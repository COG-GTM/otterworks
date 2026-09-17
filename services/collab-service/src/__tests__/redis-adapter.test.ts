import Redis from 'ioredis';
import type { Logger } from 'pino';
import { RedisAdapter } from '../services/redis-adapter';

type RedisListener = (...args: unknown[]) => void;

const mockCreateClient = () => ({
  on: jest.fn(),
  connect: jest.fn().mockResolvedValue(undefined),
  getBuffer: jest.fn().mockResolvedValue(null),
  set: jest.fn().mockResolvedValue('OK'),
  setex: jest.fn().mockResolvedValue('OK'),
  del: jest.fn().mockResolvedValue(1),
  hset: jest.fn().mockResolvedValue(1),
  hget: jest.fn().mockResolvedValue(null),
  hgetall: jest.fn().mockResolvedValue({}),
  hdel: jest.fn().mockResolvedValue(1),
  hincrby: jest.fn().mockResolvedValue(1),
  lpush: jest.fn().mockResolvedValue(1),
  lrange: jest.fn().mockResolvedValue([]),
  ltrim: jest.fn().mockResolvedValue('OK'),
  llen: jest.fn().mockResolvedValue(0),
  expire: jest.fn().mockResolvedValue(1),
  publish: jest.fn().mockResolvedValue(1),
  subscribe: jest.fn().mockResolvedValue(1),
  ping: jest.fn().mockResolvedValue('PONG'),
  disconnect: jest.fn(),
});

type MockClient = ReturnType<typeof mockCreateClient>;

const mockClients: MockClient[] = [];

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn(),
}));

const RedisMock = Redis as unknown as jest.Mock;

function listenersFor(client: MockClient, event: string): RedisListener[] {
  return client.on.mock.calls
    .filter((call) => call[0] === event)
    .map((call) => call[1] as RedisListener);
}

describe('RedisAdapter', () => {
  let adapter: RedisAdapter;
  let client: MockClient;
  let subscriber: MockClient;
  let logger: Logger;

  beforeEach(() => {
    jest.clearAllMocks();
    mockClients.length = 0;
    RedisMock.mockImplementation(() => {
      const instance = mockCreateClient();
      mockClients.push(instance);
      return instance;
    });

    logger = {
      info: jest.fn(),
      warn: jest.fn(),
      error: jest.fn(),
      debug: jest.fn(),
    } as unknown as Logger;

    adapter = new RedisAdapter(
      { host: 'redis.internal', port: 6379, password: 'pw', db: 2, keyPrefix: 'collab:' },
      logger,
    );
    [client, subscriber] = mockClients;
  });

  afterEach(() => {
    adapter.disconnect();
  });

  describe('construction', () => {
    it('opens a separate command and subscriber connection with the same options', () => {
      expect(RedisMock).toHaveBeenCalledTimes(2);
      expect(mockClients).toHaveLength(2);
      expect(RedisMock.mock.calls[0][0]).toMatchObject({
        host: 'redis.internal',
        port: 6379,
        password: 'pw',
        db: 2,
        maxRetriesPerRequest: 3,
        lazyConnect: true,
      });
      expect(RedisMock.mock.calls[1][0]).toEqual(RedisMock.mock.calls[0][0]);
      expect(adapter.getClient()).toBe(client);
      expect(adapter.getSubscriber()).toBe(subscriber);
    });

    it('defaults the database to 0 when none is configured', () => {
      mockClients.length = 0;
      const noDb = new RedisAdapter({ host: 'localhost', port: 6379 });

      expect(RedisMock.mock.calls[2][0]).toMatchObject({ db: 0, password: undefined });
      noDb.disconnect();
    });

    it('backs off linearly and caps the retry delay at 5s', () => {
      const { retryStrategy } = RedisMock.mock.calls[0][0] as {
        retryStrategy: (times: number) => number;
      };

      expect(retryStrategy(1)).toBe(200);
      expect(retryStrategy(10)).toBe(2000);
      expect(retryStrategy(1000)).toBe(5000);
    });

    it('logs client errors, connects and subscriber errors', () => {
      const err = new Error('ECONNREFUSED');

      listenersFor(client, 'error')[0](err);
      listenersFor(client, 'connect')[0]();
      listenersFor(subscriber, 'error')[0](err);

      expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_client_error');
      expect(logger.info).toHaveBeenCalledWith('redis_client_connected');
      expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_subscriber_error');
    });

    it('tolerates being constructed without a logger', () => {
      mockClients.length = 0;
      const silent = new RedisAdapter({ host: 'localhost', port: 6379 });
      const [silentClient] = mockClients;

      expect(() =>
        listenersFor(silentClient, 'error')[0](new Error('boom')),
      ).not.toThrow();
      expect(() => listenersFor(silentClient, 'connect')[0]()).not.toThrow();
      expect(() => silent.disconnect()).not.toThrow();
    });
  });

  describe('connection lifecycle', () => {
    it('connects both clients', async () => {
      await adapter.connect();

      expect(client.connect).toHaveBeenCalledTimes(1);
      expect(subscriber.connect).toHaveBeenCalledTimes(1);
    });

    it('disconnects both clients and logs it', () => {
      adapter.disconnect();

      expect(client.disconnect).toHaveBeenCalled();
      expect(subscriber.disconnect).toHaveBeenCalled();
      expect(logger.info).toHaveBeenCalledWith('redis_disconnected');
    });
  });

  describe('string values', () => {
    it('reads binary values through the prefixed key', async () => {
      const stored = Buffer.from('doc-state');
      client.getBuffer.mockResolvedValueOnce(stored);

      await expect(adapter.get('doc:1')).resolves.toBe(stored);
      expect(client.getBuffer).toHaveBeenCalledWith('collab:doc:1');
    });

    it('returns null when the key is missing', async () => {
      await expect(adapter.get('missing')).resolves.toBeNull();
    });

    it('uses SETEX when a TTL is supplied', async () => {
      const payload = Buffer.from('doc-state');

      await adapter.set('doc:1', payload, 60);

      expect(client.setex).toHaveBeenCalledWith('collab:doc:1', 60, payload);
      expect(client.set).not.toHaveBeenCalled();
    });

    it('uses SET when no TTL is supplied', async () => {
      const payload = Buffer.from('doc-state');

      await adapter.set('doc:1', payload);

      expect(client.set).toHaveBeenCalledWith('collab:doc:1', payload);
      expect(client.setex).not.toHaveBeenCalled();
    });

    it('treats a zero TTL as no expiry', async () => {
      await adapter.set('doc:1', Buffer.from('x'), 0);

      expect(client.set).toHaveBeenCalledWith('collab:doc:1', Buffer.from('x'));
      expect(client.setex).not.toHaveBeenCalled();
    });

    it('deletes through the prefixed key', async () => {
      await adapter.del('doc:1');

      expect(client.del).toHaveBeenCalledWith('collab:doc:1');
    });
  });

  describe('hashes', () => {
    it('writes and reads hash fields through the prefixed key', async () => {
      client.hget.mockResolvedValueOnce('7');

      await adapter.hset('meta:1', 'version', '7');

      expect(client.hset).toHaveBeenCalledWith('collab:meta:1', 'version', '7');
      await expect(adapter.hget('meta:1', 'version')).resolves.toBe('7');
      expect(client.hget).toHaveBeenCalledWith('collab:meta:1', 'version');
    });

    it('returns the whole hash', async () => {
      client.hgetall.mockResolvedValueOnce({ documentId: 'doc-1' });

      await expect(adapter.hgetall('meta:1')).resolves.toEqual({ documentId: 'doc-1' });
      expect(client.hgetall).toHaveBeenCalledWith('collab:meta:1');
    });

    it('deletes a hash field', async () => {
      await adapter.hdel('meta:1', 'version');

      expect(client.hdel).toHaveBeenCalledWith('collab:meta:1', 'version');
    });

    it('returns the incremented value from hincrby', async () => {
      client.hincrby.mockResolvedValueOnce(4);

      await expect(adapter.hincrby('meta:1', 'version', 1)).resolves.toBe(4);
      expect(client.hincrby).toHaveBeenCalledWith('collab:meta:1', 'version', 1);
    });
  });

  describe('lists', () => {
    it('pushes, ranges, trims and counts through the prefixed key', async () => {
      client.lrange.mockResolvedValueOnce(['a', 'b']);
      client.llen.mockResolvedValueOnce(2);

      await adapter.lpush('snapshots:1', 'a');
      await expect(adapter.lrange('snapshots:1', 0, 19)).resolves.toEqual(['a', 'b']);
      await adapter.ltrim('snapshots:1', 0, 49);
      await expect(adapter.llen('snapshots:1')).resolves.toBe(2);

      expect(client.lpush).toHaveBeenCalledWith('collab:snapshots:1', 'a');
      expect(client.lrange).toHaveBeenCalledWith('collab:snapshots:1', 0, 19);
      expect(client.ltrim).toHaveBeenCalledWith('collab:snapshots:1', 0, 49);
      expect(client.llen).toHaveBeenCalledWith('collab:snapshots:1');
    });

    it('sets expiry through the prefixed key', async () => {
      await adapter.expire('snapshots:1', 604800);

      expect(client.expire).toHaveBeenCalledWith('collab:snapshots:1', 604800);
    });
  });

  describe('pub/sub', () => {
    it('publishes on the raw channel name, without the key prefix', async () => {
      await adapter.publish('collab-events', 'hello');

      expect(client.publish).toHaveBeenCalledWith('collab-events', 'hello');
    });

    it('delivers only messages for the subscribed channel', async () => {
      const received: string[] = [];

      await adapter.subscribe('collab-events', (msg) => received.push(msg));

      expect(subscriber.subscribe).toHaveBeenCalledWith('collab-events');
      const onMessage = listenersFor(subscriber, 'message')[0];
      onMessage('collab-events', 'mine');
      onMessage('other-channel', 'not-mine');

      expect(received).toEqual(['mine']);
    });
  });

  describe('health', () => {
    it('reports a healthy connection when the server replies PONG', async () => {
      await expect(adapter.ping()).resolves.toBe(true);
    });

    it('reports unhealthy when the reply is not PONG', async () => {
      client.ping.mockResolvedValueOnce('nope');

      await expect(adapter.ping()).resolves.toBe(false);
    });

    it('reports ping failures as false instead of throwing', async () => {
      client.ping.mockRejectedValueOnce(new Error('ECONNREFUSED'));

      await expect(adapter.ping()).resolves.toBe(false);
    });
  });

  describe('key prefixing', () => {
    it('leaves keys untouched when no prefix is configured', async () => {
      mockClients.length = 0;
      const unprefixed = new RedisAdapter({ host: 'localhost', port: 6379 });
      const [unprefixedClient] = mockClients;

      await unprefixed.get('doc:1');

      expect(unprefixedClient.getBuffer).toHaveBeenCalledWith('doc:1');
      unprefixed.disconnect();
    });
  });
});
