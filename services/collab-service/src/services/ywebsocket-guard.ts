import type { IncomingMessage } from 'http';
import type { Logger } from 'pino';
import type { RawData, WebSocket } from 'ws';
import type * as Y from 'yjs';
import type { CollabLimits } from '../config';
import { DocumentSizeTracker } from './document-size-tracker';

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
  limits: Pick<
    CollabLimits,
    'maxDocumentBytes' | 'maxDocumentsPerUser' | 'idleDocumentEvictMs'
  >;
  logger: Logger;
}

export function docNameFromUrl(url: string | undefined): string {
  return (url || '/').slice(1).split('?')[0];
}

function rawDataLength(data: RawData): number {
  if (Array.isArray(data)) return data.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  return data.byteLength;
}

/**
 * Wraps y-websocket's setupWSConnection with per-document size caps, per-user
 * room caps and eviction of idle documents (y-websocket keeps them forever
 * when no persistence is configured).
 */
export class YWebsocketGuard {
  private tracker: DocumentSizeTracker;
  private userDocs: Map<string, Map<string, number>> = new Map();
  private trackedDocs: WeakSet<Y.Doc> = new WeakSet();
  private evictionTimers: Map<string, NodeJS.Timeout> = new Map();

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
    this.cancelEviction(docName);

    const originalOn = conn.on.bind(conn) as OnFn;
    const guardedOn: OnFn = (event, listener) => {
      if (event !== 'message') return originalOn(event, listener);
      return originalOn('message', (...args: unknown[]) => {
        const size = rawDataLength(args[0] as RawData);
        const doc = docs.get(docName);
        if (doc && !this.tracker.fits(docName, doc, size)) {
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
      this.scheduleEvictionIfIdle(docName);
    });
  }

  stop(): void {
    for (const timer of this.evictionTimers.values()) clearTimeout(timer);
    this.evictionTimers.clear();
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

  private cancelEviction(docName: string): void {
    const timer = this.evictionTimers.get(docName);
    if (timer) {
      clearTimeout(timer);
      this.evictionTimers.delete(docName);
    }
  }

  private scheduleEvictionIfIdle(docName: string): void {
    const doc = this.options.docs.get(docName);
    if (!doc || doc.conns.size > 0) return;
    this.cancelEviction(docName);
    const timer = setTimeout(() => {
      this.evictionTimers.delete(docName);
      const current = this.options.docs.get(docName);
      if (!current || current.conns.size > 0) return;
      this.options.docs.delete(docName);
      this.tracker.delete(docName);
      current.destroy();
      this.options.logger.info({ docName }, 'y-websocket_idle_document_evicted');
    }, this.options.limits.idleDocumentEvictMs);
    timer.unref();
    this.evictionTimers.set(docName, timer);
  }
}
