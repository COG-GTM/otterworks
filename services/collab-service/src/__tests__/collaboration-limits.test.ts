import { Server as SocketIOServer } from 'socket.io';
import { createServer } from 'http';
import { io as clientIO, Socket as ClientSocket } from 'socket.io-client';
import jwt from 'jsonwebtoken';
import * as Y from 'yjs';
import { CollaborationLimits, CollaborationManager } from '../handlers/collaboration';
import { DocumentStore } from '../services/document-store';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';
import { MetricsCollector } from '../metrics';
import { createAuthMiddleware } from '../middleware/auth';
import { RedisAdapter } from '../services/redis-adapter';

const JWT_SECRET = 'test-secret-key-for-unit-tests';

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

const TEST_LIMITS: Partial<CollaborationLimits> = {
  maxUpdateBytes: 1024,
  maxDocumentBytes: 4096,
  maxTotalDocumentBytes: 1024 * 1024,
  maxDocumentsInMemory: 100,
  maxDocumentsPerUser: 2,
  persistDebounceMs: 100,
  socketUpdates: { limit: 5, windowMs: 60000 },
  userUpdates: { limit: 1000, windowMs: 60000 },
  socketSnapshots: { limit: 1, windowMs: 60000 },
  userSnapshots: { limit: 1000, windowMs: 60000 },
  documentSnapshots: { limit: 1000, windowMs: 60000 },
  userJoins: { limit: 1000, windowMs: 60000 },
};

function textUpdate(content: string): string {
  const doc = new Y.Doc();
  doc.getText('content').insert(0, content);
  return Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64');
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe('CollaborationManager resource limits', () => {
  let io: SocketIOServer;
  let httpServer: ReturnType<typeof createServer>;
  let manager: CollaborationManager;
  let port: number;
  const clients: ClientSocket[] = [];

  beforeAll((done) => {
    httpServer = createServer();
    io = new SocketIOServer(httpServer, { cors: { origin: '*' } });
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
      limits: TEST_LIMITS,
    });
    manager.start();
    httpServer.listen(0, () => {
      const addr = httpServer.address();
      port = typeof addr === 'object' && addr ? addr.port : 0;
      done();
    });
  }, 15000);

  afterAll((done) => {
    manager.stop();
    io.close();
    httpServer.close(done);
  });

  afterEach(() => {
    while (clients.length) clients.pop()?.disconnect();
    jest.clearAllMocks();
  });

  function connect(userId: string): Promise<ClientSocket> {
    return new Promise((resolve, reject) => {
      const claims = { sub: userId, name: userId, roles: ['user'] };
      const token = jwt.sign(claims, JWT_SECRET); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
      const client = clientIO(`http://localhost:${port}`, {
        auth: { token },
        transports: ['websocket'],
      });
      clients.push(client);
      client.on('connect', () => resolve(client));
      client.on('connect_error', reject);
    });
  }

  function join(
    client: ClientSocket,
    documentId: unknown,
  ): Promise<{ success: boolean; error?: string }> {
    return new Promise((resolve) => {
      client.emit('join-document', { documentId }, resolve);
    });
  }

  function nextUpdateError(client: ClientSocket): Promise<{ error: string }> {
    return new Promise((resolve) => client.once('document-update-error', resolve));
  }

  it('rejects a decoded update larger than maxUpdateBytes', async () => {
    const client = await connect('limit-user-1');
    await join(client, 'doc-limit-update');
    const error = nextUpdateError(client);
    client.emit('document-update', {
      documentId: 'doc-limit-update',
      update: textUpdate('x'.repeat(2000)),
    });
    expect((await error).error).toBe('Update exceeds size limit');
  });

  it('rejects updates once the document reaches maxDocumentBytes', async () => {
    const client = await connect('limit-user-2');
    await join(client, 'doc-limit-size');
    const errors: string[] = [];
    client.on('document-update-error', (e: { error: string }) => errors.push(e.error));
    for (let i = 0; i < 5; i++) {
      client.emit('document-update', {
        documentId: 'doc-limit-size',
        update: textUpdate(String(i).repeat(900)),
      });
    }
    await sleep(200);
    expect(errors).toContain('Document size limit reached');
  });

  it('rate-limits document updates per socket', async () => {
    const client = await connect('limit-user-3');
    await join(client, 'doc-limit-rate');
    const errors: string[] = [];
    client.on('document-update-error', (e: { error: string }) => errors.push(e.error));
    for (let i = 0; i < 7; i++) {
      client.emit('document-update', {
        documentId: 'doc-limit-rate',
        update: textUpdate('a'),
      });
    }
    await sleep(200);
    expect(errors.filter((e) => e === 'Too many updates')).toHaveLength(2);
  });

  it('debounces Redis persistence into a single full-state write', async () => {
    const client = await connect('limit-user-4');
    await join(client, 'doc-limit-debounce');
    for (let i = 0; i < 4; i++) {
      client.emit('document-update', {
        documentId: 'doc-limit-debounce',
        update: textUpdate(`edit-${i}`),
      });
    }
    const stateWrites = () =>
      mockRedis.set.mock.calls.filter(([key]) => key.includes('doc-limit-debounce'));
    await sleep(50);
    expect(stateWrites()).toHaveLength(0);
    await sleep(200);
    expect(stateWrites()).toHaveLength(1);
  });

  it('rate-limits snapshot requests per socket', async () => {
    const client = await connect('limit-user-5');
    await join(client, 'doc-limit-snap');
    const created = new Promise((resolve) => client.once('snapshot-created', resolve));
    const rejected = new Promise<{ error: string }>((resolve) =>
      client.once('snapshot-error', resolve),
    );
    client.emit('request-snapshot', { documentId: 'doc-limit-snap' });
    client.emit('request-snapshot', { documentId: 'doc-limit-snap' });
    await created;
    expect((await rejected).error).toBe('Too many snapshot requests');
    expect(mockRedis.lpush).toHaveBeenCalledTimes(1);
  });

  it('caps how many documents a single user can hold open', async () => {
    const a = await connect('limit-user-6');
    const b = await connect('limit-user-6');
    const c = await connect('limit-user-6');
    expect((await join(a, 'doc-quota-1')).success).toBe(true);
    expect((await join(b, 'doc-quota-2')).success).toBe(true);
    expect(await join(c, 'doc-quota-3')).toEqual({
      success: false,
      error: 'Too many open documents',
    });
    // Switching an existing socket to a new document frees its previous slot
    expect((await join(b, 'doc-quota-3')).success).toBe(true);
  });

  it('rejects invalid document ids', async () => {
    const client = await connect('limit-user-7');
    expect((await join(client, 'x'.repeat(300))).success).toBe(false);
    expect((await join(client, { $ne: 1 })).success).toBe(false);
  });

  it('ignores updates for a document the socket has not joined', async () => {
    const owner = await connect('limit-user-8');
    const other = await connect('limit-user-9');
    await join(owner, 'doc-limit-owner');
    const received = jest.fn();
    owner.on('document-update', received);
    other.emit('document-update', {
      documentId: 'doc-limit-owner',
      update: textUpdate('z'),
    });
    await sleep(100);
    expect(received).not.toHaveBeenCalled();
  });
});
