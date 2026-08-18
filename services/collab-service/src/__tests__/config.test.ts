import { loadConfig } from '../config';

describe('loadConfig', () => {
  const ORIGINAL_ENV = process.env;

  beforeEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  afterEach(() => {
    process.env = ORIGINAL_ENV;
  });

  it('falls back to documented defaults when nothing is configured', () => {
    for (const key of [
      'HTTP_PORT',
      'REDIS_HOST',
      'REDIS_PORT',
      'REDIS_PASSWORD',
      'REDIS_DB',
      'REDIS_KEY_PREFIX',
      'JWT_SECRET',
      'JWT_ISSUER',
      'CORS_ORIGINS',
      'PERSIST_INTERVAL_MS',
      'SNAPSHOT_INTERVAL_MS',
      'DOC_TTL_SECONDS',
      'SNAPSHOT_TTL_SECONDS',
      'MAX_SNAPSHOTS',
      'LOG_LEVEL',
      'OTEL_ENABLED',
      'OTEL_EXPORTER_OTLP_ENDPOINT',
      'OTEL_SERVICE_NAME',
    ]) {
      delete process.env[key];
    }

    const cfg = loadConfig();

    expect(cfg.httpPort).toBe(8084);
    expect(cfg.redis).toEqual({
      host: 'localhost',
      port: 6379,
      password: undefined,
      db: 0,
      keyPrefix: 'collab:',
    });
    expect(cfg.jwt).toEqual({
      secret: 'otterworks-dev-secret',
      issuer: 'otterworks-auth-service',
    });
    expect(cfg.cors.origins).toEqual(['http://localhost:3000', 'http://localhost:4200']);
    expect(cfg.persistence).toEqual({
      intervalMs: 30000,
      snapshotIntervalMs: 300000,
      documentTtlSeconds: 86400,
      snapshotTtlSeconds: 604800,
      maxSnapshotsPerDocument: 50,
    });
    expect(cfg.logLevel).toBe('info');
    expect(cfg.otel).toEqual({
      enabled: false,
      endpoint: 'http://localhost:4318',
      serviceName: 'collab-service',
    });
  });

  it('reads every value from the environment when it is set', () => {
    process.env.HTTP_PORT = '9100';
    process.env.REDIS_HOST = 'redis.internal';
    process.env.REDIS_PORT = '6380';
    process.env.REDIS_PASSWORD = 'hunter2';
    process.env.REDIS_DB = '3';
    process.env.REDIS_KEY_PREFIX = 'tenant-a:';
    process.env.JWT_SECRET = 'prod-secret';
    process.env.JWT_ISSUER = 'otterworks-prod';
    process.env.CORS_ORIGINS = 'https://a.test,https://b.test';
    process.env.PERSIST_INTERVAL_MS = '1000';
    process.env.SNAPSHOT_INTERVAL_MS = '2000';
    process.env.DOC_TTL_SECONDS = '60';
    process.env.SNAPSHOT_TTL_SECONDS = '120';
    process.env.MAX_SNAPSHOTS = '7';
    process.env.LOG_LEVEL = 'debug';
    process.env.OTEL_ENABLED = 'true';
    process.env.OTEL_EXPORTER_OTLP_ENDPOINT = 'http://otel:4318';
    process.env.OTEL_SERVICE_NAME = 'collab-test';

    const cfg = loadConfig();

    expect(cfg.httpPort).toBe(9100);
    expect(cfg.redis).toEqual({
      host: 'redis.internal',
      port: 6380,
      password: 'hunter2',
      db: 3,
      keyPrefix: 'tenant-a:',
    });
    expect(cfg.jwt).toEqual({ secret: 'prod-secret', issuer: 'otterworks-prod' });
    expect(cfg.cors.origins).toEqual(['https://a.test', 'https://b.test']);
    expect(cfg.persistence).toEqual({
      intervalMs: 1000,
      snapshotIntervalMs: 2000,
      documentTtlSeconds: 60,
      snapshotTtlSeconds: 120,
      maxSnapshotsPerDocument: 7,
    });
    expect(cfg.logLevel).toBe('debug');
    expect(cfg.otel).toEqual({
      enabled: true,
      endpoint: 'http://otel:4318',
      serviceName: 'collab-test',
    });
  });

  it('treats an empty redis password as unset', () => {
    process.env.REDIS_PASSWORD = '';

    expect(loadConfig().redis.password).toBeUndefined();
  });

  it('only enables otel for the exact string "true"', () => {
    process.env.OTEL_ENABLED = 'TRUE';
    expect(loadConfig().otel.enabled).toBe(false);

    process.env.OTEL_ENABLED = '1';
    expect(loadConfig().otel.enabled).toBe(false);

    process.env.OTEL_ENABLED = 'true';
    expect(loadConfig().otel.enabled).toBe(true);
  });

  it('splits a single CORS origin into a one-element list', () => {
    process.env.CORS_ORIGINS = 'https://only.test';

    expect(loadConfig().cors.origins).toEqual(['https://only.test']);
  });
});
