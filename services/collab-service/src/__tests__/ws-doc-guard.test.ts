import * as Y from 'yjs';
import { DocumentMemoryBudget } from '../services/memory-budget';
import {
  SharedDoc,
  SharedDocConnection,
  WsDocumentGuard,
  WS_CLOSE_MESSAGE_TOO_BIG,
} from '../services/ws-doc-guard';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function makeDoc(withConn = true): { doc: SharedDoc; conn: SharedDocConnection } {
  const doc = new Y.Doc() as SharedDoc;
  doc.conns = new Map();
  const conn = { close: jest.fn() };
  if (withConn) doc.conns.set(conn, new Set());
  return { doc, conn };
}

interface SetupOptions {
  maxDocumentBytes?: number;
  maxDocuments?: number;
  total?: number;
}

function setup(opts: SetupOptions) {
  const docs = new Map<string, SharedDoc>();
  const budget = new DocumentMemoryBudget(opts.total ?? 1024 * 1024);
  const guard = new WsDocumentGuard({
    docs,
    budget,
    maxDocumentBytes: opts.maxDocumentBytes ?? 1024 * 1024,
    maxDocuments: opts.maxDocuments ?? 10,
    logger: mockLogger,
  });
  return { docs, budget, guard };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

describe('WsDocumentGuard', () => {
  it('evicts and disconnects a document that outgrows the per-document cap', async () => {
    const { docs, budget, guard } = setup({ maxDocumentBytes: 1000 });
    const { doc, conn } = makeDoc();
    docs.set('big', doc);
    guard.attach('big');

    doc.getText('t').insert(0, 'small');
    expect(docs.has('big')).toBe(true);

    doc.getText('t').insert(0, 'x'.repeat(2000));
    expect(docs.has('big')).toBe(false);
    expect(budget.get('ws:big')).toBe(0);
    expect(conn.close).toHaveBeenCalledWith(WS_CLOSE_MESSAGE_TOO_BIG, expect.any(String));
    await flush();
  });

  it('evicts idle documents before the active one when over budget', async () => {
    const { docs, guard } = setup({ total: 3000 });
    const idle = makeDoc(false);
    docs.set('idle', idle.doc);
    guard.attach('idle');
    idle.doc.getText('t').insert(0, 'i'.repeat(1500));

    const active = makeDoc();
    docs.set('active', active.doc);
    guard.attach('active');
    active.doc.getText('t').insert(0, 'a'.repeat(2000));

    expect(docs.has('idle')).toBe(false);
    expect(docs.has('active')).toBe(true);
    expect(active.conn.close).not.toHaveBeenCalled();
    await flush();
  });

  it('caps the number of documents, freeing idle ones first', async () => {
    const { docs, guard } = setup({ maxDocuments: 2 });
    const a = makeDoc();
    const b = makeDoc(false);
    docs.set('a', a.doc);
    docs.set('b', b.doc);
    guard.attach('a');
    guard.attach('b');

    expect(guard.canOpen('a')).toBe(true);
    expect(guard.canOpen('c')).toBe(true);
    expect(docs.has('b')).toBe(false);

    docs.set('c', makeDoc().doc);
    expect(guard.canOpen('d')).toBe(false);
    await flush();
  });
});
