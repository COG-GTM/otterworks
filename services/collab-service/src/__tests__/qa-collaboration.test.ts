import { Server as SocketIOServer, type Socket } from 'socket.io';
import { createServer } from 'http';
import { io as clientIO, Socket as ClientSocket } from 'socket.io-client';
import * as Y from 'yjs';
import { CollaborationManager } from '../handlers/collaboration';
import { DocumentStore } from '../services/document-store';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import { createAuthMiddleware } from '../middleware/auth';
import {
  QA_JWT_SECRET,
  createMockLogger,
  createMockRedis,
  signToken,
  sleep,
} from './qa-test-helpers';

const mockRedis = createMockRedis();
const logger = createMockLogger();

function yUpdateWithText(
  text: string,
  clientId?: number,
): { doc: Y.Doc; update: string } {
  const doc = new Y.Doc();
  if (clientId !== undefined) doc.clientID = clientId;
  doc.getText('content').insert(0, text);
  return { doc, update: Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64') };
}

function waitFor<T = unknown>(
  client: ClientSocket,
  event: string,
  timeoutMs = 2000,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`timeout waiting for ${event}`)),
      timeoutMs,
    );
    client.once(event, (data: T) => {
      clearTimeout(timer);
      resolve(data);
    });
  });
}

function collect(client: ClientSocket, event: string): unknown[] {
  const seen: unknown[] = [];
  client.on(event, (data: unknown) => seen.push(data));
  return seen;
}

describe('QA: CollaborationManager over Socket.IO', () => {
  let io: SocketIOServer;
  let httpServer: ReturnType<typeof createServer>;
  let manager: CollaborationManager;
  let awareness: AwarenessService;
  let port = 0;
  const clients: ClientSocket[] = [];

  beforeAll((done) => {
    httpServer = createServer();
    io = new SocketIOServer(httpServer, { cors: { origin: '*' } });
    io.use(createAuthMiddleware(QA_JWT_SECRET, logger));
    awareness = new AwarenessService(logger);
    manager = new CollaborationManager({
      io,
      documentStore: new DocumentStore(mockRedis, logger),
      awareness,
      presenceHandler: new PresenceHandler(awareness, logger),
      metrics: new MetricsCollector(),
      logger,
      persistIntervalMs: 600000,
      snapshotIntervalMs: 600000,
    });
    manager.start();
    httpServer.listen(0, () => {
      const addr = httpServer.address();
      port = typeof addr === 'object' && addr ? addr.port : 0;
      done();
    });
  });

  afterAll(async () => {
    await manager.stop();
    io.close();
    await new Promise((resolve) => httpServer.close(resolve));
  });

  afterEach(() => {
    while (clients.length) clients.pop()?.disconnect();
    jest.clearAllMocks();
    mockRedis.get.mockResolvedValue(null);
    mockRedis.set.mockResolvedValue(undefined);
    mockRedis.lrange.mockResolvedValue([]);
    mockRedis.lpush.mockResolvedValue(undefined);
  });

  async function connect(userId: string, name = userId): Promise<ClientSocket> {
    const client = clientIO(`http://localhost:${port}`, {
      auth: { token: signToken({ sub: userId, name, email: `${userId}@example.test` }) },
      transports: ['websocket'],
      reconnection: false,
    });
    clients.push(client);
    await waitFor(client, 'connect');
    return client;
  }

  function join(client: ClientSocket, documentId: string): Promise<{ success: boolean }> {
    return new Promise((resolve) =>
      client.emit('join-document', { documentId }, resolve),
    );
  }

  describe('join / leave / presence', () => {
    it('acks the join, sends sync-document and a presence-update with the joiner', async () => {
      const alice = await connect('alice', 'Alice');
      const sync = waitFor<{ documentId: string; state: string }>(alice, 'sync-document');
      const presence = waitFor<{ count: number; users: Array<{ userId: string }> }>(
        alice,
        'presence-update',
      );
      await expect(join(alice, 'doc-join')).resolves.toEqual({ success: true });
      expect((await sync).documentId).toBe('doc-join');
      const p = await presence;
      expect(p.count).toBe(1);
      expect(p.users[0].userId).toBe('alice');
    });

    it('notifies existing members with user-joined including the assigned color', async () => {
      const alice = await connect('alice2', 'Alice');
      await join(alice, 'doc-uj');
      const bob = await connect('bob2', 'Bob');
      const joined = waitFor<{ userId: string; displayName: string; color: string }>(
        alice,
        'user-joined',
      );
      await join(bob, 'doc-uj');
      const evt = await joined;
      expect(evt).toMatchObject({ userId: 'bob2', displayName: 'Bob' });
      expect(evt.color).toMatch(/^#[0-9A-F]{6}$/i);
    });

    it('switching documents leaves the old room and updates presence there', async () => {
      const alice = await connect('alice3');
      const bob = await connect('bob3');
      await join(alice, 'doc-old');
      await join(bob, 'doc-old');
      const left = waitFor<{ userId: string }>(alice, 'user-left');
      await join(bob, 'doc-new');
      expect((await left).userId).toBe('bob3');
      expect(awareness.getDocumentUserCount('doc-old')).toBe(1);
      expect(awareness.getUserDocument(bob.id!)).toBe('doc-new');
    });

    it('leave-document uses the server-tracked document, not the client-supplied id', async () => {
      const alice = await connect('alice4');
      const bob = await connect('bob4');
      await join(alice, 'doc-tracked');
      await join(bob, 'doc-tracked');
      const left = waitFor<{ userId: string }>(alice, 'user-left');
      bob.emit('leave-document', { documentId: 'some-other-doc' });
      expect((await left).userId).toBe('bob4');
      expect(awareness.getDocumentUserCount('doc-tracked')).toBe(1);
    });

    it('last member leaving persists the doc to Redis and evicts it from memory', async () => {
      const alice = await connect('alice5');
      await join(alice, 'doc-evict');
      expect(manager.getDocument('doc-evict')).toBeDefined();
      alice.emit('leave-document', { documentId: 'doc-evict' });
      await sleep(150);
      expect(mockRedis.set).toHaveBeenCalledWith(
        'doc:state:doc-evict',
        expect.any(Buffer),
        86400,
      );
      expect(manager.getDocument('doc-evict')).toBeUndefined();
    });

    it('disconnect broadcasts user-left and presence-update to remaining members', async () => {
      const alice = await connect('alice6');
      const bob = await connect('bob6');
      await join(alice, 'doc-disc');
      await join(bob, 'doc-disc');
      const left = waitFor<{ userId: string }>(alice, 'user-left');
      const presences = collect(alice, 'presence-update') as Array<{ count: number }>;
      bob.disconnect();
      expect((await left).userId).toBe('bob6');
      await sleep(100);
      expect(presences[presences.length - 1].count).toBe(1);
    });

    it('returns success:false and leaves the room when loading state from Redis fails', async () => {
      mockRedis.get.mockRejectedValueOnce(new Error('redis down'));
      const alice = await connect('alice7');
      await expect(join(alice, 'doc-redis-fail')).resolves.toEqual({
        success: false,
        error: 'Failed to join document',
      });
      expect(
        io.sockets.adapter.rooms.get('doc:doc-redis-fail')?.has(alice.id!) ?? false,
      ).toBe(false);
    });
  });

  describe('CRDT update fan-out and reconnect', () => {
    it('applies a Yjs update server-side, fans it out and persists it', async () => {
      const alice = await connect('alice8');
      const bob = await connect('bob8');
      await join(alice, 'doc-crdt');
      await join(bob, 'doc-crdt');
      const { update } = yUpdateWithText('hello world');
      const received = waitFor<{ documentId: string; update: string }>(
        bob,
        'document-update',
      );
      alice.emit('document-update', { documentId: 'doc-crdt', update });
      const evt = await received;
      expect(evt.update).toBe(update);
      const bobDoc = new Y.Doc();
      Y.applyUpdate(bobDoc, new Uint8Array(Buffer.from(evt.update, 'base64')));
      expect(bobDoc.getText('content').toString()).toBe('hello world');
      expect(manager.getDocument('doc-crdt')?.getText('content').toString()).toBe(
        'hello world',
      );
      await sleep(50);
      expect(mockRedis.set).toHaveBeenCalledWith(
        'doc:state:doc-crdt',
        expect.any(Buffer),
        86400,
      );
      expect(mockRedis.hset).toHaveBeenCalledWith(
        'doc:meta:doc-crdt',
        'lastModifiedBy',
        'alice8',
      );
    });

    it('does not echo an update back to the sender', async () => {
      const alice = await connect('alice9');
      const bob = await connect('bob9');
      await join(alice, 'doc-echo');
      await join(bob, 'doc-echo');
      const echoes = collect(alice, 'document-update');
      const toBob = waitFor(bob, 'document-update');
      alice.emit('document-update', {
        documentId: 'doc-echo',
        update: yUpdateWithText('x').update,
      });
      await toBob;
      await sleep(100);
      expect(echoes).toHaveLength(0);
    });

    it('concurrent edits from two clients converge in both directions', async () => {
      const alice = await connect('alice10');
      const bob = await connect('bob10');
      await join(alice, 'doc-converge');
      await join(bob, 'doc-converge');
      const a = yUpdateWithText('A', 1);
      const b = yUpdateWithText('B', 2);
      const atBob = waitFor<{ update: string }>(bob, 'document-update');
      const atAlice = waitFor<{ update: string }>(alice, 'document-update');
      alice.emit('document-update', { documentId: 'doc-converge', update: a.update });
      bob.emit('document-update', { documentId: 'doc-converge', update: b.update });
      Y.applyUpdate(b.doc, new Uint8Array(Buffer.from((await atBob).update, 'base64')));
      Y.applyUpdate(a.doc, new Uint8Array(Buffer.from((await atAlice).update, 'base64')));
      const server = manager.getDocument('doc-converge')!.getText('content').toString();
      expect(a.doc.getText('content').toString()).toBe(server);
      expect(b.doc.getText('content').toString()).toBe(server);
      expect(server.split('').sort().join('')).toBe('AB');
    });

    it('a reconnecting client receives the full state via sync-document', async () => {
      const alice = await connect('alice11');
      const bob = await connect('bob11');
      await join(alice, 'doc-reconnect');
      await join(bob, 'doc-reconnect');
      const got = waitFor(bob, 'document-update');
      alice.emit('document-update', {
        documentId: 'doc-reconnect',
        update: yUpdateWithText('persist me').update,
      });
      await got;
      bob.disconnect();
      const bob2 = await connect('bob11');
      const sync = waitFor<{ state: string }>(bob2, 'sync-document');
      await join(bob2, 'doc-reconnect');
      const doc = new Y.Doc();
      Y.applyUpdate(doc, new Uint8Array(Buffer.from((await sync).state, 'base64')));
      expect(doc.getText('content').toString()).toBe('persist me');
    });

    it('re-hydrates a document from Redis after it was evicted from memory', async () => {
      const saved = yUpdateWithText('from redis');
      mockRedis.get.mockResolvedValueOnce(Buffer.from(saved.update, 'base64'));
      const alice = await connect('alice12');
      const sync = waitFor<{ state: string }>(alice, 'sync-document');
      await join(alice, 'doc-rehydrate');
      expect(mockRedis.get).toHaveBeenCalledWith('doc:state:doc-rehydrate');
      const doc = new Y.Doc();
      Y.applyUpdate(doc, new Uint8Array(Buffer.from((await sync).state, 'base64')));
      expect(doc.getText('content').toString()).toBe('from redis');
    });

    it('rejects a corrupt base64 Yjs update with document-update-error and no fan-out', async () => {
      const alice = await connect('alice13');
      const bob = await connect('bob13');
      await join(alice, 'doc-corrupt');
      await join(bob, 'doc-corrupt');
      const leaked = collect(bob, 'document-update');
      const error = waitFor<{ error: string }>(alice, 'document-update-error');
      alice.emit('document-update', { documentId: 'doc-corrupt', update: '//8AAQ==' });
      expect((await error).error).toBe('Failed to apply update');
      await sleep(100);
      expect(leaked).toHaveLength(0);
    });

    it('ignores updates for documents that are not loaded', async () => {
      const alice = await connect('alice14');
      alice.emit('document-update', {
        documentId: 'never-joined',
        update: yUpdateWithText('x').update,
      });
      await sleep(100);
      expect(manager.getDocument('never-joined')).toBeUndefined();
      expect(mockRedis.set).not.toHaveBeenCalledWith(
        'doc:state:never-joined',
        expect.anything(),
        expect.anything(),
      );
    });

    it('still fans out when Redis persistence fails (best-effort persistence)', async () => {
      const alice = await connect('alice15');
      const bob = await connect('bob15');
      await join(alice, 'doc-persist-fail');
      await join(bob, 'doc-persist-fail');
      mockRedis.set.mockRejectedValueOnce(new Error('redis down'));
      const received = waitFor(bob, 'document-update');
      alice.emit('document-update', {
        documentId: 'doc-persist-fail',
        update: yUpdateWithText('ok').update,
      });
      await expect(received).resolves.toBeDefined();
    });
  });

  describe('cursor, typing and comments', () => {
    it('broadcasts cursor-update with server-side identity and color', async () => {
      const alice = await connect('alice16', 'Alice');
      const bob = await connect('bob16');
      await join(alice, 'doc-cur');
      await join(bob, 'doc-cur');
      const got = waitFor<Record<string, unknown>>(bob, 'cursor-update');
      alice.emit('cursor-update', {
        documentId: 'doc-cur',
        cursor: { index: 1, length: 0 },
        selection: null,
      });
      expect(await got).toMatchObject({
        userId: 'alice16',
        displayName: 'Alice',
        cursor: { index: 1, length: 0 },
      });
    });

    it('drops cursor and typing events from sockets that never joined', async () => {
      const alice = await connect('alice17');
      const outsider = await connect('outsider17');
      await join(alice, 'doc-drop');
      const seen = [
        ...[collect(alice, 'cursor-update')],
        ...[collect(alice, 'typing-indicator')],
      ];
      outsider.emit('cursor-update', {
        documentId: 'doc-drop',
        cursor: { index: 0, length: 0 },
        selection: null,
      });
      outsider.emit('typing-indicator', { documentId: 'doc-drop', isTyping: true });
      await sleep(150);
      expect(seen.flat()).toHaveLength(0);
    });

    it('broadcasts typing-indicator to the room', async () => {
      const alice = await connect('alice18');
      const bob = await connect('bob18');
      await join(alice, 'doc-typing');
      await join(bob, 'doc-typing');
      const got = waitFor<{ userId: string; isTyping: boolean }>(bob, 'typing-indicator');
      alice.emit('typing-indicator', { documentId: 'doc-typing', isTyping: true });
      expect(await got).toMatchObject({ userId: 'alice18', isTyping: true });
    });

    it('comment-add stamps the author from the token, overriding a spoofed author', async () => {
      const alice = await connect('alice19', 'Alice');
      const bob = await connect('bob19');
      await join(alice, 'doc-comment');
      await join(bob, 'doc-comment');
      const atBob = waitFor<Record<string, unknown>>(bob, 'comment-added');
      const atAlice = waitFor<Record<string, unknown>>(alice, 'comment-added');
      alice.emit('comment-add', {
        documentId: 'doc-comment',
        comment: {
          id: 'c1',
          threadId: 't1',
          content: 'nice',
          rangeStart: 0,
          rangeEnd: 4,
          author: { userId: 'mallory', displayName: 'Mallory' },
        },
      });
      const evt = await atBob;
      expect(evt).toMatchObject({
        id: 'c1',
        documentId: 'doc-comment',
        author: { userId: 'alice19', displayName: 'Alice' },
      });
      expect(typeof evt.createdAt).toBe('string');
      await expect(atAlice).resolves.toMatchObject({ id: 'c1' });
    });

    it('comment-update and comment-delete fan out with the acting user', async () => {
      const alice = await connect('alice20');
      const bob = await connect('bob20');
      await join(alice, 'doc-c2');
      await join(bob, 'doc-c2');
      const upd = waitFor<Record<string, unknown>>(bob, 'comment-updated');
      alice.emit('comment-update', {
        documentId: 'doc-c2',
        commentId: 'c1',
        content: 'edited',
      });
      expect(await upd).toMatchObject({
        commentId: 'c1',
        content: 'edited',
        updatedBy: { userId: 'alice20' },
      });
      const del = waitFor<Record<string, unknown>>(bob, 'comment-deleted');
      alice.emit('comment-delete', { documentId: 'doc-c2', commentId: 'c1' });
      expect(await del).toEqual({ commentId: 'c1', deletedBy: 'alice20' });
    });
  });

  describe('snapshots and history', () => {
    it('request-snapshot stores a snapshot and notifies requester and room', async () => {
      const alice = await connect('alice21');
      const bob = await connect('bob21');
      await join(alice, 'doc-snap');
      await join(bob, 'doc-snap');
      const mine = waitFor<Record<string, unknown>>(alice, 'snapshot-created');
      const theirs = waitFor<Record<string, unknown>>(bob, 'snapshot-created');
      alice.emit('request-snapshot', { documentId: 'doc-snap', label: 'v1' });
      expect(await mine).toMatchObject({
        documentId: 'doc-snap',
        createdBy: 'alice21',
        label: 'v1',
      });
      await expect(theirs).resolves.toMatchObject({ label: 'v1' });
      expect(mockRedis.lpush).toHaveBeenCalledWith(
        'doc:snapshots:doc-snap',
        expect.any(String),
      );
    });

    it('request-snapshot for an unloaded document returns snapshot-error', async () => {
      const alice = await connect('alice22');
      const err = waitFor<{ error: string }>(alice, 'snapshot-error');
      alice.emit('request-snapshot', { documentId: 'not-loaded' });
      expect((await err).error).toBe('Document not found');
    });

    it('request-snapshot surfaces Redis failures as snapshot-error', async () => {
      const alice = await connect('alice23');
      await join(alice, 'doc-snap-fail');
      mockRedis.lpush.mockRejectedValueOnce(new Error('redis down'));
      const err = waitFor<{ error: string }>(alice, 'snapshot-error');
      alice.emit('request-snapshot', { documentId: 'doc-snap-fail' });
      expect((await err).error).toBe('Failed to create snapshot');
    });

    it('request-history defaults to 20 entries and returns parsed snapshots', async () => {
      mockRedis.lrange.mockResolvedValueOnce([
        JSON.stringify({ id: 's1', documentId: 'doc-h', state: '' }),
      ]);
      const alice = await connect('alice24');
      await join(alice, 'doc-h');
      const hist = waitFor<{ snapshots: Array<{ id: string }> }>(
        alice,
        'document-history',
      );
      alice.emit('request-history', { documentId: 'doc-h' });
      expect((await hist).snapshots.map((s) => s.id)).toEqual(['s1']);
      expect(mockRedis.lrange).toHaveBeenCalledWith('doc:snapshots:doc-h', 0, 19);
    });

    it('request-history surfaces Redis failures as history-error', async () => {
      mockRedis.lrange.mockRejectedValueOnce(new Error('redis down'));
      const alice = await connect('alice25');
      await join(alice, 'doc-h-fail');
      const err = waitFor<{ error: string }>(alice, 'history-error');
      alice.emit('request-history', { documentId: 'doc-h-fail' });
      expect((await err).error).toBe('Failed to retrieve history');
    });
  });

  describe('authorization gaps (documented findings)', () => {
    // COLLAB-02: document-update is fanned out to `doc:<id>` without checking that the sender
    // joined that document, so any authenticated socket can inject edits into any open room.
    it.failing(
      'does not fan out document-update from a socket that is not a member [COLLAB-02]',
      async () => {
        const alice = await connect('alice30');
        const mallory = await connect('mallory30');
        await join(alice, 'doc-victim');
        const seen = collect(alice, 'document-update');
        mallory.emit('document-update', {
          documentId: 'doc-victim',
          update: yUpdateWithText('pwned').update,
        });
        await sleep(200);
        expect(seen).toHaveLength(0);
        expect(manager.getDocument('doc-victim')?.getText('content').toString()).toBe('');
      },
    );

    // COLLAB-02: comment events trust the client-supplied documentId and have no membership check.
    it.failing(
      'does not broadcast comment-add/delete from a non-member [COLLAB-02]',
      async () => {
        const alice = await connect('alice31');
        const mallory = await connect('mallory31');
        await join(alice, 'doc-victim2');
        const added = collect(alice, 'comment-added');
        const deleted = collect(alice, 'comment-deleted');
        mallory.emit('comment-add', {
          documentId: 'doc-victim2',
          comment: { id: 'x', content: 'spam' },
        });
        mallory.emit('comment-delete', {
          documentId: 'doc-victim2',
          commentId: 'alices-comment',
        });
        await sleep(200);
        expect(added.length + deleted.length).toBe(0);
      },
    );

    // COLLAB-02: cursor-update/typing-indicator are sent to the client-supplied room rather than
    // the document the socket actually joined.
    it.failing(
      'routes cursor-update only to the room the sender joined [COLLAB-02]',
      async () => {
        const alice = await connect('alice32');
        const mallory = await connect('mallory32');
        await join(alice, 'doc-victim3');
        await join(mallory, 'doc-mallory');
        const seen = collect(alice, 'cursor-update');
        mallory.emit('cursor-update', {
          documentId: 'doc-victim3',
          cursor: { index: 0, length: 0 },
          selection: null,
        });
        await sleep(200);
        expect(seen).toHaveLength(0);
      },
    );

    // COLLAB-03: request-history returns full snapshot state (base64 Yjs) for any document id.
    it.failing(
      'refuses request-history for a document the socket has not joined [COLLAB-03]',
      async () => {
        mockRedis.lrange.mockResolvedValueOnce([
          JSON.stringify({
            id: 's',
            documentId: 'secret-doc',
            state: 'c2VjcmV0',
            createdBy: 'alice',
          }),
        ]);
        const mallory = await connect('mallory33');
        const leaked = collect(mallory, 'document-history');
        mallory.emit('request-history', { documentId: 'secret-doc' });
        await sleep(200);
        expect(leaked).toHaveLength(0);
      },
    );
  });
});

describe('QA: CollaborationManager handlers with malformed payloads', () => {
  function fakeSocket(): Socket {
    const roomEmit = jest.fn();
    return {
      id: 'fake-socket',
      emit: jest.fn(),
      join: jest.fn().mockResolvedValue(undefined),
      leave: jest.fn(),
      to: jest.fn().mockReturnValue({ emit: roomEmit }),
      handshake: { auth: {}, headers: {} },
    } as unknown as Socket;
  }

  function buildManager() {
    const awareness = new AwarenessService(logger);
    const io = {
      to: jest.fn().mockReturnValue({ emit: jest.fn() }),
      on: jest.fn(),
    } as unknown as SocketIOServer;
    return new CollaborationManager({
      io,
      documentStore: new DocumentStore(createMockRedis(), logger),
      awareness,
      presenceHandler: new PresenceHandler(awareness, logger),
      metrics: new MetricsCollector(),
      logger,
      persistIntervalMs: 600000,
      snapshotIntervalMs: 600000,
    }) as unknown as Record<string, (socket: Socket, data: unknown) => unknown>;
  }

  // COLLAB-01: socket handlers destructure/dereference `data` before any try/catch. A single
  // event with no payload throws (sync handlers) or rejects (async handlers) inside a socket.io
  // listener, which is an uncaught exception / unhandled rejection that terminates the Node
  // process — one authenticated client can crash collab-service for every user.
  const syncHandlers = [
    'handleLeaveDocument',
    'handleCursorUpdate',
    'handleTypingIndicator',
    'handleCommentAdd',
    'handleCommentUpdate',
    'handleCommentDelete',
  ];
  const asyncHandlers = [
    'handleJoinDocument',
    'handleDocumentUpdate',
    'handleRequestSnapshot',
    'handleRequestHistory',
  ];

  for (const name of syncHandlers) {
    it.failing(`${name} tolerates a missing payload [COLLAB-01]`, () => {
      const manager = buildManager();
      expect(() => manager[name](fakeSocket(), undefined)).not.toThrow();
    });
  }

  for (const name of asyncHandlers) {
    it.failing(`${name} tolerates a missing payload [COLLAB-01]`, async () => {
      const manager = buildManager();
      await expect(
        Promise.resolve().then(() => manager[name](fakeSocket(), undefined)),
      ).resolves.toBeUndefined();
    });
  }

  it('handleJoinDocument tolerates a payload with a missing documentId', async () => {
    const manager = buildManager();
    await expect(manager.handleJoinDocument(fakeSocket(), {})).resolves.toBeUndefined();
  });

  // COLLAB-05: documentId is never validated (type/length/charset); objects, empty strings and
  // arbitrary strings all create rooms, Y.Docs and Redis keys.
  it.failing('rejects a non-string documentId on join [COLLAB-05]', async () => {
    const socket = fakeSocket();
    const ack = jest.fn();
    const manager = buildManager() as unknown as Record<
      string,
      (s: Socket, d: unknown, a: unknown) => Promise<void>
    >;
    await manager.handleJoinDocument(socket, { documentId: { $ne: null } }, ack);
    expect(ack).toHaveBeenCalledWith(expect.objectContaining({ success: false }));
  });
});

describe('QA: CollaborationManager lifecycle', () => {
  function build(redis = createMockRedis(), persistIntervalMs = 600000) {
    const awareness = new AwarenessService(logger);
    const io = {
      on: jest.fn(),
      to: jest.fn().mockReturnValue({ emit: jest.fn() }),
    } as unknown as SocketIOServer;
    const manager = new CollaborationManager({
      io,
      documentStore: new DocumentStore(redis, logger),
      awareness,
      presenceHandler: new PresenceHandler(awareness, logger),
      metrics: new MetricsCollector(),
      logger,
      persistIntervalMs,
      snapshotIntervalMs: 600000,
    });
    const internals = manager as unknown as {
      getOrCreateDoc(id: string): Promise<Y.Doc>;
    };
    return { manager, internals, redis, awareness };
  }

  it('concurrent first joins share a single Y.Doc and a single Redis load', async () => {
    const { manager, internals, redis } = build();
    const [a, b] = await Promise.all([
      internals.getOrCreateDoc('doc-race'),
      internals.getOrCreateDoc('doc-race'),
    ]);
    expect(a).toBe(b);
    expect(redis.get).toHaveBeenCalledTimes(1);
    expect(manager.getDocumentCount()).toBe(1);
  });

  it('persistAndCleanupDocument keeps the doc in memory if Redis save fails', async () => {
    const redis = createMockRedis();
    redis.set.mockRejectedValueOnce(new Error('down'));
    const { manager, internals } = build(redis);
    await internals.getOrCreateDoc('doc-keep');
    await manager.persistAndCleanupDocument('doc-keep');
    expect(manager.getDocument('doc-keep')).toBeDefined();
  });

  it('persistAndCleanupDocument keeps the doc if a user re-joined during persistence', async () => {
    const { manager, internals, awareness } = build();
    await internals.getOrCreateDoc('doc-rejoin');
    const pending = manager.persistAndCleanupDocument('doc-rejoin');
    awareness.addUser('doc-rejoin', 's1', 'u1', 'U', '');
    await pending;
    expect(manager.getDocument('doc-rejoin')).toBeDefined();
  });

  it('persistAndCleanupDocument is a no-op for unknown documents', async () => {
    const { manager, redis } = build();
    await manager.persistAndCleanupDocument('ghost');
    expect(redis.set).not.toHaveBeenCalled();
  });

  it('stop() flushes every in-memory document to Redis', async () => {
    const { manager, internals, redis } = build();
    await internals.getOrCreateDoc('d1');
    await internals.getOrCreateDoc('d2');
    await manager.stop();
    const keys = redis.set.mock.calls.map((c) => c[0]);
    expect(keys).toEqual(expect.arrayContaining(['doc:state:d1', 'doc:state:d2']));
  });

  it('the periodic persistence loop saves loaded documents', async () => {
    const { manager, internals, redis } = build(createMockRedis(), 30);
    manager.start();
    await internals.getOrCreateDoc('d-loop');
    await sleep(120);
    await manager.stop();
    expect(redis.set).toHaveBeenCalledWith('doc:state:d-loop', expect.any(Buffer), 86400);
  });
});
