import { RedisAdapter } from '../services/redis-adapter';
import { createMockLogger } from './qa-test-helpers';

type Handler = (...args: unknown[]) => void;

const instances: Array<
  Record<string, jest.Mock> & { handlers: Record<string, Handler[]> }
> = [];

jest.mock('ioredis', () => {
  return jest.fn().mockImplementation(() => {
    const handlers: Record<string, Handler[]> = {};
    const instance: Record<string, unknown> = {
      handlers,
      connect: jest.fn().mockResolvedValue(undefined),
      getBuffer: jest.fn().mockResolvedValue(Buffer.from('v')),
      set: jest.fn().mockResolvedValue('OK'),
      setex: jest.fn().mockResolvedValue('OK'),
      del: jest.fn().mockResolvedValue(1),
      hset: jest.fn().mockResolvedValue(1),
      hget: jest.fn().mockResolvedValue('x'),
      hgetall: jest.fn().mockResolvedValue({ a: '1' }),
      hdel: jest.fn().mockResolvedValue(1),
      hincrby: jest.fn().mockResolvedValue(7),
      lpush: jest.fn().mockResolvedValue(1),
      lrange: jest.fn().mockResolvedValue(['a']),
      ltrim: jest.fn().mockResolvedValue('OK'),
      llen: jest.fn().mockResolvedValue(1),
      expire: jest.fn().mockResolvedValue(1),
      publish: jest.fn().mockResolvedValue(1),
      subscribe: jest.fn().mockResolvedValue(1),
      ping: jest.fn().mockResolvedValue('PONG'),
      disconnect: jest.fn(),
    };
    instance.on = jest.fn((event: string, cb: Handler): unknown => {
      (handlers[event] ||= []).push(cb);
      return instance;
    });
    instances.push(instance as never);
    return instance;
  });
});

describe('QA: RedisAdapter', () => {
  let adapter: RedisAdapter;
  let client: (typeof instances)[number];
  let subscriber: (typeof instances)[number];

  beforeEach(() => {
    instances.length = 0;
    adapter = new RedisAdapter(
      { host: 'h', port: 1, keyPrefix: 'collab:' },
      createMockLogger(),
    );
    [client, subscriber] = instances;
  });

  it('creates separate command and subscriber connections and connects both', async () => {
    expect(instances).toHaveLength(2);
    await adapter.connect();
    expect(client.connect).toHaveBeenCalled();
    expect(subscriber.connect).toHaveBeenCalled();
  });

  it('prefixes every key-based command', async () => {
    await adapter.get('k');
    await adapter.del('k');
    await adapter.hset('h', 'f', 'v');
    await adapter.hget('h', 'f');
    await adapter.hgetall('h');
    await adapter.hdel('h', 'f');
    await adapter.lpush('l', 'v');
    await adapter.lrange('l', 0, 1);
    await adapter.ltrim('l', 0, 1);
    await adapter.llen('l');
    await adapter.expire('k', 5);
    expect(client.getBuffer).toHaveBeenCalledWith('collab:k');
    expect(client.del).toHaveBeenCalledWith('collab:k');
    expect(client.hset).toHaveBeenCalledWith('collab:h', 'f', 'v');
    expect(client.hget).toHaveBeenCalledWith('collab:h', 'f');
    expect(client.hgetall).toHaveBeenCalledWith('collab:h');
    expect(client.hdel).toHaveBeenCalledWith('collab:h', 'f');
    expect(client.lpush).toHaveBeenCalledWith('collab:l', 'v');
    expect(client.lrange).toHaveBeenCalledWith('collab:l', 0, 1);
    expect(client.ltrim).toHaveBeenCalledWith('collab:l', 0, 1);
    expect(client.llen).toHaveBeenCalledWith('collab:l');
    expect(client.expire).toHaveBeenCalledWith('collab:k', 5);
  });

  it('uses SETEX when a TTL is supplied and SET otherwise', async () => {
    const value = Buffer.from('state');
    await adapter.set('doc', value, 60);
    await adapter.set('doc2', value);
    expect(client.setex).toHaveBeenCalledWith('collab:doc', 60, value);
    expect(client.set).toHaveBeenCalledWith('collab:doc2', value);
  });

  it('returns the hincrby result for atomic version bumps', async () => {
    await expect(adapter.hincrby('meta', 'version', 1)).resolves.toBe(7);
    expect(client.hincrby).toHaveBeenCalledWith('collab:meta', 'version', 1);
  });

  it('ping returns true on PONG and false on errors or other replies', async () => {
    await expect(adapter.ping()).resolves.toBe(true);
    client.ping.mockResolvedValueOnce('NOPE');
    await expect(adapter.ping()).resolves.toBe(false);
    client.ping.mockRejectedValueOnce(new Error('down'));
    await expect(adapter.ping()).resolves.toBe(false);
  });

  it('subscribe only forwards messages for the subscribed channel', async () => {
    const cb = jest.fn();
    await adapter.subscribe('chan-a', cb);
    expect(subscriber.subscribe).toHaveBeenCalledWith('chan-a');
    for (const handler of subscriber.handlers.message) {
      handler('chan-b', 'ignored');
      handler('chan-a', 'hello');
    }
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith('hello');
  });

  it('publish uses the raw channel name and disconnect closes both connections', async () => {
    await adapter.publish('chan', 'msg');
    expect(client.publish).toHaveBeenCalledWith('chan', 'msg');
    adapter.disconnect();
    expect(client.disconnect).toHaveBeenCalled();
    expect(subscriber.disconnect).toHaveBeenCalled();
  });

  it('logs client errors instead of throwing', () => {
    expect(() =>
      client.handlers.error.forEach((h) => h(new Error('boom'))),
    ).not.toThrow();
  });
});
