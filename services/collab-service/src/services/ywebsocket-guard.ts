import type { Logger } from 'pino';
import type { RawData, WebSocket } from 'ws';

export interface YWebsocketLimits {
  maxPayloadBytes: number;
  maxDocBytes: number;
  maxDocs: number;
  maxDocNameLength: number;
  maxConnectionsPerUser: number;
  maxRoomsPerUser: number;
  rateWindowMs: number;
  maxMessagesPerWindow: number;
  maxBytesPerWindow: number;
  /** Minimum time a room must be connection-free before it may be evicted. */
  idleEvictMs: number;
}

/** Subset of y-websocket's WSSharedDoc that the guard relies on. */
export interface SharedDocLike {
  conns: Map<unknown, unknown>;
  on(event: 'update', cb: (update: Uint8Array) => void): void;
  destroy(): void;
}

export type Admission =
  | { ok: true }
  | { ok: false; status: 400 | 429 | 503; reason: string };

export const CLOSE_POLICY_VIOLATION = 1008;
export const CLOSE_MESSAGE_TOO_BIG = 1009;
export const CLOSE_TRY_AGAIN_LATER = 1013;

const MESSAGE_SYNC = 0;
const SYNC_STEP2 = 1;
const SYNC_UPDATE = 2;
const DOC_NAME_PATTERN = /^[A-Za-z0-9._:-]+$/;

/** Same derivation as y-websocket's setupWSConnection default. */
export function docNameFromUrl(url: string | undefined): string {
  return (url || '').slice(1).split('?')[0];
}

export function rawDataByteLength(data: RawData): number {
  if (Array.isArray(data)) {
    return data.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  }
  return data.byteLength;
}

function toBytes(data: RawData): Uint8Array {
  if (Array.isArray(data)) {
    return new Uint8Array(Buffer.concat(data));
  }
  return data instanceof ArrayBuffer ? new Uint8Array(data) : data;
}

function readVarUint(bytes: Uint8Array, offset: number): [number, number] | null {
  let value = 0;
  let shift = 0;
  for (let i = offset; i < bytes.length && shift < 35; i++) {
    const byte = bytes[i];
    value += (byte & 0x7f) * 2 ** shift;
    if (byte < 0x80) {
      return [value, i + 1];
    }
    shift += 7;
  }
  return null;
}

/** True for y-protocols sync messages that apply content to the shared doc. */
export function isDocUpdateMessage(data: RawData): boolean {
  const bytes = toBytes(data);
  const messageType = readVarUint(bytes, 0);
  if (!messageType || messageType[0] !== MESSAGE_SYNC) {
    return false;
  }
  const syncType = readVarUint(bytes, messageType[1]);
  return !!syncType && (syncType[0] === SYNC_STEP2 || syncType[0] === SYNC_UPDATE);
}

interface ConnectionState {
  windowStart: number;
  messages: number;
  bytes: number;
}

/**
 * Bounds the memory a y-websocket client can pin: rooms and connections per user,
 * total in-memory docs, per-doc state size, and per-connection message rate.
 */
export class YWebsocketGuard {
  private readonly userRooms = new Map<string, Map<string, number>>();
  private readonly docBytes = new WeakMap<SharedDocLike, number>();
  private readonly docLastActive = new WeakMap<SharedDocLike, number>();

  constructor(
    private readonly limits: YWebsocketLimits,
    private readonly docs: Map<string, SharedDocLike>,
    private readonly measureDoc: (doc: SharedDocLike) => number,
    private readonly logger: Logger,
    private readonly now: () => number = Date.now,
  ) {}

  admit(userId: string, docName: string): Admission {
    if (
      !docName ||
      docName.length > this.limits.maxDocNameLength ||
      !DOC_NAME_PATTERN.test(docName)
    ) {
      return { ok: false, status: 400, reason: 'invalid document name' };
    }

    const rooms = this.userRooms.get(userId);
    const connections = rooms ? [...rooms.values()].reduce((a, b) => a + b, 0) : 0;
    if (connections >= this.limits.maxConnectionsPerUser) {
      return { ok: false, status: 429, reason: 'too many connections' };
    }
    if (!rooms?.has(docName) && (rooms?.size ?? 0) >= this.limits.maxRoomsPerUser) {
      return { ok: false, status: 429, reason: 'too many documents' };
    }
    if (!this.docs.has(docName) && this.docs.size >= this.limits.maxDocs) {
      if (!this.evictIdleDoc()) {
        return { ok: false, status: 503, reason: 'document capacity reached' };
      }
    }
    return { ok: true };
  }

  /**
   * Re-checks admission for an upgraded socket, then wires limits around it.
   * `setup` must register the connection with y-websocket (creating the doc).
   * Returns false (and closes the socket) when the connection is refused.
   */
  attach(conn: WebSocket, userId: string, docName: string, setup: () => void): boolean {
    // ws emits 'error' (e.g. maxPayload exceeded) before closing; unhandled it crashes the process.
    conn.on('error', (err: Error) => {
      this.logger.warn({ docName, error: err.message }, 'y-websocket_connection_error');
    });

    const admission = this.admit(userId, docName);
    if (!admission.ok) {
      this.logger.warn(
        { userId, docName, reason: admission.reason },
        'y-websocket_connection_refused',
      );
      conn.close(
        admission.status === 503 ? CLOSE_TRY_AGAIN_LATER : CLOSE_POLICY_VIOLATION,
        admission.reason,
      );
      return false;
    }

    this.addRoom(userId, docName);
    conn.once('close', () => {
      this.removeRoom(userId, docName);
      this.touchDoc(docName);
    });

    const state: ConnectionState = { windowStart: this.now(), messages: 0, bytes: 0 };
    const emit = conn.emit.bind(conn);
    conn.emit = ((event: string | symbol, ...args: unknown[]): boolean => {
      if (
        event === 'message' &&
        !this.allowMessage(conn, state, docName, args[0] as RawData)
      ) {
        return false;
      }
      return emit(event, ...args);
    }) as WebSocket['emit'];

    setup();
    this.trackDoc(docName);
    this.touchDoc(docName);
    return true;
  }

  private allowMessage(
    conn: WebSocket,
    state: ConnectionState,
    docName: string,
    data: RawData,
  ): boolean {
    if (conn.readyState !== conn.OPEN) {
      return false;
    }
    const size = rawDataByteLength(data);
    const now = this.now();
    if (now - state.windowStart >= this.limits.rateWindowMs) {
      state.windowStart = now;
      state.messages = 0;
      state.bytes = 0;
    }
    state.messages += 1;
    state.bytes += size;
    if (
      state.messages > this.limits.maxMessagesPerWindow ||
      state.bytes > this.limits.maxBytesPerWindow
    ) {
      this.logger.warn({ docName }, 'y-websocket_rate_limit_exceeded');
      conn.close(CLOSE_POLICY_VIOLATION, 'rate limit exceeded');
      return false;
    }

    const doc = this.docs.get(docName);
    if (doc && isDocUpdateMessage(data)) {
      let current = this.docBytes.get(doc) ?? 0;
      if (current + size > this.limits.maxDocBytes) {
        // The running total over-counts (edits/deletes compact); re-measure before refusing.
        current = this.measureDoc(doc);
        this.docBytes.set(doc, current);
      }
      if (current + size > this.limits.maxDocBytes) {
        this.logger.warn(
          { docName, docBytes: current, messageBytes: size },
          'y-websocket_document_size_limit_exceeded',
        );
        conn.close(CLOSE_MESSAGE_TOO_BIG, 'document size limit exceeded');
        return false;
      }
    }
    return true;
  }

  private trackDoc(docName: string): void {
    const doc = this.docs.get(docName);
    if (!doc || this.docBytes.has(doc)) {
      return;
    }
    this.docBytes.set(doc, this.measureDoc(doc));
    doc.on('update', (update: Uint8Array) => {
      this.docBytes.set(doc, (this.docBytes.get(doc) ?? 0) + update.byteLength);
    });
  }

  private touchDoc(docName: string): void {
    const doc = this.docs.get(docName);
    if (doc) {
      this.docLastActive.set(doc, this.now());
    }
  }

  private evictIdleDoc(): boolean {
    const now = this.now();
    for (const [name, doc] of this.docs) {
      const lastActive = this.docLastActive.get(doc) ?? 0;
      if (doc.conns.size === 0 && now - lastActive >= this.limits.idleEvictMs) {
        this.docs.delete(name);
        doc.destroy();
        this.logger.info({ docName: name }, 'y-websocket_idle_document_evicted');
        return true;
      }
    }
    return false;
  }

  private addRoom(userId: string, docName: string): void {
    const rooms = this.userRooms.get(userId) ?? new Map<string, number>();
    rooms.set(docName, (rooms.get(docName) ?? 0) + 1);
    this.userRooms.set(userId, rooms);
  }

  private removeRoom(userId: string, docName: string): void {
    const rooms = this.userRooms.get(userId);
    if (!rooms) {
      return;
    }
    const count = (rooms.get(docName) ?? 0) - 1;
    if (count > 0) {
      rooms.set(docName, count);
    } else {
      rooms.delete(docName);
    }
    if (rooms.size === 0) {
      this.userRooms.delete(userId);
    }
  }
}
