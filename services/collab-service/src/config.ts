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
  limits: CollabLimits;
  logLevel: string;
  otel: {
    enabled: boolean;
    endpoint: string;
    serviceName: string;
  };
}

export interface CollabLimits {
  /** Max size of a single WebSocket / Socket.IO message. */
  maxMessageBytes: number;
  /** Max encoded Yjs state size of a single document. */
  maxDocumentBytes: number;
  /** Max distinct documents one user may hold open at a time (per transport). */
  maxDocumentsPerUser: number;
  /** Min delay between full-state Redis writes triggered by document updates. */
  persistDebounceMs: number;
  /** Min delay between client-requested snapshots of the same document. */
  snapshotMinIntervalMs: number;
  /** How long a y-websocket document with no connections stays in memory. */
  idleDocumentEvictMs: number;
}

export const DEFAULT_LIMITS: CollabLimits = {
  maxMessageBytes: 1024 * 1024,
  maxDocumentBytes: 1024 * 1024,
  maxDocumentsPerUser: 10,
  persistDebounceMs: 2000,
  snapshotMinIntervalMs: 30000,
  idleDocumentEvictMs: 300000,
};

function intFromEnv(name: string, fallback: number): number {
  const parsed = parseInt(process.env[name] || '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
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
    limits: {
      maxMessageBytes: intFromEnv('MAX_MESSAGE_BYTES', DEFAULT_LIMITS.maxMessageBytes),
      maxDocumentBytes: intFromEnv('MAX_DOCUMENT_BYTES', DEFAULT_LIMITS.maxDocumentBytes),
      maxDocumentsPerUser: intFromEnv(
        'MAX_DOCUMENTS_PER_USER',
        DEFAULT_LIMITS.maxDocumentsPerUser,
      ),
      persistDebounceMs: intFromEnv(
        'PERSIST_DEBOUNCE_MS',
        DEFAULT_LIMITS.persistDebounceMs,
      ),
      snapshotMinIntervalMs: intFromEnv(
        'SNAPSHOT_MIN_INTERVAL_MS',
        DEFAULT_LIMITS.snapshotMinIntervalMs,
      ),
      idleDocumentEvictMs: intFromEnv(
        'IDLE_DOCUMENT_EVICT_MS',
        DEFAULT_LIMITS.idleDocumentEvictMs,
      ),
    },
    logLevel: process.env.LOG_LEVEL || 'info',
    otel: {
      enabled: process.env.OTEL_ENABLED === 'true',
      endpoint: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || 'http://localhost:4318',
      serviceName: process.env.OTEL_SERVICE_NAME || 'collab-service',
    },
  };
}
