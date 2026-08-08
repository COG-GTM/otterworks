import type { Logger } from 'pino';
import { RedisAdapter } from '../services/redis-adapter';

interface RedisMock {
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

function createRedisMock(): RedisMock {
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
    hincrby: jest.fn().mockResolvedValue(7),
    lpush: jest.fn().mockResolvedValue(1),
    lrange: jest.fn().mockResolvedValue([]),
    ltrim: jest.fn().mockResolvedValue('OK'),
    llen: jest.fn().mockResolvedValue(0),
    expire: jest.fn().mockResolvedValue(1),
    publish: jest.fn().mockResolvedValue(1),
    subscribe: jest.fn().mockResolvedValue(1),
    ping: jest.fn().mockResolvedValue('PONG'),
    disconnect: jest.fn(),
  };
}

const instances: RedisMock[] = [];
const redisOptions: unknown[] = [];

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn((options: unknown) => {
    redisOptions.push(options);
    const instance = createRedisMock();
    instances.push(instance);
    return instance;
  }),
}));

function createLoggerMock() {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
  };
}

describe('RedisAdapter', () => {
  let adapter: RedisAdapter;
  let client: RedisMock;
  let subscriber: RedisMock;
  let logger: ReturnType<typeof createLoggerMock>;

  beforeEach(() => {
    jest.clearAllMocks();
    instances.length = 0;
    redisOptions.length = 0;
    logger = createLoggerMock();
    adapter = new RedisAdapter(
      { host: 'localhost', port: 6379, password: 'pw', db: 2, keyPrefix: 'collab:' },
      logger as unknown as Logger,
    );
    [client, subscriber] = instances;
  });

  afterEach(() => {
    adapter.disconnect();
  });

  it('creates a client and a subscriber with lazy connections', () => {
    expect(instances).toHaveLength(2);
    expect(redisOptions[0]).toMatchObject({
      host: 'localhost',
      port: 6379,
      password: 'pw',
      db: 2,
      lazyConnect: true,
      maxRetriesPerRequest: 3,
    });
    expect(adapter.getClient()).toBe(client as never);
    expect(adapter.getSubscriber()).toBe(subscriber as never);
  });

  it('backs off retries linearly up to five seconds', () => {
    const { retryStrategy } = redisOptions[0] as {
      retryStrategy: (times: number) => number;
    };

    expect(retryStrategy(1)).toBe(200);
    expect(retryStrategy(10)).toBe(2000);
    expect(retryStrategy(100)).toBe(5000);
  });

  it('connects both connections', async () => {
    await adapter.connect();

    expect(client.connect).toHaveBeenCalledTimes(1);
    expect(subscriber.connect).toHaveBeenCalledTimes(1);
  });

  it('logs client and subscriber lifecycle events', () => {
    const handlers = new Map<string, (arg: unknown) => void>();
    for (const [event, handler] of client.on.mock.calls) {
      handlers.set(`client:${event}`, handler);
    }
    for (const [event, handler] of subscriber.on.mock.calls) {
      handlers.set(`subscriber:${event}`, handler);
    }

    const err = new Error('boom');
    handlers.get('client:error')?.(err);
    handlers.get('client:connect')?.(undefined);
    handlers.get('subscriber:error')?.(err);

    expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_client_error');
    expect(logger.info).toHaveBeenCalledWith('redis_client_connected');
    expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_subscriber_error');
  });

  it('prefixes keys on reads and returns the raw buffer', async () => {
    const stored = Buffer.from('state');
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

  it.each([[undefined], [0]])('uses SET when the TTL is %s', async (ttl) => {
    const payload = Buffer.from('doc-state');

    await adapter.set('doc:1', payload, ttl);

    expect(client.set).toHaveBeenCalledWith('collab:doc:1', payload);
    expect(client.setex).not.toHaveBeenCalled();
  });

  it('deletes prefixed keys', async () => {
    await adapter.del('doc:1');

    expect(client.del).toHaveBeenCalledWith('collab:doc:1');
  });

  it('proxies hash operations with prefixed keys', async () => {
    client.hget.mockResolvedValueOnce('value');
    client.hgetall.mockResolvedValueOnce({ a: '1' });

    await adapter.hset('meta:1', 'version', '2');
    await expect(adapter.hget('meta:1', 'version')).resolves.toBe('value');
    await expect(adapter.hgetall('meta:1')).resolves.toEqual({ a: '1' });
    await adapter.hdel('meta:1', 'version');
    await expect(adapter.hincrby('meta:1', 'version', 1)).resolves.toBe(7);

    expect(client.hset).toHaveBeenCalledWith('collab:meta:1', 'version', '2');
    expect(client.hget).toHaveBeenCalledWith('collab:meta:1', 'version');
    expect(client.hgetall).toHaveBeenCalledWith('collab:meta:1');
    expect(client.hdel).toHaveBeenCalledWith('collab:meta:1', 'version');
    expect(client.hincrby).toHaveBeenCalledWith('collab:meta:1', 'version', 1);
  });

  it('proxies list operations with prefixed keys', async () => {
    client.lrange.mockResolvedValueOnce(['a', 'b']);
    client.llen.mockResolvedValueOnce(2);

    await adapter.lpush('snapshots:1', 'a');
    await expect(adapter.lrange('snapshots:1', 0, -1)).resolves.toEqual(['a', 'b']);
    await adapter.ltrim('snapshots:1', 0, 9);
    await expect(adapter.llen('snapshots:1')).resolves.toBe(2);
    await adapter.expire('snapshots:1', 30);

    expect(client.lpush).toHaveBeenCalledWith('collab:snapshots:1', 'a');
    expect(client.lrange).toHaveBeenCalledWith('collab:snapshots:1', 0, -1);
    expect(client.ltrim).toHaveBeenCalledWith('collab:snapshots:1', 0, 9);
    expect(client.llen).toHaveBeenCalledWith('collab:snapshots:1');
    expect(client.expire).toHaveBeenCalledWith('collab:snapshots:1', 30);
  });

  it('publishes on the un-prefixed channel name', async () => {
    await adapter.publish('doc-events', 'hello');

    expect(client.publish).toHaveBeenCalledWith('doc-events', 'hello');
  });

  it('delivers only messages for the subscribed channel', async () => {
    const callback = jest.fn();

    await adapter.subscribe('doc-events', callback);

    expect(subscriber.subscribe).toHaveBeenCalledWith('doc-events');
    const messageHandler = subscriber.on.mock.calls.find(
      ([event]) => event === 'message',
    )?.[1];
    messageHandler('doc-events', 'wanted');
    messageHandler('other-channel', 'ignored');

    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith('wanted');
  });

  it('reports a healthy ping as true', async () => {
    await expect(adapter.ping()).resolves.toBe(true);
  });

  it('reports an unexpected ping reply as false', async () => {
    client.ping.mockResolvedValueOnce('NOPE');

    await expect(adapter.ping()).resolves.toBe(false);
  });

  it('reports ping failures as false instead of throwing', async () => {
    client.ping.mockRejectedValueOnce(new Error('ECONNREFUSED'));

    await expect(adapter.ping()).resolves.toBe(false);
  });

  it('disconnects both connections and logs it', () => {
    adapter.disconnect();

    expect(client.disconnect).toHaveBeenCalled();
    expect(subscriber.disconnect).toHaveBeenCalled();
    expect(logger.info).toHaveBeenCalledWith('redis_disconnected');
  });

  it('works without a logger and without a key prefix', async () => {
    const bare = new RedisAdapter({ host: 'localhost', port: 6379 });
    const [bareClient] = instances.slice(-2);

    await bare.set('doc:1', Buffer.from('x'));
    bare.disconnect();

    expect(bareClient.set).toHaveBeenCalledWith('doc:1', Buffer.from('x'));
  });
});
