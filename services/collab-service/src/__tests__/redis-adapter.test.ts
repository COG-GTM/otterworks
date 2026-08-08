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

function createRedisInstanceMock(): RedisInstanceMock {
  return {
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
    hincrby: jest.fn().mockResolvedValue(3),
    lpush: jest.fn().mockResolvedValue(1),
    lrange: jest.fn().mockResolvedValue([]),
    ltrim: jest.fn().mockResolvedValue('OK'),
    llen: jest.fn().mockResolvedValue(2),
    expire: jest.fn().mockResolvedValue(1),
    publish: jest.fn().mockResolvedValue(1),
    subscribe: jest.fn().mockResolvedValue(1),
    ping: jest.fn().mockResolvedValue('PONG'),
    disconnect: jest.fn(),
  };
}

const instances: RedisInstanceMock[] = [];
const constructorOptions: Array<Record<string, unknown>> = [];

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn((options: Record<string, unknown>) => {
    constructorOptions.push(options);
    const instance = createRedisInstanceMock();
    instances.push(instance);
    return instance;
  }),
}));

function handlerFor(instance: RedisInstanceMock, event: string): (arg: unknown) => void {
  const call = instance.on.mock.calls.find(([name]) => name === event);
  if (!call) throw new Error(`no handler registered for "${event}"`);
  return call[1] as (arg: unknown) => void;
}

describe('RedisAdapter', () => {
  const logger = {
    info: jest.fn(),
    error: jest.fn(),
  } as unknown as Logger;

  let adapter: RedisAdapter;
  let client: RedisInstanceMock;
  let subscriber: RedisInstanceMock;

  beforeEach(() => {
    jest.clearAllMocks();
    instances.length = 0;
    constructorOptions.length = 0;
    adapter = new RedisAdapter(
      { host: 'redis.test', port: 6379, password: 'pw', db: 2, keyPrefix: 'collab:' },
      logger,
    );
    [client, subscriber] = instances;
  });

  afterEach(() => {
    adapter.disconnect();
  });

  describe('construction', () => {
    it('opens a separate client and subscriber connection with lazy connect', () => {
      expect(instances).toHaveLength(2);
      expect(adapter.getClient()).toBe(client);
      expect(adapter.getSubscriber()).toBe(subscriber);
      expect(constructorOptions[0]).toMatchObject({
        host: 'redis.test',
        port: 6379,
        password: 'pw',
        db: 2,
        maxRetriesPerRequest: 3,
        lazyConnect: true,
      });
    });

    it('backs off linearly and caps the retry delay at five seconds', () => {
      const retryStrategy = constructorOptions[0].retryStrategy as (n: number) => number;

      expect(retryStrategy(1)).toBe(200);
      expect(retryStrategy(10)).toBe(2000);
      expect(retryStrategy(100)).toBe(5000);
    });

    it('logs client and subscriber lifecycle events', () => {
      const err = new Error('ECONNRESET');

      handlerFor(client, 'error')(err);
      handlerFor(client, 'connect')(undefined);
      handlerFor(subscriber, 'error')(err);

      expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_client_error');
      expect(logger.info).toHaveBeenCalledWith('redis_client_connected');
      expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_subscriber_error');
    });

    it('tolerates lifecycle events when no logger is supplied', () => {
      instances.length = 0;
      const silent = new RedisAdapter({ host: 'localhost', port: 6379 });
      const [silentClient] = instances;

      expect(() => {
        handlerFor(silentClient, 'error')(new Error('boom'));
        handlerFor(silentClient, 'connect')(undefined);
        silent.disconnect();
      }).not.toThrow();
    });

    it('defaults the database to 0 and the key prefix to empty', async () => {
      instances.length = 0;
      constructorOptions.length = 0;
      const unprefixed = new RedisAdapter({ host: 'localhost', port: 6379 });

      await unprefixed.get('doc:1');

      expect(constructorOptions[0]).toMatchObject({ db: 0 });
      expect(instances[0].getBuffer).toHaveBeenCalledWith('doc:1');
      unprefixed.disconnect();
    });
  });

  describe('connection lifecycle', () => {
    it('connects both sockets', async () => {
      await adapter.connect();

      expect(client.connect).toHaveBeenCalledTimes(1);
      expect(subscriber.connect).toHaveBeenCalledTimes(1);
    });

    it('disconnects both sockets and logs it', () => {
      adapter.disconnect();

      expect(client.disconnect).toHaveBeenCalled();
      expect(subscriber.disconnect).toHaveBeenCalled();
      expect(logger.info).toHaveBeenCalledWith('redis_disconnected');
    });
  });

  describe('string values', () => {
    it('reads buffers through the prefixed key', async () => {
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

    it('deletes the prefixed key', async () => {
      await adapter.del('doc:1');

      expect(client.del).toHaveBeenCalledWith('collab:doc:1');
    });
  });

  describe('hashes', () => {
    it('writes, reads and deletes fields on the prefixed key', async () => {
      client.hget.mockResolvedValueOnce('v1');
      client.hgetall.mockResolvedValueOnce({ version: '1' });

      await adapter.hset('meta:1', 'version', '1');
      await expect(adapter.hget('meta:1', 'version')).resolves.toBe('v1');
      await expect(adapter.hgetall('meta:1')).resolves.toEqual({ version: '1' });
      await adapter.hdel('meta:1', 'version');

      expect(client.hset).toHaveBeenCalledWith('collab:meta:1', 'version', '1');
      expect(client.hget).toHaveBeenCalledWith('collab:meta:1', 'version');
      expect(client.hgetall).toHaveBeenCalledWith('collab:meta:1');
      expect(client.hdel).toHaveBeenCalledWith('collab:meta:1', 'version');
    });

    it('returns the incremented counter value', async () => {
      await expect(adapter.hincrby('meta:1', 'version', 1)).resolves.toBe(3);
      expect(client.hincrby).toHaveBeenCalledWith('collab:meta:1', 'version', 1);
    });
  });

  describe('lists', () => {
    it('pushes, ranges, trims and measures the prefixed list', async () => {
      client.lrange.mockResolvedValueOnce(['a', 'b']);

      await adapter.lpush('snap:1', 'a');
      await expect(adapter.lrange('snap:1', 0, 9)).resolves.toEqual(['a', 'b']);
      await adapter.ltrim('snap:1', 0, 49);
      await expect(adapter.llen('snap:1')).resolves.toBe(2);

      expect(client.lpush).toHaveBeenCalledWith('collab:snap:1', 'a');
      expect(client.lrange).toHaveBeenCalledWith('collab:snap:1', 0, 9);
      expect(client.ltrim).toHaveBeenCalledWith('collab:snap:1', 0, 49);
      expect(client.llen).toHaveBeenCalledWith('collab:snap:1');
    });

    it('expires the prefixed key', async () => {
      await adapter.expire('snap:1', 120);

      expect(client.expire).toHaveBeenCalledWith('collab:snap:1', 120);
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
      const onMessage = handlerFor(subscriber, 'message') as unknown as (
        channel: string,
        message: string,
      ) => void;
      onMessage('collab-events', 'yes');
      onMessage('other-channel', 'no');

      expect(subscriber.subscribe).toHaveBeenCalledWith('collab-events');
      expect(received).toEqual(['yes']);
    });
  });

  describe('health', () => {
    it('reports a healthy ping', async () => {
      await expect(adapter.ping()).resolves.toBe(true);
    });

    it('reports an unexpected ping reply as unhealthy', async () => {
      client.ping.mockResolvedValueOnce('LOADING');

      await expect(adapter.ping()).resolves.toBe(false);
    });

    it('reports a failed ping as unhealthy instead of throwing', async () => {
      client.ping.mockRejectedValueOnce(new Error('ECONNREFUSED'));

      await expect(adapter.ping()).resolves.toBe(false);
    });
  });
});
