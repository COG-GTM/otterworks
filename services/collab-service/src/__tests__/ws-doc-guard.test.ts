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

describe('WsDocumentGuard', () => {
  it('disconnects a document that outgrows the per-document cap', () => {
    const { docs, budget, guard } = setup({ maxDocumentBytes: 1000 });
    const { doc, conn } = makeDoc();
    docs.set('big', doc);
    guard.attach('big');

    doc.getText('t').insert(0, 'small');
    expect(conn.close).not.toHaveBeenCalled();

    doc.getText('t').insert(0, 'x'.repeat(2000));
    expect(conn.close).toHaveBeenCalledWith(WS_CLOSE_MESSAGE_TOO_BIG, expect.any(String));
    expect(budget.get('ws:big')).toBeGreaterThan(1000);
  });

  it('disconnects the document that pushes the total over budget', () => {
    const { docs, guard } = setup({ total: 3000 });
    const first = makeDoc();
    docs.set('first', first.doc);
    guard.attach('first');
    first.doc.getText('t').insert(0, 'i'.repeat(1500));

    const second = makeDoc();
    docs.set('second', second.doc);
    guard.attach('second');
    second.doc.getText('t').insert(0, 'a'.repeat(2000));

    expect(first.conn.close).not.toHaveBeenCalled();
    expect(second.conn.close).toHaveBeenCalled();
  });

  it('prefers terminate() so no further frames are read', () => {
    const { docs, guard } = setup({ maxDocumentBytes: 100 });
    const { doc } = makeDoc(false);
    const conn = { close: jest.fn(), terminate: jest.fn() };
    doc.conns.set(conn, new Set());
    docs.set('t', doc);
    guard.attach('t');
    doc.getText('t').insert(0, 'x'.repeat(200));
    expect(conn.terminate).toHaveBeenCalled();
    expect(conn.close).not.toHaveBeenCalled();
  });

  it('releases the budget when y-websocket destroys the document', () => {
    const { docs, budget, guard } = setup({});
    const { doc } = makeDoc();
    docs.set('d', doc);
    guard.attach('d');
    doc.getText('t').insert(0, 'hello');
    expect(budget.total).toBeGreaterThan(0);
    docs.delete('d');
    doc.destroy();
    expect(budget.total).toBe(0);
  });

  it('caps the number of open documents', () => {
    const { docs, guard } = setup({ maxDocuments: 2 });
    docs.set('a', makeDoc().doc);
    docs.set('b', makeDoc().doc);
    expect(guard.canOpen('a')).toBe(true);
    expect(guard.canOpen('c')).toBe(false);
  });
});
