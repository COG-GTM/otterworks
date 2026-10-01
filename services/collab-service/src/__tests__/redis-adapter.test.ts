import type { Logger } from 'pino';
import { RedisAdapter } from '../services/redis-adapter';

interface RedisInstanceMock {
  on: jest.Mock;
  connect: jest.Mock;
  getBuffer: jest.Mock;
  set: jest.Mock;
  setex: jest.Mock;
  del: jest.Mock;
  hset: jest.Mock;
  hget: jest.Mock;
  hgetall: jest.Mock;
  hdel: jest.Mock;
  hincrby: jest.Mock;
  lpush: jest.Mock;
  lrange: jest.Mock;
  ltrim: jest.Mock;
  llen: jest.Mock;
  expire: jest.Mock;
  publish: jest.Mock;
  subscribe: jest.Mock;
  ping: jest.Mock;
  disconnect: jest.Mock;
}

const mockInstances: RedisInstanceMock[] = [];
const mockOptions: Array<Record<string, unknown>> = [];

const mockCreateInstance = (): RedisInstanceMock => ({
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
  hincrby: jest.fn().mockResolvedValue(4),
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

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn((options: Record<string, unknown>) => {
    const instance = mockCreateInstance();
    mockInstances.push(instance);
    mockOptions.push(options);
    return instance;
  }),
}));

const loggerMock = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};
const logger = loggerMock as unknown as Logger;

function handlerFor(instance: RedisInstanceMock, event: string) {
  const call = instance.on.mock.calls.find(([name]) => name === event);
  if (!call) throw new Error(`no handler registered for "${event}"`);
  return call[1] as (...args: unknown[]) => void;
}

describe('RedisAdapter', () => {
  let adapter: RedisAdapter;
  let client: RedisInstanceMock;
  let subscriber: RedisInstanceMock;

  beforeEach(() => {
    jest.clearAllMocks();
    mockInstances.length = 0;
    mockOptions.length = 0;
    adapter = new RedisAdapter(
      { host: 'redis.internal', port: 6380, password: 'pw', db: 2, keyPrefix: 'collab:' },
      logger,
    );
    [client, subscriber] = mockInstances;
  });

  afterEach(() => {
    adapter.disconnect();
  });

  describe('construction', () => {
    it('opens a client and a subscriber with lazy connect and a retry strategy', () => {
      expect(mockInstances).toHaveLength(2);
      expect(mockOptions[0]).toMatchObject({
        host: 'redis.internal',
        port: 6380,
        password: 'pw',
        db: 2,
        lazyConnect: true,
        maxRetriesPerRequest: 3,
      });
      expect(mockOptions[0]).toEqual(mockOptions[1]);
    });

    it('caps the retry backoff at five seconds', () => {
      const retryStrategy = mockOptions[0].retryStrategy as (times: number) => number;

      expect(retryStrategy(1)).toBe(200);
      expect(retryStrategy(10)).toBe(2000);
      expect(retryStrategy(100)).toBe(5000);
    });

    it('defaults db to 0 and the key prefix to empty', async () => {
      mockInstances.length = 0;
      mockOptions.length = 0;
      const bare = new RedisAdapter({ host: 'localhost', port: 6379 });

      await bare.get('doc:1');

      expect(mockOptions[0]).toMatchObject({ db: 0 });
      expect(mockInstances[0].getBuffer).toHaveBeenCalledWith('doc:1');
      bare.disconnect();
    });

    it('logs client and subscriber lifecycle events', () => {
      const err = new Error('ECONNRESET');

      handlerFor(client, 'error')(err);
      handlerFor(client, 'connect')();
      handlerFor(subscriber, 'error')(err);

      expect(loggerMock.error).toHaveBeenCalledWith({ err }, 'redis_client_error');
      expect(loggerMock.info).toHaveBeenCalledWith('redis_client_connected');
      expect(loggerMock.error).toHaveBeenCalledWith({ err }, 'redis_subscriber_error');
    });

    it('tolerates being constructed without a logger', () => {
      mockInstances.length = 0;
      const silent = new RedisAdapter({ host: 'localhost', port: 6379 });

      expect(() =>
        handlerFor(mockInstances[0], 'error')(new Error('boom')),
      ).not.toThrow();
      expect(() => silent.disconnect()).not.toThrow();
    });
  });

  describe('connection lifecycle', () => {
    it('connects both sockets', async () => {
      await adapter.connect();

      expect(client.connect).toHaveBeenCalledTimes(1);
      expect(subscriber.connect).toHaveBeenCalledTimes(1);
    });

    it('exposes the underlying clients', () => {
      expect(adapter.getClient()).toBe(client);
      expect(adapter.getSubscriber()).toBe(subscriber);
    });

    it('disconnects both sockets and logs it', () => {
      adapter.disconnect();

      expect(client.disconnect).toHaveBeenCalled();
      expect(subscriber.disconnect).toHaveBeenCalled();
      expect(loggerMock.info).toHaveBeenCalledWith('redis_disconnected');
    });
  });

  describe('string keys', () => {
    it('reads a prefixed key as a buffer', async () => {
      const stored = Buffer.from('doc-state');
      client.getBuffer.mockResolvedValueOnce(stored);

      await expect(adapter.get('doc:1')).resolves.toBe(stored);
      expect(client.getBuffer).toHaveBeenCalledWith('collab:doc:1');
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

    it('deletes a prefixed key', async () => {
      await adapter.del('doc:1');

      expect(client.del).toHaveBeenCalledWith('collab:doc:1');
    });

    it('expires a prefixed key', async () => {
      await adapter.expire('doc:1', 90);

      expect(client.expire).toHaveBeenCalledWith('collab:doc:1', 90);
    });
  });

  describe('hashes', () => {
    it('writes and reads hash fields through the prefix', async () => {
      client.hget.mockResolvedValueOnce('bar');

      await adapter.hset('meta:1', 'foo', 'bar');

      await expect(adapter.hget('meta:1', 'foo')).resolves.toBe('bar');
      expect(client.hset).toHaveBeenCalledWith('collab:meta:1', 'foo', 'bar');
      expect(client.hget).toHaveBeenCalledWith('collab:meta:1', 'foo');
    });

    it('reads an entire hash', async () => {
      client.hgetall.mockResolvedValueOnce({ a: '1' });

      await expect(adapter.hgetall('meta:1')).resolves.toEqual({ a: '1' });
      expect(client.hgetall).toHaveBeenCalledWith('collab:meta:1');
    });

    it('deletes and increments hash fields', async () => {
      await adapter.hdel('meta:1', 'foo');

      await expect(adapter.hincrby('meta:1', 'hits', 3)).resolves.toBe(4);
      expect(client.hdel).toHaveBeenCalledWith('collab:meta:1', 'foo');
      expect(client.hincrby).toHaveBeenCalledWith('collab:meta:1', 'hits', 3);
    });
  });

  describe('lists', () => {
    it('pushes, ranges, trims and measures a prefixed list', async () => {
      client.lrange.mockResolvedValueOnce(['a', 'b']);
      client.llen.mockResolvedValueOnce(2);

      await adapter.lpush('history:1', 'a');
      await adapter.ltrim('history:1', 0, 9);

      await expect(adapter.lrange('history:1', 0, -1)).resolves.toEqual(['a', 'b']);
      await expect(adapter.llen('history:1')).resolves.toBe(2);
      expect(client.lpush).toHaveBeenCalledWith('collab:history:1', 'a');
      expect(client.ltrim).toHaveBeenCalledWith('collab:history:1', 0, 9);
      expect(client.lrange).toHaveBeenCalledWith('collab:history:1', 0, -1);
      expect(client.llen).toHaveBeenCalledWith('collab:history:1');
    });
  });

  describe('pub/sub', () => {
    it('publishes on the raw (unprefixed) channel', async () => {
      await adapter.publish('collab-events', 'hello');

      expect(client.publish).toHaveBeenCalledWith('collab-events', 'hello');
    });

    it('delivers only messages for the subscribed channel', async () => {
      const received: string[] = [];

      await adapter.subscribe('collab-events', (msg) => received.push(msg));
      const onMessage = handlerFor(subscriber, 'message');
      onMessage('collab-events', 'mine');
      onMessage('other-channel', 'not-mine');

      expect(subscriber.subscribe).toHaveBeenCalledWith('collab-events');
      expect(received).toEqual(['mine']);
    });
  });

  describe('health', () => {
    it('reports true when the server answers PONG', async () => {
      await expect(adapter.ping()).resolves.toBe(true);
    });

    it('reports false on an unexpected reply', async () => {
      client.ping.mockResolvedValueOnce('nope');

      await expect(adapter.ping()).resolves.toBe(false);
    });

    it('reports ping failures as false instead of throwing', async () => {
      client.ping.mockRejectedValueOnce(new Error('ECONNREFUSED'));

      await expect(adapter.ping()).resolves.toBe(false);
    });
  });
});
