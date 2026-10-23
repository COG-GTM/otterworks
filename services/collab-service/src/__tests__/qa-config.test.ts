import { loadConfig } from '../config';

describe('QA: loadConfig', () => {
  const saved = { ...process.env };

  afterEach(() => {
    process.env = { ...saved };
  });

  it('uses documented defaults when env is empty', () => {
    for (const key of [
      'HTTP_PORT',
      'REDIS_HOST',
      'REDIS_PORT',
      'REDIS_DB',
      'REDIS_KEY_PREFIX',
      'REDIS_PASSWORD',
      'CORS_ORIGINS',
      'PERSIST_INTERVAL_MS',
      'MAX_SNAPSHOTS',
      'OTEL_ENABLED',
      'LOG_LEVEL',
    ]) {
      delete process.env[key];
    }
    const config = loadConfig();
    expect(config.httpPort).toBe(8084);
    expect(config.redis).toEqual({
      host: 'localhost',
      port: 6379,
      password: undefined,
      db: 0,
      keyPrefix: 'collab:',
    });
    expect(config.cors.origins).toEqual([
      'http://localhost:3000',
      'http://localhost:4200',
    ]);
    expect(config.persistence.intervalMs).toBe(30000);
    expect(config.persistence.maxSnapshotsPerDocument).toBe(50);
    expect(config.otel.enabled).toBe(false);
    expect(config.logLevel).toBe('info');
  });

  it('reads overrides from the environment', () => {
    process.env.HTTP_PORT = '9999';
    process.env.REDIS_HOST = 'redis';
    process.env.REDIS_PORT = '6380';
    process.env.REDIS_PASSWORD = 'pw';
    process.env.REDIS_DB = '3';
    process.env.CORS_ORIGINS = 'https://a.example,https://b.example';
    process.env.MAX_SNAPSHOTS = '5';
    process.env.OTEL_ENABLED = 'true';
    process.env.JWT_SECRET = 'override-secret';
    const config = loadConfig();
    expect(config.httpPort).toBe(9999);
    expect(config.redis.host).toBe('redis');
    expect(config.redis.port).toBe(6380);
    expect(config.redis.password).toBe('pw');
    expect(config.redis.db).toBe(3);
    expect(config.cors.origins).toEqual(['https://a.example', 'https://b.example']);
    expect(config.persistence.maxSnapshotsPerDocument).toBe(5);
    expect(config.otel.enabled).toBe(true);
    expect(config.jwt.secret).toBe('override-secret');
  });

  it('treats an empty REDIS_PASSWORD as no password', () => {
    process.env.REDIS_PASSWORD = '';
    expect(loadConfig().redis.password).toBeUndefined();
  });

  // Finding COLLAB-09: JWT_SECRET silently falls back to a hard-coded dev secret, so a deployment
  // that forgets to wire the secret accepts tokens forged with the public default.
  it.failing(
    'refuses to start without JWT_SECRET instead of using a hard-coded default [COLLAB-09]',
    () => {
      delete process.env.JWT_SECRET;
      expect(() => loadConfig()).toThrow();
    },
  );
});
