import * as Y from 'yjs';
import type { Logger } from 'pino';
import { DocumentMemoryBudget } from './memory-budget';

export const WS_CLOSE_MESSAGE_TOO_BIG = 1009;

export interface SharedDocConnection {
  close(code?: number, reason?: string): void;
  terminate?: () => void;
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
 * Bounds the y-websocket server's in-memory documents: caps how many exist and
 * tracks each one's encoded size against the shared memory budget. A document
 * that outgrows its cap (or pushes the total over budget) has its connections
 * dropped; y-websocket then persists and destroys it once the last one closes.
 */
export class WsDocumentGuard {
  private owners: Map<string, Y.Doc> = new Map();

  constructor(private readonly opts: WsDocumentGuardOptions) {}

  canOpen(docName: string): boolean {
    const { docs, maxDocuments } = this.opts;
    return docs.has(docName) || docs.size < maxDocuments;
  }

  attach(docName: string): void {
    const doc = this.opts.docs.get(docName);
    if (!doc || this.owners.get(docName) === doc) return;
    this.owners.set(docName, doc);

    const key = budgetKey(docName);
    this.opts.budget.set(key, Y.encodeStateAsUpdate(doc).length);
    doc.on('update', (update: Uint8Array) => this.handleUpdate(docName, doc, update));
    doc.on('destroy', () => {
      if (this.owners.get(docName) !== doc) return;
      this.owners.delete(docName);
      this.opts.budget.release(key);
    });
  }

  private handleUpdate(docName: string, doc: SharedDoc, update: Uint8Array): void {
    const { budget, maxDocumentBytes } = this.opts;
    if (this.owners.get(docName) !== doc) return;

    const key = budgetKey(docName);
    let size = budget.get(key) + update.length;
    if (size > maxDocumentBytes || budget.wouldExceed(key, size)) {
      size = Y.encodeStateAsUpdate(doc).length;
    }
    budget.set(key, size);

    if (size > maxDocumentBytes) this.disconnect(docName, doc, 'document_size_limit');
    else if (budget.exceeded()) this.disconnect(docName, doc, 'memory_budget');
  }

  private disconnect(docName: string, doc: SharedDoc, reason: string): void {
    const conns = Array.from(doc.conns.keys());
    for (const conn of conns) {
      // terminate() stops reading immediately; close() would wait for the handshake
      if (conn.terminate) conn.terminate();
      else conn.close(WS_CLOSE_MESSAGE_TOO_BIG, 'Document limit exceeded');
    }
    this.opts.logger.warn(
      { documentName: docName, reason, connections: conns.length },
      'y-websocket_document_disconnected',
    );
  }
}

function budgetKey(docName: string): string {
  return `ws:${docName}`;
}
