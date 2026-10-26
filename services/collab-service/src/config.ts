export interface Config {
  httpPort: number;
  redis: {
    host: string;
    port: number;
    password: string | undefined;
    db: number;
    keyPrefix: string;
  };
  jwt: {
    secret: string;
    issuer: string;
  };
  cors: {
    origins: string[];
  };
  persistence: {
    intervalMs: number;
    snapshotIntervalMs: number;
    documentTtlSeconds: number;
    snapshotTtlSeconds: number;
    maxSnapshotsPerDocument: number;
  };
  logLevel: string;
  otel: {
    enabled: boolean;
    endpoint: string;
    serviceName: string;
  };
}

export const MIN_JWT_SECRET_BYTES = 32;

// Tokens are HMAC-signed by auth-service (jjwt picks HS256/384/512 from the key length);
// pinning the family blocks alg confusion, matching the gateway's SigningMethodHMAC check.
export const JWT_ALGORITHMS: ['HS256', 'HS384', 'HS512'] = ['HS256', 'HS384', 'HS512'];

const PUBLIC_DEFAULT_JWT_SECRETS = new Set(['otterworks-dev-secret']);

// docker-compose's local-dev fallback; fine on a laptop, never in a deployed tenant.
const LOCAL_DEV_JWT_SECRETS = new Set([
  'otterworks-local-dev-jwt-secret-change-me-in-production',
]);

export function requireJwtSecret(
  value: string | undefined = process.env.JWT_SECRET,
  nodeEnv: string | undefined = process.env.NODE_ENV,
): string {
  if (!value || value.trim() === '') {
    throw new Error('JWT_SECRET environment variable is required but not set');
  }
  if (
    PUBLIC_DEFAULT_JWT_SECRETS.has(value) ||
    (nodeEnv === 'production' && LOCAL_DEV_JWT_SECRETS.has(value))
  ) {
    throw new Error(
      'JWT_SECRET is set to a publicly known default; configure a random secret',
    );
  }
  if (Buffer.byteLength(value, 'utf8') < MIN_JWT_SECRET_BYTES) {
    throw new Error(`JWT_SECRET must be at least ${MIN_JWT_SECRET_BYTES} bytes`);
  }
  return value;
}

export function loadConfig(): Config {
  return {
    httpPort: parseInt(process.env.HTTP_PORT || '8084', 10),
    redis: {
      host: process.env.REDIS_HOST || 'localhost',
      port: parseInt(process.env.REDIS_PORT || '6379', 10),
      password: process.env.REDIS_PASSWORD || undefined,
      db: parseInt(process.env.REDIS_DB || '0', 10),
      keyPrefix: process.env.REDIS_KEY_PREFIX || 'collab:',
    },
    jwt: {
      secret: requireJwtSecret(),
      issuer: process.env.JWT_ISSUER || 'otterworks-auth-service',
    },
    cors: {
      origins: (
        process.env.CORS_ORIGINS || 'http://localhost:3000,http://localhost:4200'
      ).split(','),
    },
    persistence: {
      intervalMs: parseInt(process.env.PERSIST_INTERVAL_MS || '30000', 10),
      snapshotIntervalMs: parseInt(process.env.SNAPSHOT_INTERVAL_MS || '300000', 10),
      documentTtlSeconds: parseInt(process.env.DOC_TTL_SECONDS || '86400', 10),
      snapshotTtlSeconds: parseInt(process.env.SNAPSHOT_TTL_SECONDS || '604800', 10),
      maxSnapshotsPerDocument: parseInt(process.env.MAX_SNAPSHOTS || '50', 10),
    },
    logLevel: process.env.LOG_LEVEL || 'info',
    otel: {
      enabled: process.env.OTEL_ENABLED === 'true',
      endpoint: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://localhost:4318',
      serviceName: process.env.OTEL_SERVICE_NAME || 'collab-service',
    },
  };
}
