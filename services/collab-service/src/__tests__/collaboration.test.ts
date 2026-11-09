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
import type { DocumentAccessChecker } from '../services/document-access';

const JWT_SECRET = 'test-secret-key-for-unit-tests';
let PORT: number;

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

// Users may only open documents they own: `<owner>__<name>` (or any doc without an owner prefix).
const accessChecker: jest.Mocked<DocumentAccessChecker> = {
  canAccess: jest.fn<Promise<boolean>, [string, string, string]>(
    async (documentId, userId) => {
      const [owner] = documentId.split('__');
      return !documentId.includes('__') || owner === userId;
    },
  ),
};

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
      documentStore,
      awareness,
      presenceHandler,
      accessChecker,
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
  });

  function connectClient(userId: string, displayName: string): Promise<ClientSocket> {
    return new Promise((resolve, reject) => {
      const token = createToken({
        sub: userId,
        name: displayName,
        email: `${userId}@test.com`,
        roles: ['user'],
      });

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
          { documentId: 'doc-join-test' },
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

      client.emit('join-document', { documentId: 'doc-sync-test' }, () => {});

      const syncData = await syncPromise;
      expect(syncData.documentId).toBe('doc-sync-test');
      expect(syncData.state).toBeDefined();

      client.disconnect();
    });

    it('should notify other users when someone joins', async () => {
      const client1 = await connectClient('user-notify-1', 'Alice');
      const client2 = await connectClient('user-notify-2', 'Bob');

      // Client 1 joins first
      await new Promise<void>((resolve) => {
        client1.emit('join-document', { documentId: 'doc-notify-test' }, () => resolve());
      });

      // Listen for join notification on client 1
      const joinPromise = new Promise<{ userId: string; displayName: string }>(
        (resolve) => {
          client1.on('user-joined', (data) => resolve(data));
        },
      );

      // Client 2 joins
      client2.emit('join-document', { documentId: 'doc-notify-test' }, () => {});

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
          client1.emit('join-document', { documentId: 'doc-update-test' }, () =>
            resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit('join-document', { documentId: 'doc-update-test' }, () =>
            resolve(),
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
        documentId: 'doc-update-test',
        update: encodedUpdate,
      });

      const updateData = await updatePromise;
      expect(updateData.documentId).toBe('doc-update-test');
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
          client1.emit('join-document', { documentId: 'doc-cursor-test' }, () =>
            resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit('join-document', { documentId: 'doc-cursor-test' }, () =>
            resolve(),
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
        documentId: 'doc-cursor-test',
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
          client1.emit('join-document', { documentId: 'doc-disc-test' }, () => resolve());
        }),
        new Promise<void>((resolve) => {
          client2.emit('join-document', { documentId: 'doc-disc-test' }, () => resolve());
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

  describe('Document Access Control', () => {
    function join(
      client: ClientSocket,
      documentId: string,
    ): Promise<{ success: boolean; error?: string }> {
      return new Promise((resolve) => {
        client.emit('join-document', { documentId }, resolve);
      });
    }

    it('should pass the socket token to the access checker', async () => {
      const client = await connectClient('owner-a', 'Alice');
      const response = await join(client, 'owner-a__token-doc');

      expect(response.success).toBe(true);
      expect(accessChecker.canAccess).toHaveBeenCalledWith(
        'owner-a__token-doc',
        'owner-a',
        expect.any(String),
      );
      expect(accessChecker.canAccess.mock.calls[0][2]).not.toBe('');
      client.disconnect();
    });

    it("should reject joining another user's document without syncing state", async () => {
      const owner = await connectClient('owner-a', 'Alice');
      const intruder = await connectClient('mallory', 'Mallory');
      expect((await join(owner, 'owner-a__secret')).success).toBe(true);

      const synced = jest.fn();
      intruder.on('sync-document', synced);
      const joinedOnOwner = jest.fn();
      owner.on('user-joined', joinedOnOwner);

      const response = await join(intruder, 'owner-a__secret');
      await new Promise((r) => setTimeout(r, 100));

      expect(response).toEqual({ success: false, error: 'Access denied' });
      expect(synced).not.toHaveBeenCalled();
      expect(joinedOnOwner).not.toHaveBeenCalled();
      expect(awareness.getUserDocument(intruder.id!)).toBeNull();

      owner.disconnect();
      intruder.disconnect();
    });

    it('should not register a socket that disconnects during the access check', async () => {
      let release!: (allowed: boolean) => void;
      accessChecker.canAccess.mockImplementationOnce(
        () => new Promise<boolean>((resolve) => (release = resolve)),
      );
      const client = await connectClient('owner-a', 'Alice');
      const socketId = client.id!;
      client.emit('join-document', { documentId: 'owner-a__slow' });
      await new Promise((r) => setTimeout(r, 50));

      client.disconnect();
      await new Promise((r) => setTimeout(r, 50));
      release(true);
      await new Promise((r) => setTimeout(r, 50));

      expect(awareness.getUserDocument(socketId)).toBeNull();
      expect(awareness.getDocumentUserCount('owner-a__slow')).toBe(0);
    });

    it('should reject malformed document ids', async () => {
      const client = await connectClient('owner-a', 'Alice');
      const response = await join(client, '../../etc');

      expect(response).toEqual({ success: false, error: 'Invalid document id' });
      expect(accessChecker.canAccess).not.toHaveBeenCalled();
      client.disconnect();
    });

    it('should drop document updates from sockets that have not joined the document', async () => {
      const owner = await connectClient('owner-a', 'Alice');
      const intruder = await connectClient('mallory', 'Mallory');
      expect((await join(owner, 'owner-a__wipe')).success).toBe(true);
      // Intruder is joined to a different document of their own
      expect((await join(intruder, 'mallory__mine')).success).toBe(true);

      const receivedByOwner = jest.fn();
      owner.on('document-update', receivedByOwner);
      const errorPromise = new Promise<{ documentId: string; error: string }>((resolve) =>
        intruder.on('document-update-error', resolve),
      );

      const tempDoc = new Y.Doc();
      tempDoc.getText('content').insert(0, 'pwned');
      intruder.emit('document-update', {
        documentId: 'owner-a__wipe',
        update: Buffer.from(Y.encodeStateAsUpdate(tempDoc)).toString('base64'),
      });

      const error = await errorPromise;
      await new Promise((r) => setTimeout(r, 100));

      expect(error.error).toBe('Not joined to document');
      expect(receivedByOwner).not.toHaveBeenCalled();
      expect(manager.getDocument('owner-a__wipe')!.getText('content').toString()).toBe(
        '',
      );
      expect(mockRedis.set).not.toHaveBeenCalledWith(
        expect.stringContaining('owner-a__wipe'),
        expect.anything(),
        expect.anything(),
      );

      owner.disconnect();
      intruder.disconnect();
    });

    it('should reject snapshot and history requests for documents the socket has not joined', async () => {
      const owner = await connectClient('owner-a', 'Alice');
      const intruder = await connectClient('mallory', 'Mallory');
      expect((await join(owner, 'owner-a__history')).success).toBe(true);

      const historyError = new Promise<{ error: string }>((resolve) =>
        intruder.on('history-error', resolve),
      );
      const snapshotError = new Promise<{ error: string }>((resolve) =>
        intruder.on('snapshot-error', resolve),
      );
      const history = jest.fn();
      intruder.on('document-history', history);

      intruder.emit('request-history', { documentId: 'owner-a__history' });
      intruder.emit('request-snapshot', { documentId: 'owner-a__history' });

      expect((await historyError).error).toBe('Not joined to document');
      expect((await snapshotError).error).toBe('Not joined to document');
      expect(history).not.toHaveBeenCalled();
      expect(mockRedis.lrange).not.toHaveBeenCalled();

      owner.disconnect();
      intruder.disconnect();
    });

    it('should not relay comments or cursors into rooms the socket has not joined', async () => {
      const owner = await connectClient('owner-a', 'Alice');
      const intruder = await connectClient('mallory', 'Mallory');
      expect((await join(owner, 'owner-a__comments')).success).toBe(true);
      expect((await join(intruder, 'mallory__other')).success).toBe(true);

      const relayed = jest.fn();
      owner.on('comment-added', relayed);
      owner.on('comment-deleted', relayed);
      owner.on('cursor-update', relayed);

      intruder.emit('comment-add', {
        documentId: 'owner-a__comments',
        comment: {
          id: 'c1',
          threadId: 't1',
          content: 'spam',
          rangeStart: 0,
          rangeEnd: 1,
        },
      });
      intruder.emit('comment-delete', {
        documentId: 'owner-a__comments',
        commentId: 'c1',
      });
      intruder.emit('cursor-update', {
        documentId: 'owner-a__comments',
        cursor: { index: 0, length: 0 },
        selection: null,
      });
      await new Promise((r) => setTimeout(r, 200));

      expect(relayed).not.toHaveBeenCalled();
      owner.disconnect();
      intruder.disconnect();
    });
  });

  describe('Leave Document', () => {
    it('should allow a user to leave a document', async () => {
      const client1 = await connectClient('user-leave-1', 'Alice');
      const client2 = await connectClient('user-leave-2', 'Bob');

      await Promise.all([
        new Promise<void>((resolve) => {
          client1.emit('join-document', { documentId: 'doc-leave-test' }, () =>
            resolve(),
          );
        }),
        new Promise<void>((resolve) => {
          client2.emit('join-document', { documentId: 'doc-leave-test' }, () =>
            resolve(),
          );
        }),
      ]);

      await new Promise((r) => setTimeout(r, 100));

      const leftPromise = new Promise<{ socketId: string }>((resolve) => {
        client1.on('user-left', (data) => resolve(data));
      });

      client2.emit('leave-document', { documentId: 'doc-leave-test' });

      const leftData = await leftPromise;
      expect(leftData.socketId).toBeDefined();

      client1.disconnect();
      client2.disconnect();
    });
  });
});
