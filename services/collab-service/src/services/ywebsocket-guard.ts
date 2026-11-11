import type { IncomingMessage } from 'http';
import type { Logger } from 'pino';
import type { RawData, WebSocket } from 'ws';
import * as decoding from 'lib0/decoding';
import * as Y from 'yjs';
import type { CollabLimits } from '../config';
import { DocumentSizeTracker } from './document-size-tracker';
import type { DocumentStore } from './document-store';

export const WS_CLOSE_MESSAGE_TOO_BIG = 1009;

type SharedDoc = Y.Doc & { conns: Map<unknown, unknown> };
type Listener = (...args: unknown[]) => void;
type OnFn = (event: string, listener: Listener) => WebSocket;

export interface YWebsocketGuardOptions {
  setupWSConnection: (
    conn: WebSocket,
    req: IncomingMessage,
    opts: { docName: string },
  ) => void;
  docs: Map<string, SharedDoc>;
  limits: Pick<CollabLimits, 'maxDocumentBytes' | 'maxDocumentsPerUser'>;
  persistence?: YWebsocketPersistence;
  logger: Logger;
}

export interface YWebsocketPersistence {
  bindState(docName: string, doc: Y.Doc): Promise<void>;
  writeState(docName: string, doc: Y.Doc): Promise<void>;
  /** Wait for in-flight writes and retry any that failed (e.g. on shutdown). */
  drain?(): Promise<void>;
}

/**
 * y-websocket persistence backed by the Redis document store. With a
 * persistence layer set, y-websocket writes a document's state and drops it
 * from memory when its last connection closes, and reloads it on next open.
 *
 * Writes for the same document are serialized and a reload waits for them, so a
 * reconnect during a save never starts from stale state. A state whose write
 * failed is kept in memory and merged into the next load (or retried by
 * `drain`) instead of being lost when y-websocket destroys the document. That
 * buffer is capped at `maxUnsavedBytes`; beyond it the oldest states are dropped.
 */
export function createYWebsocketPersistence(
  store: Pick<DocumentStore, 'getDocumentState' | 'saveDocumentState'>,
  logger: Logger,
  maxUnsavedBytes = 64 * 1024 * 1024,
): YWebsocketPersistence {
  const writes = new Map<string, Promise<void>>();
  const unsaved = new Map<string, Uint8Array>();
  let unsavedBytes = 0;

  const forget = (docName: string): void => {
    const state = unsaved.get(docName);
    if (!state) return;
    unsaved.delete(docName);
    unsavedBytes -= state.byteLength;
  };

  const keep = (docName: string, state: Uint8Array): void => {
    forget(docName);
    unsaved.set(docName, state);
    unsavedBytes += state.byteLength;
    for (const name of unsaved.keys()) {
      if (unsavedBytes <= maxUnsavedBytes) break;
      forget(name);
      logger.error({ docName: name }, 'y-websocket_unsaved_state_dropped');
    }
  };

  const save = async (docName: string, state: Uint8Array): Promise<void> => {
    try {
      await store.saveDocumentState(docName, Buffer.from(state));
      forget(docName);
    } catch (err) {
      keep(docName, state);
      logger.error({ err, docName }, 'y-websocket_persist_state_failed');
    }
  };

  const enqueue = (docName: string, state: Uint8Array): Promise<void> => {
    const write = (writes.get(docName) ?? Promise.resolve()).then(() =>
      save(docName, state),
    );
    writes.set(docName, write);
    void write.then(() => {
      if (writes.get(docName) === write) writes.delete(docName);
    });
    return write;
  };

  return {
    async bindState(docName, doc) {
      await writes.get(docName);
      const pending = unsaved.get(docName);
      if (pending) Y.applyUpdate(doc, pending);
      try {
        const state = await store.getDocumentState(docName);
        if (state) Y.applyUpdate(doc, state);
      } catch (err) {
        logger.error({ err, docName }, 'y-websocket_load_state_failed');
      }
    },
    writeState(docName, doc) {
      return enqueue(docName, Y.encodeStateAsUpdate(doc));
    },
    async drain() {
      await Promise.all(writes.values());
      await Promise.all(Array.from(unsaved).map(([name, state]) => enqueue(name, state)));
    },
  };
}

export function docNameFromUrl(url: string | undefined): string {
  return (url || '/').slice(1).split('?')[0];
}

function rawDataLength(data: RawData): number {
  if (Array.isArray(data)) return data.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  return data.byteLength;
}

// y-protocols message types: only sync step 2 and sync updates add content
// to the document; sync step 1 and awareness messages do not.
const MESSAGE_SYNC = 0;
const SYNC_STEP_2 = 1;
const SYNC_UPDATE = 2;

export function growsDocument(data: RawData): boolean {
  const bytes = Array.isArray(data)
    ? Buffer.concat(data)
    : data instanceof ArrayBuffer
      ? new Uint8Array(data)
      : data;
  try {
    const decoder = decoding.createDecoder(bytes);
    if (decoding.readVarUint(decoder) !== MESSAGE_SYNC) return false;
    const step = decoding.readVarUint(decoder);
    return step === SYNC_STEP_2 || step === SYNC_UPDATE;
  } catch {
    return true;
  }
}

/**
 * Wraps y-websocket's setupWSConnection with per-document size caps and
 * per-user room caps.
 */
export class YWebsocketGuard {
  private tracker: DocumentSizeTracker;
  private userDocs: Map<string, Map<string, number>> = new Map();
  private trackedDocs: WeakSet<Y.Doc> = new WeakSet();

  constructor(private readonly options: YWebsocketGuardOptions) {
    this.tracker = new DocumentSizeTracker(options.limits.maxDocumentBytes);
  }

  canOpen(userId: string, docName: string): boolean {
    const openDocs = this.userDocs.get(userId);
    if (!openDocs || openDocs.has(docName)) return true;
    return openDocs.size < this.options.limits.maxDocumentsPerUser;
  }

  handleConnection(conn: WebSocket, req: IncomingMessage, userId: string): void {
    const { setupWSConnection, docs, logger } = this.options;
    const docName = docNameFromUrl(req.url);
    this.retain(userId, docName);

    const originalOn = conn.on.bind(conn) as OnFn;
    const guardedOn: OnFn = (event, listener) => {
      if (event !== 'message') return originalOn(event, listener);
      return originalOn('message', (...args: unknown[]) => {
        const data = args[0] as RawData;
        const size = rawDataLength(data);
        const doc = docs.get(docName);
        if (doc && growsDocument(data) && !this.tracker.fits(docName, doc, size)) {
          logger.warn(
            { docName, userId, size, limit: this.tracker.limit },
            'y-websocket_document_size_limit_exceeded',
          );
          conn.close(WS_CLOSE_MESSAGE_TOO_BIG, 'Document size limit exceeded');
          return;
        }
        listener(...args);
      });
    };
    (conn as unknown as { on: OnFn }).on = guardedOn;
    try {
      setupWSConnection(conn, req, { docName });
    } finally {
      delete (conn as unknown as { on?: OnFn }).on;
    }

    const doc = docs.get(docName);
    if (doc && !this.trackedDocs.has(doc)) {
      this.trackedDocs.add(doc);
      doc.on('update', (update: Uint8Array) =>
        this.tracker.add(docName, update.byteLength),
      );
    }

    // ws emits 'error' (e.g. maxPayload exceeded) before closing; without a
    // listener the EventEmitter would throw and crash the process.
    conn.on('error', (err) => {
      logger.warn({ docName, userId, err: err.message }, 'y-websocket_connection_error');
    });
    conn.on('close', () => {
      this.release(userId, docName);
      if (!docs.has(docName)) this.tracker.delete(docName);
    });
  }

  /** Persist every in-memory document (e.g. on shutdown). */
  async flush(): Promise<void> {
    const { persistence, docs } = this.options;
    if (!persistence) return;
    await Promise.all(
      Array.from(docs.entries()).map(([name, doc]) => persistence.writeState(name, doc)),
    );
    await persistence.drain?.();
  }

  private retain(userId: string, docName: string): void {
    let openDocs = this.userDocs.get(userId);
    if (!openDocs) {
      openDocs = new Map();
      this.userDocs.set(userId, openDocs);
    }
    openDocs.set(docName, (openDocs.get(docName) ?? 0) + 1);
  }

  private release(userId: string, docName: string): void {
    const openDocs = this.userDocs.get(userId);
    if (!openDocs) return;
    const count = (openDocs.get(docName) ?? 0) - 1;
    if (count > 0) openDocs.set(docName, count);
    else openDocs.delete(docName);
    if (openDocs.size === 0) this.userDocs.delete(userId);
  }
}
