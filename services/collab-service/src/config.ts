import type { RateLimit } from './services/rate-limiter';

export interface CollaborationLimitsConfig {
  maxMessageBytes: number;
  maxUpdateBytes: number;
  maxDocumentBytes: number;
  maxTotalDocumentBytes: number;
  maxDocumentsInMemory: number;
  maxDocumentsPerUser: number;
  maxSnapshotBytesPerDocument: number;
  persistDebounceMs: number;
  socketUpdates: RateLimit;
  userUpdates: RateLimit;
  socketSnapshots: RateLimit;
  userSnapshots: RateLimit;
  documentSnapshots: RateLimit;
  userJoins: RateLimit;
  userHistory: RateLimit;
}

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
  limits: CollaborationLimitsConfig;
  logLevel: string;
  otel: {
    enabled: boolean;
    endpoint: string;
    serviceName: string;
  };
}

function positiveInt(name: string, fallback: number): number {
  const parsed = parseInt(process.env[name] || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function rateLimit(name: string, limit: number, windowMs: number): RateLimit {
  return {
    limit: positiveInt(`${name}_LIMIT`, limit),
    windowMs: positiveInt(`${name}_WINDOW_MS`, windowMs),
  };
}

export function loadLimits(): CollaborationLimitsConfig {
  return {
    maxMessageBytes: positiveInt('MAX_MESSAGE_BYTES', 256 * 1024),
    maxUpdateBytes: positiveInt('MAX_UPDATE_BYTES', 256 * 1024),
    maxDocumentBytes: positiveInt('MAX_DOCUMENT_BYTES', 2 * 1024 * 1024),
    maxTotalDocumentBytes: positiveInt('MAX_TOTAL_DOCUMENT_BYTES', 64 * 1024 * 1024),
    maxDocumentsInMemory: positiveInt('MAX_DOCUMENTS_IN_MEMORY', 500),
    maxDocumentsPerUser: positiveInt('MAX_DOCUMENTS_PER_USER', 10),
    maxSnapshotBytesPerDocument: positiveInt(
      'MAX_SNAPSHOT_BYTES_PER_DOCUMENT',
      16 * 1024 * 1024,
    ),
    persistDebounceMs: positiveInt('PERSIST_DEBOUNCE_MS', 2000),
    socketUpdates: rateLimit('SOCKET_UPDATE_RATE', 50, 1000),
    userUpdates: rateLimit('USER_UPDATE_RATE', 100, 1000),
    socketSnapshots: rateLimit('SOCKET_SNAPSHOT_RATE', 2, 60000),
    userSnapshots: rateLimit('USER_SNAPSHOT_RATE', 5, 60000),
    documentSnapshots: rateLimit('DOCUMENT_SNAPSHOT_RATE', 10, 60000),
    userJoins: rateLimit('USER_JOIN_RATE', 30, 60000),
    userHistory: rateLimit('USER_HISTORY_RATE', 20, 60000),
  };
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
      secret: process.env.JWT_SECRET || 'otterworks-dev-secret',
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
    limits: loadLimits(),
    logLevel: process.env.LOG_LEVEL || 'info',
    otel: {
      enabled: process.env.OTEL_ENABLED === 'true',
      endpoint: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://localhost:4318',
      serviceName: process.env.OTEL_SERVICE_NAME || 'collab-service',
    },
  };
}
