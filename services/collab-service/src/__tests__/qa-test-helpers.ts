import jwt from 'jsonwebtoken';
import { RedisAdapter } from '../services/redis-adapter';

export const QA_JWT_SECRET = 'qa-test-secret-for-unit-tests';

export function signToken(
  payload: Record<string, unknown>,
  options: jwt.SignOptions = { expiresIn: '1h' },
  secret = QA_JWT_SECRET,
): string {
  return jwt.sign(payload, secret, options); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

export function createMockLogger() {
  return {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
    fatal: jest.fn(),
    trace: jest.fn(),
    child: jest.fn().mockReturnThis(),
    level: 'info',
  } as never;
}

export function createMockRedis(): jest.Mocked<RedisAdapter> {
  return {
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
}

export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
