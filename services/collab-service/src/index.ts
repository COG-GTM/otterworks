import express from 'express';
import { createServer, type IncomingMessage } from 'http';
import type { Duplex } from 'stream';
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
import {
  DocumentAccessChecker,
  documentRoomName,
  parseDocumentRoomPath,
} from './services/document-access';
import { AwarenessService } from './services/awareness';
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

// Presence endpoint
app.get('/api/v1/collab/documents/:id/presence', (req, res) => {
  const documentId = req.params.id;
  const presence = presenceHandler.getDocumentPresence(documentId);
  res.json(presence);
});

// Active documents listing
app.get('/api/v1/collab/documents', (_req, res) => {
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
  config.persistence.intervalMs,
  config.persistence.snapshotIntervalMs,
);

// y-websocket server for TipTap/Yjs collaborative editing
const documentAccess = new DocumentAccessChecker(
  {
    documentServiceUrl: config.documentService.url,
    timeoutMs: config.documentService.accessCheckTimeoutMs,
  },
  logger,
);

// Doc names are authorized during the upgrade; never derived from req.url here.
const authorizedDocNames = new WeakMap<IncomingMessage, string>();

const wss = new WebSocketServer({ noServer: true });
wss.on('connection', (conn, req) => {
  const docName = authorizedDocNames.get(req);
  authorizedDocNames.delete(req);
  if (!docName) {
    conn.close(1008, 'Unauthorized');
    return;
  }
  setupWSConnection(conn, req, { docName });
  logger.info({ docName }, 'y-websocket_client_connected');
});

function rejectUpgrade(socket: Duplex, status: number, reason: string): void {
  socket.write(`HTTP/1.1 ${status} ${reason}\r\nConnection: close\r\n\r\n`);
  socket.destroy();
}

// Route WebSocket upgrades: Socket.IO paths go to Socket.IO, all others to y-websocket
httpServer.on('upgrade', (request, socket, head) => {
  if (request.url?.startsWith('/socket.io')) {
    // Socket.IO handles its own upgrades via its internal listener
    return;
  }

  // JWT authentication for y-websocket connections
  const url = new URL(request.url || '', 'http://collab-service.local');
  const token =
    url.searchParams.get('token') ||
    request.headers.authorization?.replace('Bearer ', '');

  if (!token) {
    logger.warn('y-websocket_connection_rejected: no token');
    rejectUpgrade(socket, 401, 'Unauthorized');
    return;
  }

  let userId: string | undefined;
  try {
    const decoded = jwt.verify(token, config.jwt.secret);
    userId = typeof decoded === 'object' ? decoded.sub : undefined;
  } catch {
    logger.warn('y-websocket_connection_rejected: invalid token');
    rejectUpgrade(socket, 401, 'Unauthorized');
    return;
  }

  if (!userId) {
    logger.warn('y-websocket_connection_rejected: token has no subject');
    rejectUpgrade(socket, 401, 'Unauthorized');
    return;
  }

  const documentId = parseDocumentRoomPath(url.pathname);
  if (!documentId) {
    logger.warn(
      { userId, path: url.pathname },
      'y-websocket_connection_rejected: invalid document path',
    );
    rejectUpgrade(socket, 404, 'Not Found');
    return;
  }

  documentAccess
    .checkAccess(documentId, token)
    .then((result) => {
      if (socket.destroyed) return;
      if (result === 'denied') {
        logger.warn(
          { userId, documentId },
          'y-websocket_connection_rejected: access denied',
        );
        rejectUpgrade(socket, 403, 'Forbidden');
        return;
      }
      if (result === 'unavailable') {
        logger.warn(
          { userId, documentId },
          'y-websocket_connection_rejected: access check unavailable',
        );
        rejectUpgrade(socket, 503, 'Service Unavailable');
        return;
      }
      authorizedDocNames.set(request, documentRoomName(documentId));
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit('connection', ws, request);
      });
    })
    .catch((err) => {
      logger.error({ err, userId, documentId }, 'y-websocket_upgrade_failed');
      if (!socket.destroyed) rejectUpgrade(socket, 500, 'Internal Server Error');
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
