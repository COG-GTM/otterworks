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
import type {
  DocumentAccess,
  DocumentAccessRequest,
  DocumentPermissionChecker,
} from '../services/document-permissions';

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

// Users named `mallory-*` have no access, `reader-*` hold a read-only share link,
// everyone else owns the documents they open.
const permissions: DocumentPermissionChecker & { calls: DocumentAccessRequest[] } = {
  calls: [],
  async checkAccess(request: DocumentAccessRequest): Promise<DocumentAccess> {
    this.calls.push(request);
    if (request.userId.startsWith('mallory')) return 'none';
    if (request.userId.startsWith('reader')) return 'read';
    if (request.userId.startsWith('slow')) await new Promise((r) => setTimeout(r, 200));
    return 'write';
  },
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
      permissions,
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
  describe('Document Authorization', () => {
    function join(
      client: ClientSocket,
      documentId: string,
      extra: Record<string, unknown> = {},
    ): Promise<{ success: boolean; error?: string; access?: string }> {
      return new Promise((resolve) => {
        client.emit('join-document', { documentId, ...extra }, resolve);
      });
    }

    function yjsUpdate(text: string): string {
      const tempDoc = new Y.Doc();
      tempDoc.getText('content').insert(0, text);
      return Buffer.from(Y.encodeStateAsUpdate(tempDoc)).toString('base64');
    }

    it('checks access with the caller identity, JWT and share token', async () => {
      const client = await connectClient('user-perm-1', 'Alice');
      permissions.calls.length = 0;

      await join(client, 'doc-perm-args', { shareToken: 'share-123' });

      expect(permissions.calls).toHaveLength(1);
      expect(permissions.calls[0]).toMatchObject({
        documentId: 'doc-perm-args',
        userId: 'user-perm-1',
        shareToken: 'share-123',
      });
      expect(typeof permissions.calls[0].token).toBe('string');
      expect(permissions.calls[0].token.length).toBeGreaterThan(0);
      client.disconnect();
    });

    it('stores no grant when the socket disconnects during the access check', async () => {
      const client = await connectClient('slow-user', 'Slow');
      const socketId = client.id as string;
      client.emit('join-document', { documentId: 'doc-authz-aborted' }, () => {});
      await new Promise((r) => setTimeout(r, 50));
      client.disconnect();
      await new Promise((r) => setTimeout(r, 300));

      const grants = (manager as unknown as { socketAccess: Map<string, unknown> })
        .socketAccess;
      expect(grants.has(socketId)).toBe(false);
      expect(awareness.getUserDocument(socketId)).toBeNull();
    });

    it('rejects join-document without access and sends no document state', async () => {
      const owner = await connectClient('user-authz-owner', 'Alice');
      const attacker = await connectClient('mallory-join', 'Mallory');
      await join(owner, 'doc-authz-join');

      const received: string[] = [];
      attacker.on('sync-document', () => received.push('sync-document'));
      attacker.on('presence-update', () => received.push('presence-update'));
      let ownerSawJoin = false;
      owner.on('user-joined', () => {
        ownerSawJoin = true;
      });

      const res = await join(attacker, 'doc-authz-join');
      await new Promise((r) => setTimeout(r, 100));

      expect(res).toEqual({ success: false, error: 'Access denied' });
      expect(received).toEqual([]);
      expect(ownerSawJoin).toBe(false);
      owner.disconnect();
      attacker.disconnect();
    });

    it('rejects request-history for a document the socket has not joined', async () => {
      const attacker = await connectClient('mallory-history', 'Mallory');

      const result = await new Promise<{ event: string; data: { error?: string } }>(
        (resolve) => {
          attacker.on('document-history', (data) =>
            resolve({ event: 'document-history', data }),
          );
          attacker.on('history-error', (data) =>
            resolve({ event: 'history-error', data }),
          );
          attacker.emit('request-history', {
            documentId: 'doc-authz-history',
            limit: 50,
          });
        },
      );

      expect(result).toEqual({
        event: 'history-error',
        data: expect.objectContaining({ error: 'Access denied' }),
      });
      expect(mockRedis.lrange).not.toHaveBeenCalled();
      attacker.disconnect();
    });

    it('rejects history after a denied join attempt', async () => {
      const attacker = await connectClient('mallory-history-2', 'Mallory');
      await join(attacker, 'doc-authz-history-2');

      const event = await new Promise<string>((resolve) => {
        attacker.on('document-history', () => resolve('document-history'));
        attacker.on('history-error', () => resolve('history-error'));
        attacker.emit('request-history', { documentId: 'doc-authz-history-2' });
      });

      expect(event).toBe('history-error');
      expect(mockRedis.lrange).not.toHaveBeenCalled();
      attacker.disconnect();
    });

    it('rejects document-update from a socket outside the room', async () => {
      const owner = await connectClient('user-authz-upd-owner', 'Alice');
      const attacker = await connectClient('mallory-update', 'Mallory');
      await join(owner, 'doc-authz-update');
      await join(attacker, 'doc-authz-update');

      let ownerReceived = false;
      owner.on('document-update', () => {
        ownerReceived = true;
      });
      const error = new Promise<{ error: string }>((resolve) => {
        attacker.on('document-update-error', resolve);
      });

      attacker.emit('document-update', {
        documentId: 'doc-authz-update',
        update: yjsUpdate('pwned'),
      });

      expect((await error).error).toBe('Access denied');
      await new Promise((r) => setTimeout(r, 100));
      expect(ownerReceived).toBe(false);
      expect(manager.getDocument('doc-authz-update')?.getText('content').toString()).toBe(
        '',
      );
      expect(mockRedis.set).not.toHaveBeenCalled();
      owner.disconnect();
      attacker.disconnect();
    });

    it('rejects updates to a different document than the one joined', async () => {
      const victim = await connectClient('user-authz-victim', 'Alice');
      const owner = await connectClient('user-authz-own-doc', 'Bob');
      await join(victim, 'doc-authz-victim');
      await join(owner, 'doc-authz-own');

      let victimReceived = false;
      victim.on('document-update', () => {
        victimReceived = true;
      });
      const error = new Promise<{ error: string }>((resolve) => {
        owner.on('document-update-error', resolve);
      });

      owner.emit('document-update', {
        documentId: 'doc-authz-victim',
        update: yjsUpdate('cross-doc'),
      });

      expect((await error).error).toBe('Access denied');
      await new Promise((r) => setTimeout(r, 100));
      expect(victimReceived).toBe(false);
      victim.disconnect();
      owner.disconnect();
    });

    it('lets read-only users view and read history but not edit or comment', async () => {
      const owner = await connectClient('user-authz-ro-owner', 'Alice');
      const reader = await connectClient('reader-1', 'Rita');
      await join(owner, 'doc-authz-readonly');

      const sync = new Promise<{ documentId: string }>((resolve) => {
        reader.on('sync-document', resolve);
      });
      const res = await join(reader, 'doc-authz-readonly', { shareToken: 'share-token' });
      expect(res).toEqual({ success: true, access: 'read' });
      expect((await sync).documentId).toBe('doc-authz-readonly');

      const ownerEvents: string[] = [];
      owner.on('document-update', () => ownerEvents.push('document-update'));
      owner.on('comment-added', () => ownerEvents.push('comment-added'));
      owner.on('snapshot-created', () => ownerEvents.push('snapshot-created'));

      const updateError = new Promise<{ error: string }>((resolve) => {
        reader.on('document-update-error', resolve);
      });
      const snapshotError = new Promise<{ error: string }>((resolve) => {
        reader.on('snapshot-error', resolve);
      });
      reader.emit('document-update', {
        documentId: 'doc-authz-readonly',
        update: yjsUpdate('edit'),
      });
      reader.emit('comment-add', {
        documentId: 'doc-authz-readonly',
        comment: { id: 'c1', threadId: 't1', content: 'hi', rangeStart: 0, rangeEnd: 1 },
      });
      reader.emit('request-snapshot', { documentId: 'doc-authz-readonly' });

      expect((await updateError).error).toBe('Access denied');
      expect((await snapshotError).error).toBe('Access denied');

      const history = await new Promise<{ documentId: string }>((resolve) => {
        reader.on('document-history', resolve);
        reader.emit('request-history', { documentId: 'doc-authz-readonly' });
      });
      expect(history.documentId).toBe('doc-authz-readonly');

      await new Promise((r) => setTimeout(r, 100));
      expect(ownerEvents).toEqual([]);
      owner.disconnect();
      reader.disconnect();
    });

    it('revokes access to the previous document after switching', async () => {
      const owner = await connectClient('user-authz-switch', 'Alice');
      await join(owner, 'doc-authz-switch-a');
      await join(owner, 'doc-authz-switch-b');

      const event = await new Promise<string>((resolve) => {
        owner.on('document-history', () => resolve('document-history'));
        owner.on('history-error', () => resolve('history-error'));
        owner.emit('request-history', { documentId: 'doc-authz-switch-a' });
      });

      expect(event).toBe('history-error');
      owner.disconnect();
    });
  });
});
