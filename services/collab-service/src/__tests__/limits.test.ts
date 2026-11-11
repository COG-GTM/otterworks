import { createServer, type Server } from 'http';
import { Server as SocketIOServer } from 'socket.io';
import { io as clientIO, Socket as ClientSocket } from 'socket.io-client';
import { WebSocket, WebSocketServer } from 'ws';
import jwt from 'jsonwebtoken';
import * as Y from 'yjs';
import * as encoding from 'lib0/encoding';
import * as syncProtocol from 'y-protocols/sync';
import * as awarenessProtocol from 'y-protocols/awareness';
import { CollaborationManager } from '../handlers/collaboration';
import { DocumentStore } from '../services/document-store';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import { createAuthMiddleware } from '../middleware/auth';
import { RedisAdapter } from '../services/redis-adapter';
import {
  DocumentSizeTracker,
  base64DecodedLength,
} from '../services/document-size-tracker';
import {
  WS_CLOSE_MESSAGE_TOO_BIG,
  YWebsocketGuard,
  docNameFromUrl,
  createYWebsocketPersistence,
  growsDocument,
} from '../services/ywebsocket-guard';

const {
  setupWSConnection,
  setPersistence,
  docs: yDocs,
  // eslint-disable-next-line @typescript-eslint/no-var-requires
} = require('y-websocket/bin/utils');

const JWT_SECRET = 'test-secret-key-for-unit-tests';

const mockRedis = {
  get: jest.fn().mockResolvedValue(null),
  set: jest.fn().mockResolvedValue(undefined),
  del: jest.fn().mockResolvedValue(undefined),
  hset: jest.fn().mockResolvedValue(undefined),
  hget: jest.fn().mockResolvedValue(null),
  hgetall: jest.fn().mockResolvedValue({}),
  hincrby: jest.fn().mockResolvedValue(1),
  lpush: jest.fn().mockResolvedValue(undefined),
  lrange: jest.fn().mockResolvedValue([]),
  ltrim: jest.fn().mockResolvedValue(undefined),
  llen: jest.fn().mockResolvedValue(0),
  expire: jest.fn().mockResolvedValue(undefined),
} as unknown as jest.Mocked<RedisAdapter>;

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
  fatal: jest.fn(),
  trace: jest.fn(),
  child: jest.fn().mockReturnThis(),
  level: 'info',
} as never;

function textUpdate(length: number): Uint8Array {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, 'x'.repeat(length));
  return Y.encodeStateAsUpdate(doc);
}

function listen(server: Server): Promise<number> {
  return new Promise((resolve) => {
    server.listen(0, () => {
      const addr = server.address();
      resolve(typeof addr === 'object' && addr ? addr.port : 0);
    });
  });
}

describe('DocumentSizeTracker', () => {
  it('accepts updates under the cap and rejects ones that would exceed it', () => {
    const tracker = new DocumentSizeTracker(1000);
    const doc = new Y.Doc();
    const small = textUpdate(100);
    expect(tracker.fits('d', doc, small.byteLength)).toBe(true);
    Y.applyUpdate(doc, small);
    tracker.add('d', small.byteLength);
    expect(tracker.fits('d', doc, 2000)).toBe(false);
    expect(tracker.fits('d', doc, 1000 - Y.encodeStateAsUpdate(doc).byteLength)).toBe(
      true,
    );
  });

  it('recomputes the exact size before rejecting on an overestimate', () => {
    const tracker = new DocumentSizeTracker(1000);
    const doc = new Y.Doc();
    tracker.set('d', 990);
    expect(tracker.fits('d', doc, 100)).toBe(true);
  });

  it('computes decoded base64 length', () => {
    for (const n of [0, 1, 2, 3, 10, 1000]) {
      const encoded = Buffer.alloc(n).toString('base64');
      expect(base64DecodedLength(encoded)).toBe(n);
    }
  });
});

describe('CollaborationManager limits', () => {
  let io: SocketIOServer;
  let httpServer: Server;
  let manager: CollaborationManager;
  let port: number;
  const clients: ClientSocket[] = [];

  beforeAll(async () => {
    httpServer = createServer();
    io = new SocketIOServer(httpServer, { maxHttpBufferSize: 64 * 1024 });
    io.use(createAuthMiddleware(JWT_SECRET, mockLogger));
    const awareness = new AwarenessService(mockLogger);
    manager = new CollaborationManager({
      io,
      documentStore: new DocumentStore(mockRedis, mockLogger),
      awareness,
      presenceHandler: new PresenceHandler(awareness, mockLogger),
      metrics: new MetricsCollector(),
      logger: mockLogger,
      persistIntervalMs: 600000,
      snapshotIntervalMs: 600000,
      limits: {
        maxMessageBytes: 4096,
        maxDocumentBytes: 8192,
        maxDocumentsPerUser: 2,
        persistDebounceMs: 200,
        snapshotMinIntervalMs: 60000,
      },
    });
    manager.start();
    port = await listen(httpServer);
  });

  afterEach(() => {
    while (clients.length) clients.pop()?.disconnect();
    jest.clearAllMocks();
  });

  afterAll(async () => {
    await manager.stop();
    io.close();
    await new Promise((resolve) => httpServer.close(resolve));
  });

  function connect(userId: string): Promise<ClientSocket> {
    const token = jwt.sign({ sub: userId, name: userId }, JWT_SECRET); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    const client = clientIO(`http://localhost:${port}`, {
      auth: { token },
      transports: ['websocket'],
    });
    clients.push(client);
    return new Promise((resolve, reject) => {
      client.on('connect', () => resolve(client));
      client.on('connect_error', reject);
    });
  }

  function join(client: ClientSocket, documentId: string) {
    return new Promise<{ success: boolean; error?: string }>((resolve) =>
      client.emit('join-document', { documentId }, resolve),
    );
  }

  function sendUpdate(client: ClientSocket, documentId: string, update: Uint8Array) {
    const error = new Promise<{ error: string }>((resolve) =>
      client.once('document-update-error', resolve),
    );
    client.emit('document-update', {
      documentId,
      update: Buffer.from(update).toString('base64'),
    });
    return error;
  }

  it('rejects a single update larger than maxMessageBytes', async () => {
    const client = await connect('size-user-1');
    await join(client, 'doc-big-update');
    const err = await sendUpdate(client, 'doc-big-update', textUpdate(5000));
    expect(err.error).toBe('Update exceeds maximum size');
    expect(
      Y.encodeStateAsUpdate(manager.getDocument('doc-big-update')!).byteLength,
    ).toBeLessThan(100);
  });

  it('stops a document from growing past maxDocumentBytes', async () => {
    const client = await connect('size-user-2');
    await join(client, 'doc-growth');
    const errors: string[] = [];
    client.on('document-update-error', (e: { error: string }) => errors.push(e.error));
    for (let i = 0; i < 6; i++) {
      const piece = new Y.Doc();
      piece.clientID = 1000 + i;
      piece.getText('content').insert(0, 'y'.repeat(3000));
      client.emit('document-update', {
        documentId: 'doc-growth',
        update: Buffer.from(Y.encodeStateAsUpdate(piece)).toString('base64'),
      });
    }
    await new Promise((r) => setTimeout(r, 300));
    expect(errors).toContain('Document size limit exceeded');
    const size = Y.encodeStateAsUpdate(manager.getDocument('doc-growth')!).byteLength;
    expect(size).toBeLessThanOrEqual(8192);
  });

  it('throttles full-state Redis writes for bursts of updates', async () => {
    const client = await connect('size-user-3');
    await join(client, 'doc-throttle');
    mockRedis.set.mockClear();
    for (let i = 0; i < 10; i++) {
      const piece = new Y.Doc();
      piece.clientID = 2000 + i;
      piece.getText('content').insert(0, 'z');
      client.emit('document-update', {
        documentId: 'doc-throttle',
        update: Buffer.from(Y.encodeStateAsUpdate(piece)).toString('base64'),
      });
    }
    await new Promise((r) => setTimeout(r, 500));
    const writes = mockRedis.set.mock.calls.filter(([key]) =>
      String(key).endsWith('doc-throttle'),
    ).length;
    expect(writes).toBeGreaterThanOrEqual(1);
    expect(writes).toBeLessThanOrEqual(2);
  });

  it('rate-limits client-requested snapshots per document', async () => {
    const client = await connect('size-user-4');
    await join(client, 'doc-snap');
    const created = new Promise((resolve) => client.once('snapshot-created', resolve));
    client.emit('request-snapshot', { documentId: 'doc-snap' });
    await created;
    const rejected = new Promise<{ error: string }>((resolve) =>
      client.once('snapshot-error', resolve),
    );
    client.emit('request-snapshot', { documentId: 'doc-snap' });
    expect((await rejected).error).toBe('Snapshot rate limit exceeded');
    expect(mockRedis.lpush).toHaveBeenCalledTimes(1);
  });

  it('does not rate-limit a snapshot retry after a failed attempt', async () => {
    const client = await connect('size-user-7');
    await join(client, 'doc-snap-retry');
    mockRedis.lpush.mockRejectedValueOnce(new Error('redis down'));
    const failed = new Promise<{ error: string }>((resolve) =>
      client.once('snapshot-error', resolve),
    );
    client.emit('request-snapshot', { documentId: 'doc-snap-retry' });
    expect((await failed).error).toBe('Failed to create snapshot');
    const created = new Promise((resolve) => client.once('snapshot-created', resolve));
    client.emit('request-snapshot', { documentId: 'doc-snap-retry' });
    await created;
  });

  it('caps the number of documents a user can hold open', async () => {
    const a = await connect('size-user-5');
    const b = await connect('size-user-5');
    const c = await connect('size-user-5');
    expect((await join(a, 'doc-cap-1')).success).toBe(true);
    expect((await join(b, 'doc-cap-2')).success).toBe(true);
    const third = await join(c, 'doc-cap-3');
    expect(third).toEqual({ success: false, error: 'Too many open documents' });
    expect(manager.getDocument('doc-cap-3')).toBeUndefined();
    // Joining an already-open document or switching documents is still allowed
    expect((await join(c, 'doc-cap-1')).success).toBe(true);
    expect((await join(b, 'doc-cap-4')).success).toBe(true);
  });

  it('lets a socket rejoin its current document while the user is at the cap', async () => {
    const a = await connect('size-user-6');
    expect((await join(a, 'doc-rejoin')).success).toBe(true);
    jest
      .spyOn(AwarenessService.prototype, 'getUserDocumentIds')
      .mockReturnValueOnce(new Set(['other-1', 'other-2']));
    expect((await join(a, 'doc-rejoin')).success).toBe(true);
  });
});

describe('YWebsocketGuard', () => {
  let httpServer: Server;
  let wss: WebSocketServer;
  let guard: YWebsocketGuard;
  let port: number;
  const sockets: WebSocket[] = [];
  const store = {
    getDocumentState: jest.fn().mockResolvedValue(null),
    saveDocumentState: jest.fn().mockResolvedValue(undefined),
  };

  beforeAll(async () => {
    httpServer = createServer();
    wss = new WebSocketServer({ noServer: true, maxPayload: 16 * 1024 });
    const persistence = createYWebsocketPersistence(store, mockLogger);
    setPersistence(persistence);
    guard = new YWebsocketGuard({
      setupWSConnection,
      docs: yDocs,
      limits: { maxDocumentBytes: 8192, maxDocumentsPerUser: 2 },
      persistence,
      logger: mockLogger,
    });
    httpServer.on('upgrade', (req, socket, head) => {
      const userId = new URL(req.url || '', 'http://x').searchParams.get('user') || '';
      if (!guard.canOpen(userId, docNameFromUrl(req.url))) {
        socket.write('HTTP/1.1 429 Too Many Requests\r\n\r\n');
        socket.destroy();
        return;
      }
      wss.handleUpgrade(req, socket, head, (ws) =>
        guard.handleConnection(ws, req, userId),
      );
    });
    port = await listen(httpServer);
  });

  afterEach(() => {
    while (sockets.length) sockets.pop()?.close();
  });

  afterAll(async () => {
    setPersistence(null);
    wss.close();
    await new Promise((resolve) => httpServer.close(resolve));
  });

  function open(docName: string, user: string): Promise<WebSocket> {
    const ws = new WebSocket(`ws://localhost:${port}/${docName}?user=${user}`);
    sockets.push(ws);
    return new Promise((resolve, reject) => {
      ws.on('open', () => resolve(ws));
      ws.on('unexpected-response', (_req, res) =>
        reject(new Error(`HTTP ${res.statusCode}`)),
      );
      ws.on('error', reject);
    });
  }

  function syncUpdateMessage(update: Uint8Array): Uint8Array {
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, 0);
    syncProtocol.writeUpdate(encoder, update);
    return encoding.toUint8Array(encoder);
  }

  function closeCode(ws: WebSocket): Promise<number> {
    return new Promise((resolve) => ws.on('close', (code) => resolve(code)));
  }

  it('applies normal Yjs updates', async () => {
    const ws = await open('yws-normal', 'u1');
    ws.send(syncUpdateMessage(textUpdate(100)));
    await new Promise((r) => setTimeout(r, 100));
    expect(yDocs.get('yws-normal').getText('content').length).toBe(100);
  });

  it('closes connections whose updates would exceed maxDocumentBytes', async () => {
    const ws = await open('yws-growth', 'u2');
    const closed = closeCode(ws);
    for (let i = 0; i < 6; i++) {
      const piece = new Y.Doc();
      piece.clientID = 3000 + i;
      piece.getText('content').insert(0, 'q'.repeat(3000));
      ws.send(syncUpdateMessage(Y.encodeStateAsUpdate(piece)));
    }
    expect(await closed).toBe(WS_CLOSE_MESSAGE_TOO_BIG);
    const doc = yDocs.get('yws-growth');
    if (doc) expect(Y.encodeStateAsUpdate(doc).byteLength).toBeLessThanOrEqual(8192);
  });

  it('keeps sync step 1 and awareness working on a nearly full document', async () => {
    const ws = await open('yws-full', 'u6');
    ws.send(syncUpdateMessage(textUpdate(8000)));
    await new Promise((r) => setTimeout(r, 100));
    const serverDoc = yDocs.get('yws-full');
    expect(serverDoc.getText('content').length).toBe(8000);

    const clientDoc = new Y.Doc();
    const awareness = new awarenessProtocol.Awareness(clientDoc);
    awareness.setLocalState({ user: 'a'.repeat(1000) });
    const awarenessMsg = encoding.createEncoder();
    encoding.writeVarUint(awarenessMsg, 1);
    encoding.writeVarUint8Array(
      awarenessMsg,
      awarenessProtocol.encodeAwarenessUpdate(awareness, [clientDoc.clientID]),
    );
    const step1 = encoding.createEncoder();
    encoding.writeVarUint(step1, 0);
    syncProtocol.writeSyncStep1(step1, clientDoc);
    awareness.destroy();

    let closed = false;
    ws.on('close', () => (closed = true));
    ws.send(encoding.toUint8Array(awarenessMsg));
    ws.send(encoding.toUint8Array(step1));
    await new Promise((r) => setTimeout(r, 100));
    expect(closed).toBe(false);
    expect(serverDoc.awareness.getStates().has(clientDoc.clientID)).toBe(true);
  });

  it('only size-checks messages that can grow the document', () => {
    const update = Buffer.from(syncUpdateMessage(textUpdate(10)));
    expect(growsDocument(update)).toBe(true);
    expect(growsDocument(Buffer.from([1, 0]))).toBe(false);
    expect(growsDocument(Buffer.from([0, 0, 0]))).toBe(false);
    expect(growsDocument(Buffer.from([]))).toBe(true);
  });

  it('rejects frames larger than maxPayload', async () => {
    const ws = await open('yws-payload', 'u3');
    const closed = closeCode(ws);
    ws.send(Buffer.alloc(32 * 1024));
    expect(await closed).toBe(WS_CLOSE_MESSAGE_TOO_BIG);
  });

  it('caps rooms per user and persists documents when the last client leaves', async () => {
    const a = await open('yws-room-1', 'u4');
    await open('yws-room-2', 'u4');
    await expect(open('yws-room-3', 'u4')).rejects.toThrow('HTTP 429');
    // Re-opening an already-open room is fine; other users are unaffected
    await open('yws-room-1', 'u4');
    await open('yws-room-3', 'u5');
    a.send(syncUpdateMessage(textUpdate(42)));

    const closed = closeCode(a);
    a.close();
    await closed;
    expect(yDocs.has('yws-room-1')).toBe(true);
    while (sockets.length) sockets.pop()?.close();
    await new Promise((r) => setTimeout(r, 200));
    expect(yDocs.has('yws-room-1')).toBe(false);
    expect(yDocs.has('yws-room-2')).toBe(false);
    const saved = store.saveDocumentState.mock.calls.find(
      ([name]) => name === 'yws-room-1',
    );
    expect(saved).toBeDefined();
    await open('yws-room-4', 'u4');

    // Reopening restores the persisted state instead of starting empty
    store.getDocumentState.mockImplementation(async (name: string) =>
      name === 'yws-room-1' ? new Uint8Array(saved![1]) : null,
    );
    await open('yws-room-1', 'u6');
    await new Promise((r) => setTimeout(r, 100));
    expect(yDocs.get('yws-room-1').getText('content').length).toBe(42);
  });

  it('flushes in-memory documents on shutdown', async () => {
    const ws = await open('yws-flush', 'u7');
    ws.send(syncUpdateMessage(textUpdate(5)));
    await new Promise((r) => setTimeout(r, 100));
    store.saveDocumentState.mockClear();
    await guard.flush();
    expect(store.saveDocumentState).toHaveBeenCalledWith('yws-flush', expect.any(Buffer));
  });
});
