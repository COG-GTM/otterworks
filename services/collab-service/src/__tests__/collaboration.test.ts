import { Server as SocketIOServer } from 'socket.io';
import { createServer } from 'http';
import { io as clientIO, Socket as ClientSocket } from 'socket.io-client';
import jwt from 'jsonwebtoken';
import * as Y from 'yjs';
import { CollaborationManager } from '../handlers/collaboration';
import { DocumentStore } from '../services/document-store';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import { createAuthMiddleware } from '../middleware/auth';
import { RedisAdapter } from '../services/redis-adapter';

const JWT_SECRET = 'test-secret-key-for-unit-tests';
let PORT: number;

const INTRUDER_PREFIX = 'intruder-';
const accessChecks: Array<{ token: string; userId: string; documentId: string }> = [];
const documentAccess = {
  canAccess: async (token: string, userId: string, documentId: string) => {
    accessChecks.push({ token, userId, documentId });
    return !userId.startsWith(INTRUDER_PREFIX);
  },
};

function createToken(payload: Record<string, unknown>): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

const mockRedis = {
  get: jest.fn().mockResolvedValue(null),
  set: jest.fn().mockResolvedValue(undefined),
  del: jest.fn().mockResolvedValue(undefined),
  hset: jest.fn().mockResolvedValue(undefined),
  hget: jest.fn().mockResolvedValue(null),
  hgetall: jest.fn().mockResolvedValue({}),
  hdel: jest.fn().mockResolvedValue(undefined),
  hincrby: jest.fn().mockResolvedValue(1),
  lpush: jest.fn().mockResolvedValue(undefined),
  lrange: jest.fn().mockResolvedValue([]),
  ltrim: jest.fn().mockResolvedValue(undefined),
  llen: jest.fn().mockResolvedValue(0),
  expire: jest.fn().mockResolvedValue(undefined),
  publish: jest.fn().mockResolvedValue(undefined),
  subscribe: jest.fn().mockResolvedValue(undefined),
  connect: jest.fn().mockResolvedValue(undefined),
  disconnect: jest.fn(),
  ping: jest.fn().mockResolvedValue(true),
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

describe('CollaborationManager', () => {
  let io: SocketIOServer;
  let httpServer: ReturnType<typeof createServer>;
  let manager: CollaborationManager;
  let metrics: MetricsCollector;
  let awareness: AwarenessService;
  let presenceHandler: PresenceHandler;
  let documentStore: DocumentStore;

  beforeAll((done) => {
    httpServer = createServer();
    io = new SocketIOServer(httpServer, {
      cors: { origin: '*' },
    });

    io.use(createAuthMiddleware(JWT_SECRET, mockLogger));

    metrics = new MetricsCollector();
    awareness = new AwarenessService(mockLogger);
    presenceHandler = new PresenceHandler(awareness, mockLogger);
    documentStore = new DocumentStore(mockRedis, mockLogger);

    manager = new CollaborationManager({
      io,
      documentAccess,
      documentStore,
      awareness,
      presenceHandler,
      metrics,
      logger: mockLogger,
      persistIntervalMs: 600000, // long interval so it doesn't fire during tests
      snapshotIntervalMs: 600000,
    });
    manager.start();

    httpServer.listen(0, () => {
      const addr = httpServer.address();
      PORT = typeof addr === 'object' && addr ? addr.port : 0;
      done();
    });
  }, 15000);

  afterAll((done) => {
    manager.stop();
    io.close();
    httpServer.close(done);
  });

  afterEach(() => {
    jest.clearAllMocks();
    accessChecks.length = 0;
  });

  function tokenFor(userId: string, displayName: string): string {
    return createToken({
      sub: userId,
      name: displayName,
      email: `${userId}@test.com`,
      roles: ['user'],
    });
  }

  function connectClient(userId: string, displayName: string): Promise<ClientSocket> {
    return new Promise((resolve, reject) => {
      const token = tokenFor(userId, displayName);

      const client = clientIO(`http://localhost:${PORT}`, {
        auth: { token },
        transports: ['websocket'],
      });

      client.on('connect', () => resolve(client));
      client.on('connect_error', (err) => reject(err));

      setTimeout(() => reject(new Error('Connection timeout')), 5000);
    });
  }

  describe('Authentication', () => {
    it('should reject connections without a token', (done) => {
      const client = clientIO(`http://localhost:${PORT}`, {
        auth: {},
        transports: ['websocket'],
      });

      client.on('connect_error', (err) => {
        expect(err.message).toContain('Authentication required');
        client.disconnect();
        done();
      });
    });

    it('should reject connections with an invalid token', (done) => {
      const client = clientIO(`http://localhost:${PORT}`, {
        auth: { token: 'invalid-token-value' },
        transports: ['websocket'],
      });

      client.on('connect_error', (err) => {
        expect(err.message).toContain('Invalid or expired token');
        client.disconnect();
        done();
      });
    });

    it('should accept connections with a valid token', async () => {
      const client = await connectClient('user-auth-test', 'Test User');
      expect(client.connected).toBe(true);
      client.disconnect();
    });
  });

  describe('Document Joining', () => {
    it('should allow a user to join a document room', async () => {
      const client = await connectClient('user-join-1', 'Alice');

      const response = await new Promise<{ success: boolean }>((resolve) => {
        client.emit(
          'join-document',
          { documentId: '00000000-0000-4000-8000-000000000003' },
          (res: { success: boolean }) => resolve(res),
        );
      });

      expect(response.success).toBe(true);
      client.disconnect();
    });

    it('should sync document state to joining client', async () => {
      const client = await connectClient('user-sync-1', 'Bob');

      const syncPromise = new Promise<{ documentId: string; state: string }>(
        (resolve) => {
          client.on('sync-document', (data) => resolve(data));
        },
      );

      client.emit(
        'join-document',
        { documentId: '00000000-0000-4000-8000-000000000006' },
        () => {},
      );

      const syncData = await syncPromise;
      expect(syncData.documentId).toBe('00000000-0000-4000-8000-000000000006');
      expect(syncData.state).toBeDefined();

      client.disconnect();
    });

    it('should notify other users when someone joins', async () => {
      const client1 = await connectClient('user-notify-1', 'Alice');
      const client2 = await connectClient('user-notify-2', 'Bob');

      // Client 1 joins first
      await new Promise<void>((resolve) => {
        client1.emit(
          'join-document',
          { documentId: '00000000-0000-4000-8000-000000000005' },
          () => resolve(),
        );
      });

      // Listen for join notification on client 1
      const joinPromise = new Promise<{ userId: string; displayName: string }>(
        (resolve) => {
          client1.on('user-joined', (data) => resolve(data));
        },
      );

      // Client 2 joins
      client2.emit(
        'join-document',
        { documentId: '00000000-0000-4000-8000-000000000005' },
        () => {},
      );

      const joinData = await joinPromise;
      expect(joinData.userId).toBe('user-notify-2');
      expect(joinData.displayName).toBe('Bob');

      client1.disconnect();
      client2.disconnect();
    });
  });

  describe('Document Updates', () => {
    it('should broadcast document updates to other clients', async () => {
      const client1 = await connectClient('user-update-1', 'Alice');
      const client2 = await connectClient('user-update-2', 'Bob');

      // Both join the same document
      await Promise.all([
        new Promise<void>((resolve) => {
          client1.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000007' },
            () => resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000007' },
            () => resolve(),
          );
        }),
      ]);

      // Wait for sync to complete
      await new Promise((r) => setTimeout(r, 100));

      // Listen for update on client 2
      const updatePromise = new Promise<{
        documentId: string;
        update: string;
      }>((resolve) => {
        client2.on('document-update', (data) => resolve(data));
      });

      // Create a valid Yjs update
      const tempDoc = new Y.Doc();
      const text = tempDoc.getText('content');
      text.insert(0, 'Hello');
      const validUpdate = Y.encodeStateAsUpdate(tempDoc);
      const encodedUpdate = Buffer.from(validUpdate).toString('base64');

      client1.emit('document-update', {
        documentId: '00000000-0000-4000-8000-000000000007',
        update: encodedUpdate,
      });

      const updateData = await updatePromise;
      expect(updateData.documentId).toBe('00000000-0000-4000-8000-000000000007');
      expect(updateData.update).toBe(encodedUpdate);

      client1.disconnect();
      client2.disconnect();
    });
  });

  describe('Cursor Updates', () => {
    it('should broadcast cursor updates to other clients', async () => {
      const client1 = await connectClient('user-cursor-1', 'Alice');
      const client2 = await connectClient('user-cursor-2', 'Bob');

      await Promise.all([
        new Promise<void>((resolve) => {
          client1.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000001' },
            () => resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000001' },
            () => resolve(),
          );
        }),
      ]);

      await new Promise((r) => setTimeout(r, 100));

      const cursorPromise = new Promise<{
        userId: string;
        cursor: { index: number; length: number };
      }>((resolve) => {
        client2.on('cursor-update', (data) => resolve(data));
      });

      client1.emit('cursor-update', {
        documentId: '00000000-0000-4000-8000-000000000001',
        cursor: { index: 42, length: 0 },
        selection: null,
      });

      const cursorData = await cursorPromise;
      expect(cursorData.userId).toBe('user-cursor-1');
      expect(cursorData.cursor).toEqual({ index: 42, length: 0 });

      client1.disconnect();
      client2.disconnect();
    });
  });

  describe('Disconnect Handling', () => {
    it('should notify others when a user disconnects', async () => {
      const client1 = await connectClient('user-disc-1', 'Alice');
      const client2 = await connectClient('user-disc-2', 'Bob');

      await Promise.all([
        new Promise<void>((resolve) => {
          client1.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000002' },
            () => resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000002' },
            () => resolve(),
          );
        }),
      ]);

      await new Promise((r) => setTimeout(r, 100));

      const leftPromise = new Promise<{ userId: string }>((resolve) => {
        client1.on('user-left', (data) => resolve(data));
      });

      client2.disconnect();

      const leftData = await leftPromise;
      expect(leftData.userId).toBe('user-disc-2');

      client1.disconnect();
    });
  });

  describe('Leave Document', () => {
    it('should allow a user to leave a document', async () => {
      const client1 = await connectClient('user-leave-1', 'Alice');
      const client2 = await connectClient('user-leave-2', 'Bob');

      await Promise.all([
        new Promise<void>((resolve) => {
          client1.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000004' },
            () => resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit(
            'join-document',
            { documentId: '00000000-0000-4000-8000-000000000004' },
            () => resolve(),
          );
        }),
      ]);

      await new Promise((r) => setTimeout(r, 100));

      const leftPromise = new Promise<{ socketId: string }>((resolve) => {
        client1.on('user-left', (data) => resolve(data));
      });

      client2.emit('leave-document', {
        documentId: '00000000-0000-4000-8000-000000000004',
      });

      const leftData = await leftPromise;
      expect(leftData.socketId).toBeDefined();

      client1.disconnect();
      client2.disconnect();
    });
  });

  describe('Document Authorization', () => {
    let docCounter = 0;
    let OWNED_DOC: string;

    beforeEach(() => {
      docCounter += 1;
      OWNED_DOC = `00000000-0000-4000-8000-0000000a${String(docCounter).padStart(4, '0')}`;
    });

    function join(client: ClientSocket, documentId: unknown) {
      return new Promise<{ success: boolean; error?: string }>((resolve) => {
        client.emit('join-document', { documentId }, resolve);
      });
    }

    function collect(client: ClientSocket, event: string): unknown[] {
      const received: unknown[] = [];
      client.on(event, (data) => received.push(data));
      return received;
    }

    const settle = () => new Promise((r) => setTimeout(r, 150));

    it('checks access with the caller token before joining', async () => {
      const client = await connectClient('user-acl-owner', 'Owner');
      const response = await join(client, OWNED_DOC);

      expect(response.success).toBe(true);
      expect(accessChecks).toEqual([
        {
          token: tokenFor('user-acl-owner', 'Owner'),
          userId: 'user-acl-owner',
          documentId: OWNED_DOC,
        },
      ]);
      client.disconnect();
    });

    it('rejects a join the document-service denies without syncing state', async () => {
      const owner = await connectClient('user-acl-owner-2', 'Owner');
      await join(owner, OWNED_DOC);
      const ownerJoins = collect(owner, 'user-joined');

      const intruder = await connectClient(`${INTRUDER_PREFIX}join`, 'Mallory');
      const synced = collect(intruder, 'sync-document');
      const response = await join(intruder, OWNED_DOC);
      await settle();

      expect(response).toEqual({ success: false, error: 'Access denied' });
      expect(synced).toHaveLength(0);
      expect(ownerJoins).toHaveLength(0);
      expect(presenceHandler.getDocumentPresence(OWNED_DOC).count).toBe(1);

      owner.disconnect();
      intruder.disconnect();
    });

    it('rejects joins for ids that are not document UUIDs', async () => {
      const client = await connectClient('user-acl-invalid', 'Alice');

      expect(await join(client, '../admin')).toEqual({
        success: false,
        error: 'Invalid document id',
      });
      expect(await join(client, undefined)).toEqual({
        success: false,
        error: 'Invalid document id',
      });
      expect(accessChecks).toHaveLength(0);
      client.disconnect();
    });

    it('ignores document updates from sockets that did not join the document', async () => {
      const owner = await connectClient('user-acl-owner-3', 'Owner');
      await join(owner, OWNED_DOC);
      const ownerUpdates = collect(owner, 'document-update');
      const before = Buffer.from(
        Y.encodeStateAsUpdate(manager.getDocument(OWNED_DOC) as Y.Doc),
      );

      const intruder = await connectClient(`${INTRUDER_PREFIX}update`, 'Mallory');
      const errors = collect(intruder, 'document-update-error');
      await join(intruder, OWNED_DOC);

      const tempDoc = new Y.Doc();
      tempDoc.getText('content').insert(0, 'tampered');
      intruder.emit('document-update', {
        documentId: OWNED_DOC,
        update: Buffer.from(Y.encodeStateAsUpdate(tempDoc)).toString('base64'),
      });
      await settle();

      expect(ownerUpdates).toHaveLength(0);
      expect(errors).toEqual([
        { documentId: OWNED_DOC, error: 'Not joined to document' },
      ]);
      expect(
        Buffer.from(Y.encodeStateAsUpdate(manager.getDocument(OWNED_DOC) as Y.Doc)),
      ).toEqual(before);
      expect(mockRedis.set).not.toHaveBeenCalled();

      owner.disconnect();
      intruder.disconnect();
    });

    it('does not return history or create snapshots for unjoined documents', async () => {
      const owner = await connectClient('user-acl-owner-4', 'Owner');
      await join(owner, OWNED_DOC);
      const ownerSnapshots = collect(owner, 'snapshot-created');

      const intruder = await connectClient(`${INTRUDER_PREFIX}history`, 'Mallory');
      const history = collect(intruder, 'document-history');
      const historyErrors = collect(intruder, 'history-error');
      const snapshotErrors = collect(intruder, 'snapshot-error');

      intruder.emit('request-history', { documentId: OWNED_DOC, limit: 50 });
      intruder.emit('request-snapshot', { documentId: OWNED_DOC, label: 'x' });
      await settle();

      expect(history).toHaveLength(0);
      expect(historyErrors).toEqual([
        { documentId: OWNED_DOC, error: 'Not joined to document' },
      ]);
      expect(snapshotErrors).toEqual([
        { documentId: OWNED_DOC, error: 'Not joined to document' },
      ]);
      expect(ownerSnapshots).toHaveLength(0);
      expect(mockRedis.lrange).not.toHaveBeenCalled();
      expect(mockRedis.lpush).not.toHaveBeenCalled();

      owner.disconnect();
      intruder.disconnect();
    });

    it('caps the history limit for joined members', async () => {
      const owner = await connectClient('user-acl-owner-5', 'Owner');
      await join(owner, OWNED_DOC);
      const history = collect(owner, 'document-history');

      owner.emit('request-history', { documentId: OWNED_DOC, limit: 100000 });
      await settle();

      expect(history).toHaveLength(1);
      expect(mockRedis.lrange).toHaveBeenCalledWith(expect.any(String), 0, 49);
      owner.disconnect();
    });

    it('does not relay comments, cursors or typing into rooms the sender did not join', async () => {
      const owner = await connectClient('user-acl-owner-6', 'Owner');
      await join(owner, OWNED_DOC);
      const ownerEvents = [
        collect(owner, 'comment-added'),
        collect(owner, 'comment-updated'),
        collect(owner, 'comment-deleted'),
        collect(owner, 'cursor-update'),
        collect(owner, 'typing-indicator'),
      ];

      const intruder = await connectClient(`${INTRUDER_PREFIX}comment`, 'Mallory');
      const commentErrors = collect(intruder, 'comment-error');
      intruder.emit('comment-add', {
        documentId: OWNED_DOC,
        comment: {
          id: 'c1',
          threadId: 't1',
          content: 'spoof',
          rangeStart: 0,
          rangeEnd: 1,
        },
      });
      intruder.emit('comment-update', {
        documentId: OWNED_DOC,
        commentId: 'c1',
        content: 'spoof',
      });
      intruder.emit('comment-delete', { documentId: OWNED_DOC, commentId: 'c1' });
      intruder.emit('cursor-update', {
        documentId: OWNED_DOC,
        cursor: { index: 1, length: 0 },
        selection: null,
      });
      intruder.emit('typing-indicator', { documentId: OWNED_DOC, isTyping: true });
      await settle();

      for (const events of ownerEvents) expect(events).toHaveLength(0);
      expect(commentErrors).toHaveLength(3);

      owner.disconnect();
      intruder.disconnect();
    });

    it('stamps comments with the joined document id, not the client payload', async () => {
      const owner = await connectClient('user-acl-owner-7', 'Owner');
      await join(owner, OWNED_DOC);
      const added = collect(owner, 'comment-added');

      owner.emit('comment-add', {
        documentId: OWNED_DOC,
        comment: {
          id: 'c2',
          documentId: 'someone-elses-doc',
          threadId: 't2',
          content: 'hi',
          rangeStart: 0,
          rangeEnd: 2,
        },
      });
      await settle();

      expect(added).toHaveLength(1);
      expect((added[0] as { documentId: string }).documentId).toBe(OWNED_DOC);
      owner.disconnect();
    });

    it('leaving a document the socket never joined does not touch that room', async () => {
      const owner = await connectClient('user-acl-owner-8', 'Owner');
      await join(owner, OWNED_DOC);
      const ownerLeft = collect(owner, 'user-left');

      const intruder = await connectClient(`${INTRUDER_PREFIX}leave`, 'Mallory');
      intruder.emit('leave-document', { documentId: OWNED_DOC });
      await settle();

      expect(ownerLeft).toHaveLength(0);
      expect(manager.getDocument(OWNED_DOC)).toBeDefined();

      owner.disconnect();
      intruder.disconnect();
    });

    it('omits emails from presence', async () => {
      const owner = await connectClient('user-acl-owner-9', 'Owner');
      const presenceUpdates = collect(owner, 'presence-update');
      await join(owner, OWNED_DOC);
      await settle();

      const presence = presenceHandler.getDocumentPresence(OWNED_DOC);
      expect(presence.users.length).toBeGreaterThan(0);
      for (const user of presence.users) expect(user).not.toHaveProperty('email');
      expect(JSON.stringify(presenceUpdates)).not.toContain('@test.com');
      owner.disconnect();
    });
  });
});
