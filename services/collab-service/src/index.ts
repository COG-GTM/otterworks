import express from 'express';
import { createServer, type IncomingMessage } from 'http';
import { Server as SocketIOServer } from 'socket.io';
import { WebSocketServer, type WebSocket } from 'ws';
import cors from 'cors';
import helmet from 'helmet';
import pino from 'pino';
import { loadConfig } from './config';
import { MetricsCollector } from './metrics';
import {
  type AuthenticatedUser,
  createAuthMiddleware,
  extractBearerToken,
  isAdmin,
  userFromToken,
} from './middleware/auth';
import { RedisAdapter } from './services/redis-adapter';
import { DocumentStore } from './services/document-store';
import { AwarenessService } from './services/awareness';
import {
  DocumentAccessService,
  documentIdFromYjsRequestUrl,
  normalizeDocumentId,
} from './services/document-access';
import { PresenceHandler } from './handlers/presence';
import { setupCollaborationHandlers } from './handlers/collaboration';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { setupWSConnection } = require('y-websocket/bin/utils');

const config = loadConfig();

const logger = pino({
  level: config.logLevel,
  transport:
    process.env.NODE_ENV !== 'production'
      ? { target: 'pino-pretty', options: { colorize: true } }
      : undefined,
  base: { service: 'collab-service' },
});

const app = express();
const httpServer = createServer(app);
const metrics = new MetricsCollector();

// Middleware
app.use(helmet());
app.use(
  cors({
    origin: config.cors.origins,
    credentials: true,
  }),
);
app.use(express.json());

// Health check
app.get('/health', async (_req, res) => {
  const redisHealthy = await redisAdapter.ping();
  const status = redisHealthy ? 'healthy' : 'degraded';
  res.status(redisHealthy ? 200 : 503).json({
    status,
    service: 'collab-service',
    timestamp: new Date().toISOString(),
    uptime: process.uptime(),
    redis: redisHealthy ? 'connected' : 'disconnected',
    activeDocuments: collabManager?.getDocumentCount() ?? 0,
  });
});

// Prometheus metrics endpoint
app.get('/metrics', async (_req, res) => {
  try {
    const metricsOutput = await metrics.getMetrics();
    res.type(metrics.getContentType()).send(metricsOutput);
  } catch (err) {
    logger.error({ err }, 'metrics_collection_failed');
    res.status(500).send('Error collecting metrics');
  }
});

const documentAccess = new DocumentAccessService({
  baseUrl: config.documentService.url,
  timeoutMs: config.documentService.timeoutMs,
  cacheTtlMs: config.documentService.accessCacheTtlMs,
  logger,
});

function authenticateRequest(
  req: express.Request,
): { user: AuthenticatedUser; token: string } | null {
  const token = extractBearerToken(req.headers.authorization);
  if (!token) return null;
  try {
    return { user: userFromToken(token, config.jwt.secret), token };
  } catch {
    return null;
  }
}

// Presence endpoint: only callers who may open the document see who is in it
app.get('/api/v1/collab/documents/:id/presence', async (req, res) => {
  const auth = authenticateRequest(req);
  if (!auth) {
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  const documentId = normalizeDocumentId(req.params.id);
  if (!documentId) {
    res.status(400).json({ error: 'Invalid document id' });
    return;
  }
  if (!(await documentAccess.canAccess(auth.token, auth.user.userId, documentId))) {
    res.status(403).json({ error: 'Access denied' });
    return;
  }
  res.json(presenceHandler.getDocumentPresence(documentId));
});

// Active documents listing (admin only: it enumerates every open document)
app.get('/api/v1/collab/documents', (req, res) => {
  const auth = authenticateRequest(req);
  if (!auth) {
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  if (!isAdmin(auth.user)) {
    res.status(403).json({ error: 'Admin role required' });
    return;
  }
  const activeDocuments = presenceHandler.getActiveDocuments();
  res.json({ documents: activeDocuments, count: activeDocuments.length });
});

// Socket.IO server
const io = new SocketIOServer(httpServer, {
  cors: {
    origin: config.cors.origins,
    credentials: true,
  },
  pingInterval: 25000,
  pingTimeout: 20000,
});

// JWT auth middleware for WebSocket
io.use(createAuthMiddleware(config.jwt.secret, logger));

// Initialize services
const redisAdapter = new RedisAdapter(
  {
    host: config.redis.host,
    port: config.redis.port,
    password: config.redis.password,
    db: config.redis.db,
    keyPrefix: config.redis.keyPrefix,
  },
  logger,
);

const documentStore = new DocumentStore(redisAdapter, logger, {
  documentTtl: config.persistence.documentTtlSeconds,
  snapshotTtl: config.persistence.snapshotTtlSeconds,
  maxSnapshots: config.persistence.maxSnapshotsPerDocument,
});

const awareness = new AwarenessService(logger);
const presenceHandler = new PresenceHandler(awareness, logger);

// Setup collaboration handlers
const collabManager = setupCollaborationHandlers(
  io,
  documentStore,
  awareness,
  presenceHandler,
  metrics,
  logger,
  documentAccess,
  config.persistence.intervalMs,
  config.persistence.snapshotIntervalMs,
  config.documentService.accessRevalidateIntervalMs,
);

// y-websocket server for TipTap/Yjs collaborative editing
const wss = new WebSocketServer({ noServer: true });
const YJS_ACCESS_REVOKED = 4403;
const yjsAuthByRequest = new WeakMap<
  IncomingMessage,
  { token: string; userId: string; documentId: string }
>();

// Open y-websocket connections are re-authorized periodically so revoked access
// (or an expired token) does not keep a live editor attached to the document.
function watchYjsAccess(
  conn: WebSocket,
  token: string,
  userId: string,
  documentId: string,
): void {
  const intervalMs = config.documentService.accessRevalidateIntervalMs;
  if (intervalMs <= 0) return;
  const timer = setInterval(() => {
    documentAccess
      .canAccess(token, userId, documentId, { fresh: true })
      .then((allowed) => {
        if (allowed) return;
        logger.warn({ documentId, userId }, 'y-websocket_access_revoked');
        conn.close(YJS_ACCESS_REVOKED, 'Access revoked');
      })
      .catch((err) => logger.error({ err }, 'y-websocket_access_revalidation_failed'));
  }, intervalMs);
  timer.unref?.();
  conn.on('close', () => clearInterval(timer));
}

wss.on('connection', (conn: WebSocket, req: IncomingMessage) => {
  setupWSConnection(conn, req);
  const auth = yjsAuthByRequest.get(req);
  if (auth) watchYjsAccess(conn, auth.token, auth.userId, auth.documentId);
  logger.info({ url: req.url }, 'y-websocket_client_connected');
});

// Route WebSocket upgrades: Socket.IO paths go to Socket.IO, all others to y-websocket
httpServer.on('upgrade', (request, socket, head) => {
  if (request.url?.startsWith('/socket.io')) {
    // Socket.IO handles its own upgrades via its internal listener
    return;
  }

  const reject = (status: string, reason: string): void => {
    logger.warn({ reason }, 'y-websocket_connection_rejected');
    socket.write(`HTTP/1.1 ${status}\r\n\r\n`);
    socket.destroy();
  };

  // JWT authentication for y-websocket connections
  const url = new URL(request.url || '', 'http://collab-service');
  const token =
    url.searchParams.get('token') || extractBearerToken(request.headers.authorization);

  if (!token) {
    reject('401 Unauthorized', 'no token');
    return;
  }

  let user: AuthenticatedUser;
  try {
    user = userFromToken(token, config.jwt.secret);
  } catch {
    reject('401 Unauthorized', 'invalid token');
    return;
  }

  // The y-websocket room name must be `document-<uuid>` and the caller must be
  // allowed to open that document before the connection is handed off.
  const documentId = documentIdFromYjsRequestUrl(request.url);
  if (!documentId) {
    reject('400 Bad Request', 'invalid document room');
    return;
  }

  documentAccess
    .canAccess(token, user.userId, documentId)
    .then((allowed) => {
      if (!allowed) {
        reject('403 Forbidden', 'document access denied');
        return;
      }
      wss.handleUpgrade(request, socket, head, (ws) => {
        yjsAuthByRequest.set(request, { token, userId: user.userId, documentId });
        wss.emit('connection', ws, request);
      });
    })
    .catch((err) => {
      logger.error({ err }, 'y-websocket_access_check_failed');
      reject('503 Service Unavailable', 'access check failed');
    });
});

// Start presence cleanup with document eviction callback
const presenceCleanupTimer = presenceHandler.startCleanupInterval(
  io,
  60000,
  300000,
  (documentId: string) => {
    collabManager.persistAndCleanupDocument(documentId).catch((err) => {
      logger.error({ err, documentId }, 'stale_cleanup_document_eviction_failed');
    });
  },
);

// Start server
async function start(): Promise<void> {
  try {
    await redisAdapter.connect();
    logger.info('redis_connected');
  } catch (err) {
    logger.warn({ err }, 'redis_connection_failed, starting without Redis persistence');
  }

  httpServer.listen(config.httpPort, '0.0.0.0', () => {
    logger.info({ port: config.httpPort }, 'collaboration_service_started');
  });
}

// Graceful shutdown
async function shutdown(signal: string): Promise<void> {
  logger.info({ signal }, 'shutdown_initiated');

  clearInterval(presenceCleanupTimer);
  await collabManager.stop();

  httpServer.close(() => {
    redisAdapter.disconnect();
    logger.info('collaboration_service_stopped');
    process.exit(0);
  });

  // Force exit after 10 seconds
  setTimeout(() => {
    logger.error('forced_shutdown_after_timeout');
    process.exit(1);
  }, 10000);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

start().catch((err) => {
  logger.fatal({ err }, 'startup_failed');
  process.exit(1);
});
