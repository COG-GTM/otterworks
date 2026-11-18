import { loadConfig } from '../config';

const ENV_KEYS = [
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
];

describe('loadConfig', () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
  });

  it('returns defaults when no env vars are set', () => {
    expect(loadConfig()).toEqual({
      httpPort: 8084,
      redis: {
        host: 'localhost',
        port: 6379,
        password: undefined,
        db: 0,
        keyPrefix: 'collab:',
      },
      jwt: { secret: 'otterworks-dev-secret', issuer: 'otterworks-auth-service' },
      cors: { origins: ['http://localhost:3000', 'http://localhost:4200'] },
      persistence: {
        intervalMs: 30000,
        snapshotIntervalMs: 300000,
        documentTtlSeconds: 86400,
        snapshotTtlSeconds: 604800,
        maxSnapshotsPerDocument: 50,
      },
      logLevel: 'info',
      otel: {
        enabled: false,
        endpoint: 'http://localhost:4318',
        serviceName: 'collab-service',
      },
    });
  });

  it('reads overrides from the environment', () => {
    Object.assign(process.env, {
      HTTP_PORT: '9000',
      REDIS_HOST: 'redis.internal',
      REDIS_PORT: '6380',
      REDIS_PASSWORD: 'pw',
      REDIS_DB: '2',
      REDIS_KEY_PREFIX: 't1:',
      JWT_SECRET: 's3cret',
      JWT_ISSUER: 'issuer-x',
      CORS_ORIGINS: 'https://a.example,https://b.example',
      PERSIST_INTERVAL_MS: '1000',
      SNAPSHOT_INTERVAL_MS: '2000',
      DOC_TTL_SECONDS: '10',
      SNAPSHOT_TTL_SECONDS: '20',
      MAX_SNAPSHOTS: '5',
      LOG_LEVEL: 'debug',
      OTEL_ENABLED: 'true',
      OTEL_EXPORTER_OTLP_ENDPOINT: 'http://otel:4318',
      OTEL_SERVICE_NAME: 'collab-x',
    });

    const config = loadConfig();
    expect(config.httpPort).toBe(9000);
    expect(config.redis).toEqual({
      host: 'redis.internal',
      port: 6380,
      password: 'pw',
      db: 2,
      keyPrefix: 't1:',
    });
    expect(config.jwt).toEqual({ secret: 's3cret', issuer: 'issuer-x' });
    expect(config.cors.origins).toEqual(['https://a.example', 'https://b.example']);
    expect(config.persistence).toEqual({
      intervalMs: 1000,
      snapshotIntervalMs: 2000,
      documentTtlSeconds: 10,
      snapshotTtlSeconds: 20,
      maxSnapshotsPerDocument: 5,
    });
    expect(config.logLevel).toBe('debug');
    expect(config.otel).toEqual({
      enabled: true,
      endpoint: 'http://otel:4318',
      serviceName: 'collab-x',
    });
  });

  it('treats an empty REDIS_PASSWORD as unset and OTEL_ENABLED other than "true" as disabled', () => {
    process.env.REDIS_PASSWORD = '';
    process.env.OTEL_ENABLED = '1';
    const config = loadConfig();
    expect(config.redis.password).toBeUndefined();
    expect(config.otel.enabled).toBe(false);
  });
});
