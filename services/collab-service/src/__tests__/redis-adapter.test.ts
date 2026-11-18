import { EventEmitter } from 'events';
import Redis from 'ioredis';
import { RedisAdapter } from '../services/redis-adapter';

class FakeRedis extends EventEmitter {
  options: Record<string, unknown>;
  connect = jest.fn().mockResolvedValue(undefined);
  disconnect = jest.fn();
  getBuffer = jest.fn();
  setex = jest.fn().mockResolvedValue('OK');
  set = jest.fn().mockResolvedValue('OK');
  del = jest.fn().mockResolvedValue(1);
  hset = jest.fn().mockResolvedValue(1);
  hget = jest.fn();
  hgetall = jest.fn();
  hdel = jest.fn().mockResolvedValue(1);
  hincrby = jest.fn();
  lpush = jest.fn().mockResolvedValue(1);
  lrange = jest.fn();
  ltrim = jest.fn().mockResolvedValue('OK');
  llen = jest.fn();
  expire = jest.fn().mockResolvedValue(1);
  publish = jest.fn().mockResolvedValue(1);
  subscribe = jest.fn().mockResolvedValue(1);
  ping = jest.fn();

  constructor(options: Record<string, unknown>) {
    super();
    this.options = options;
  }
}

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn().mockImplementation((opts) => new FakeRedis(opts)),
}));

const RedisMock = Redis as unknown as jest.Mock;

function makeLogger() {
  return { info: jest.fn(), error: jest.fn(), warn: jest.fn(), debug: jest.fn() };
}

describe('RedisAdapter', () => {
  let logger: ReturnType<typeof makeLogger>;
  let adapter: RedisAdapter;
  let client: FakeRedis;
  let subscriber: FakeRedis;

  beforeEach(() => {
    RedisMock.mockClear();
    logger = makeLogger();
    adapter = new RedisAdapter(
      { host: 'h', port: 1234, password: 'pw', db: 3, keyPrefix: 'pre:' },
      logger as never,
    );
    client = adapter.getClient() as unknown as FakeRedis;
    subscriber = adapter.getSubscriber() as unknown as FakeRedis;
  });

  describe('construction', () => {
    it('creates distinct lazy client and subscriber connections with the given options', () => {
      expect(RedisMock).toHaveBeenCalledTimes(2);
      expect(client).not.toBe(subscriber);
      expect(client.options).toMatchObject({
        host: 'h',
        port: 1234,
        password: 'pw',
        db: 3,
        maxRetriesPerRequest: 3,
        lazyConnect: true,
      });
    });

    it('uses a capped linear retry strategy', () => {
      const retry = client.options.retryStrategy as (n: number) => number;
      expect(retry(1)).toBe(200);
      expect(retry(10)).toBe(2000);
      expect(retry(100)).toBe(5000);
    });

    it('defaults db to 0 and key prefix to empty', async () => {
      const bare = new RedisAdapter({ host: 'h', port: 1 });
      const bareClient = bare.getClient() as unknown as FakeRedis;
      expect(bareClient.options.db).toBe(0);
      await bare.del('k');
      expect(bareClient.del).toHaveBeenCalledWith('k');
    });

    it('logs client errors, connects and subscriber errors', () => {
      const err = new Error('boom');
      client.emit('error', err);
      client.emit('connect');
      subscriber.emit('error', err);
      expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_client_error');
      expect(logger.info).toHaveBeenCalledWith('redis_client_connected');
      expect(logger.error).toHaveBeenCalledWith({ err }, 'redis_subscriber_error');
    });

    it('tolerates events without a logger', () => {
      const bare = new RedisAdapter({ host: 'h', port: 1 });
      const c = bare.getClient() as unknown as FakeRedis;
      const s = bare.getSubscriber() as unknown as FakeRedis;
      expect(() => {
        c.emit('error', new Error('x'));
        c.emit('connect');
        s.emit('error', new Error('y'));
        bare.disconnect();
      }).not.toThrow();
    });
  });

  it('connect() connects both connections', async () => {
    await adapter.connect();
    expect(client.connect).toHaveBeenCalled();
    expect(subscriber.connect).toHaveBeenCalled();
  });

  it('connect() propagates connection failures', async () => {
    subscriber.connect.mockRejectedValueOnce(new Error('refused'));
    await expect(adapter.connect()).rejects.toThrow('refused');
  });

  describe('key/value commands apply the key prefix', () => {
    it('get', async () => {
      const buf = Buffer.from('v');
      client.getBuffer.mockResolvedValue(buf);
      await expect(adapter.get('k')).resolves.toBe(buf);
      expect(client.getBuffer).toHaveBeenCalledWith('pre:k');
    });

    it('set with ttl uses SETEX', async () => {
      const buf = Buffer.from('v');
      await adapter.set('k', buf, 60);
      expect(client.setex).toHaveBeenCalledWith('pre:k', 60, buf);
      expect(client.set).not.toHaveBeenCalled();
    });

    it('set without ttl uses SET', async () => {
      const buf = Buffer.from('v');
      await adapter.set('k', buf);
      expect(client.set).toHaveBeenCalledWith('pre:k', buf);
      expect(client.setex).not.toHaveBeenCalled();
    });

    it('set with ttl 0 uses SET', async () => {
      const buf = Buffer.from('v');
      await adapter.set('k', buf, 0);
      expect(client.set).toHaveBeenCalledWith('pre:k', buf);
    });

    it('del', async () => {
      await adapter.del('k');
      expect(client.del).toHaveBeenCalledWith('pre:k');
    });

    it('expire', async () => {
      await adapter.expire('k', 5);
      expect(client.expire).toHaveBeenCalledWith('pre:k', 5);
    });
  });

  describe('hash commands', () => {
    it('hset / hget / hgetall / hdel / hincrby', async () => {
      client.hget.mockResolvedValue('v');
      client.hgetall.mockResolvedValue({ a: '1' });
      client.hincrby.mockResolvedValue(7);

      await adapter.hset('h', 'f', 'v');
      await expect(adapter.hget('h', 'f')).resolves.toBe('v');
      await expect(adapter.hgetall('h')).resolves.toEqual({ a: '1' });
      await adapter.hdel('h', 'f');
      await expect(adapter.hincrby('h', 'f', 2)).resolves.toBe(7);

      expect(client.hset).toHaveBeenCalledWith('pre:h', 'f', 'v');
      expect(client.hget).toHaveBeenCalledWith('pre:h', 'f');
      expect(client.hgetall).toHaveBeenCalledWith('pre:h');
      expect(client.hdel).toHaveBeenCalledWith('pre:h', 'f');
      expect(client.hincrby).toHaveBeenCalledWith('pre:h', 'f', 2);
    });
  });

  describe('list commands', () => {
    it('lpush / lrange / ltrim / llen', async () => {
      client.lrange.mockResolvedValue(['a', 'b']);
      client.llen.mockResolvedValue(2);

      await adapter.lpush('l', 'a');
      await expect(adapter.lrange('l', 0, -1)).resolves.toEqual(['a', 'b']);
      await adapter.ltrim('l', 0, 9);
      await expect(adapter.llen('l')).resolves.toBe(2);

      expect(client.lpush).toHaveBeenCalledWith('pre:l', 'a');
      expect(client.lrange).toHaveBeenCalledWith('pre:l', 0, -1);
      expect(client.ltrim).toHaveBeenCalledWith('pre:l', 0, 9);
      expect(client.llen).toHaveBeenCalledWith('pre:l');
    });
  });

  describe('pub/sub', () => {
    it('publish uses the raw channel name on the client connection', async () => {
      await adapter.publish('chan', 'msg');
      expect(client.publish).toHaveBeenCalledWith('chan', 'msg');
    });

    it('subscribe only forwards messages for the subscribed channel', async () => {
      const cb = jest.fn();
      await adapter.subscribe('chan', cb);
      expect(subscriber.subscribe).toHaveBeenCalledWith('chan');

      subscriber.emit('message', 'other', 'nope');
      subscriber.emit('message', 'chan', 'yes');
      expect(cb).toHaveBeenCalledTimes(1);
      expect(cb).toHaveBeenCalledWith('yes');
    });
  });

  describe('ping', () => {
    it('returns true on PONG', async () => {
      client.ping.mockResolvedValue('PONG');
      await expect(adapter.ping()).resolves.toBe(true);
    });

    it('returns false on unexpected reply', async () => {
      client.ping.mockResolvedValue('NOPE');
      await expect(adapter.ping()).resolves.toBe(false);
    });

    it('returns false when the command fails', async () => {
      client.ping.mockRejectedValue(new Error('down'));
      await expect(adapter.ping()).resolves.toBe(false);
    });
  });

  it('disconnect() closes both connections and logs', () => {
    adapter.disconnect();
    expect(client.disconnect).toHaveBeenCalled();
    expect(subscriber.disconnect).toHaveBeenCalled();
    expect(logger.info).toHaveBeenCalledWith('redis_disconnected');
  });
});
