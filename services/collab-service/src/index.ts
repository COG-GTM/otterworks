import express from 'express';
import { createServer } from 'http';
import { Server as SocketIOServer } from 'socket.io';
import { WebSocketServer } from 'ws';
import jwt from 'jsonwebtoken';
import cors from 'cors';
import helmet from 'helmet';
import pino from 'pino';
import { loadConfig } from './config';
import { MetricsCollector } from './metrics';
import { createAuthMiddleware } from './middleware/auth';
import { RedisAdapter } from './services/redis-adapter';
import { DocumentStore } from './services/document-store';
import { AwarenessService } from './services/awareness';
import { HttpDocumentAccessChecker, isValidDocumentId } from './services/document-access';
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
const accessChecker = new HttpDocumentAccessChecker(
  config.documentService.url,
  logger,
  config.documentService.timeoutMs,
);

interface HttpAuthLocals {
  userId: string;
  roles: string[];
  token: string;
}

function requireHttpAuth(
  req: express.Request,
  res: express.Response,
  next: express.NextFunction,
): void {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) {
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  try {
    const decoded = jwt.verify(token, config.jwt.secret) as jwt.JwtPayload;
    if (!decoded.sub) throw new Error('missing sub');
    res.locals.auth = {
      userId: decoded.sub,
      roles: Array.isArray(decoded.roles) ? decoded.roles : [],
      token,
    } satisfies HttpAuthLocals;
    next();
  } catch {
    res.status(401).json({ error: 'Invalid or expired token' });
  }
}

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

// Presence endpoint
app.get('/api/v1/collab/documents/:id/presence', requireHttpAuth, async (req, res) => {
  const documentId = req.params.id;
  const auth = res.locals.auth as HttpAuthLocals;
  if (!(await accessChecker.canAccess(documentId, auth.userId, auth.token))) {
    res.status(404).json({ error: 'Document not found' });
    return;
  }
  const presence = presenceHandler.getDocumentPresence(documentId);
  res.json(presence);
});

// Active documents listing
// Admins see every active document; other users only see documents they are in.
app.get('/api/v1/collab/documents', requireHttpAuth, (_req, res) => {
  const auth = res.locals.auth as HttpAuthLocals;
  const isAdmin = auth.roles.some((role) => role.toLowerCase() === 'admin');
  const activeDocuments = presenceHandler
    .getActiveDocuments()
    .filter(
      ({ documentId }) =>
        isAdmin ||
        presenceHandler
          .getDocumentPresence(documentId)
          .users.some((u) => u.userId === auth.userId),
    );
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
  accessChecker,
  metrics,
  logger,
  config.persistence.intervalMs,
  config.persistence.snapshotIntervalMs,
);

// y-websocket server for TipTap/Yjs collaborative editing
const wss = new WebSocketServer({ noServer: true });
wss.on('connection', (conn, req) => {
  setupWSConnection(conn, req);
  logger.info({ url: req.url }, 'y-websocket_client_connected');
});

// Route WebSocket upgrades: Socket.IO paths go to Socket.IO, all others to y-websocket
httpServer.on('upgrade', (request, socket, head) => {
  if (request.url?.startsWith('/socket.io')) {
    // Socket.IO handles its own upgrades via its internal listener
    return;
  }

  // JWT authentication for y-websocket connections
  const url = new URL(request.url || '', `http://${request.headers.host}`);
  const token =
    url.searchParams.get('token') ||
    request.headers.authorization?.replace('Bearer ', '');

  if (!token) {
    logger.warn('y-websocket_connection_rejected: no token');
    socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
    socket.destroy();
    return;
  }

  let userId: string;
  try {
    const decoded = jwt.verify(token, config.jwt.secret) as jwt.JwtPayload;
    if (!decoded.sub) throw new Error('missing sub');
    userId = decoded.sub;
  } catch {
    logger.warn('y-websocket_connection_rejected: invalid token');
    socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
    socket.destroy();
    return;
  }

  // Must match how y-websocket derives the room name from the request URL.
  const docName = (request.url || '').slice(1).split('?')[0];
  const documentId = docName.startsWith('document-')
    ? docName.slice('document-'.length)
    : '';
  if (!isValidDocumentId(documentId)) {
    logger.warn({ docName }, 'y-websocket_connection_rejected: invalid document');
    socket.write('HTTP/1.1 404 Not Found\r\n\r\n');
    socket.destroy();
    return;
  }

  accessChecker
    .canAccess(documentId, userId, token)
    .then((allowed) => {
      if (!allowed) {
        logger.warn(
          { documentId, userId },
          'y-websocket_connection_rejected: access denied',
        );
        socket.write('HTTP/1.1 403 Forbidden\r\n\r\n');
        socket.destroy();
        return;
      }
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    })
    .catch((err) => {
      logger.error({ err, documentId }, 'y-websocket_access_check_failed');
      socket.destroy();
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
