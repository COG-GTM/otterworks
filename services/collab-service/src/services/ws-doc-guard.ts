import * as Y from 'yjs';
import type { Logger } from 'pino';
import { DocumentMemoryBudget } from './memory-budget';

export const WS_CLOSE_MESSAGE_TOO_BIG = 1009;

export interface SharedDocConnection {
  close(code?: number, reason?: string): void;
}

/** Shape of y-websocket's WSSharedDoc that the guard relies on. */
export interface SharedDoc extends Y.Doc {
  conns: Map<SharedDocConnection, unknown>;
}

export interface WsDocumentGuardOptions {
  docs: Map<string, SharedDoc>;
  budget: DocumentMemoryBudget;
  maxDocumentBytes: number;
  maxDocuments: number;
  logger: Logger;
}

/**
 * Bounds the y-websocket server's in-memory documents. y-websocket applies
 * updates itself and never frees documents when no persistence is configured,
 * so the guard caps the number of documents, the encoded size of each one and
 * the total across all of them, evicting idle documents first and then the
 * offending document (closing its connections) when a limit is crossed.
 */
export class WsDocumentGuard {
  private guarded: WeakSet<Y.Doc> = new WeakSet();

  constructor(private readonly opts: WsDocumentGuardOptions) {}

  canOpen(docName: string): boolean {
    const { docs, maxDocuments } = this.opts;
    if (docs.has(docName) || docs.size < maxDocuments) return true;
    this.evictIdle();
    return docs.size < maxDocuments;
  }

  attach(docName: string): void {
    const doc = this.opts.docs.get(docName);
    if (!doc || this.guarded.has(doc)) return;
    this.guarded.add(doc);

    const key = budgetKey(docName);
    this.opts.budget.set(key, Y.encodeStateAsUpdate(doc).length);
    doc.on('update', (update: Uint8Array) => this.handleUpdate(docName, doc, update));
    doc.on('destroy', () => {
      if (this.opts.docs.get(docName) !== doc) return;
      this.opts.docs.delete(docName);
      this.opts.budget.release(key);
    });
  }

  evictIdle(): void {
    for (const [name, doc] of this.opts.docs) {
      if (doc.conns.size === 0) this.evict(name, doc, 'idle');
    }
  }

  private handleUpdate(docName: string, doc: SharedDoc, update: Uint8Array): void {
    const { docs, budget, maxDocumentBytes } = this.opts;
    if (docs.get(docName) !== doc) return;

    const key = budgetKey(docName);
    let size = budget.get(key) + update.length;
    if (size > maxDocumentBytes || budget.wouldExceed(key, size)) {
      size = Y.encodeStateAsUpdate(doc).length;
    }
    budget.set(key, size);

    if (size > maxDocumentBytes) {
      this.evict(docName, doc, 'document_size_limit');
      return;
    }
    if (budget.exceeded()) {
      this.evictIdle();
      if (budget.exceeded()) this.evict(docName, doc, 'memory_budget');
    }
  }

  private evict(docName: string, doc: SharedDoc, reason: string): void {
    const { docs, budget, logger } = this.opts;
    if (docs.get(docName) !== doc) return;
    docs.delete(docName);
    budget.release(budgetKey(docName));

    const conns = Array.from(doc.conns.keys());
    for (const conn of conns) {
      conn.close(WS_CLOSE_MESSAGE_TOO_BIG, 'Document limit exceeded');
    }
    if (reason !== 'idle') {
      logger.warn(
        { documentName: docName, reason, connections: conns.length },
        'y-websocket_document_evicted',
      );
    }
    // Destroy outside the Yjs transaction that may have triggered the eviction.
    setImmediate(() => doc.destroy());
  }
}

function budgetKey(docName: string): string {
  return `ws:${docName}`;
}
