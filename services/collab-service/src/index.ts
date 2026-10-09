import express from 'express';
import { createServer } from 'http';
import { Server as SocketIOServer } from 'socket.io';
import { WebSocketServer } from 'ws';
import jwt from 'jsonwebtoken';
import cors from 'cors';
import helmet from 'helmet';
import pino from 'pino';
import * as Y from 'yjs';
import { loadConfig } from './config';
import { MetricsCollector } from './metrics';
import { createAuthMiddleware } from './middleware/auth';
import { RedisAdapter } from './services/redis-adapter';
import { DocumentStore } from './services/document-store';
import { DocumentMemoryBudget } from './services/memory-budget';
import {
  SharedDoc,
  WsDocumentGuard,
  WS_CLOSE_MESSAGE_TOO_BIG,
} from './services/ws-doc-guard';
import { AwarenessService } from './services/awareness';
import { PresenceHandler } from './handlers/presence';
import { setupCollaborationHandlers } from './handlers/collaboration';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const {
  setupWSConnection,
  setPersistence,
  docs: wsDocs,
} = require('y-websocket/bin/utils') as {
  setupWSConnection: (conn: unknown, req: unknown, opts?: { docName?: string }) => void;
  setPersistence: (persistence: {
    provider: unknown;
    bindState: (docName: string, doc: Y.Doc) => Promise<void>;
    writeState: (docName: string, doc: Y.Doc) => Promise<void>;
  }) => void;
  docs: Map<string, SharedDoc>;
};

const config = loadConfig();
const { limits } = config;
// Socket.IO and y-websocket documents share one memory budget
const memoryBudget = new DocumentMemoryBudget(limits.maxTotalDocumentBytes);

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
  maxHttpBufferSize: limits.maxMessageBytes,
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
  maxStateBytes: limits.maxDocumentBytes,
  maxSnapshotBytes: limits.maxSnapshotBytesPerDocument,
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
  limits,
  memoryBudget,
);

// y-websocket keeps documents in memory forever unless persistence is configured.
// With it, a document is saved and freed when its last editor disconnects.
const wsStateKey = (docName: string) => `ws:${docName}`;
setPersistence({
  provider: null,
  bindState: async (docName, doc) => {
    try {
      const state = await documentStore.getDocumentState(wsStateKey(docName));
      if (state && state.length <= limits.maxDocumentBytes) Y.applyUpdate(doc, state);
    } catch (err) {
      logger.error({ err, documentName: docName }, 'y-websocket_state_load_failed');
    }
  },
  writeState: async (docName, doc) => {
    try {
      const state = Buffer.from(Y.encodeStateAsUpdate(doc));
      await documentStore.saveDocumentState(wsStateKey(docName), state);
    } catch (err) {
      // Oversized documents are rejected by the store and intentionally dropped
      logger.warn({ err, documentName: docName }, 'y-websocket_state_save_failed');
    }
  },
});

// y-websocket server for TipTap/Yjs collaborative editing
const wss = new WebSocketServer({ noServer: true, maxPayload: limits.maxMessageBytes });
const wsGuard = new WsDocumentGuard({
  docs: wsDocs,
  budget: memoryBudget,
  maxDocumentBytes: limits.maxDocumentBytes,
  maxDocuments: limits.maxDocumentsInMemory,
  logger,
});
wss.on('connection', (conn, req) => {
  const docName = (req.url || '').slice(1).split('?')[0];
  if (!docName || docName.length > 256 || !wsGuard.canOpen(docName)) {
    logger.warn({ documentName: docName }, 'y-websocket_connection_rejected: limit');
    conn.close(WS_CLOSE_MESSAGE_TOO_BIG, 'Document limit exceeded');
    return;
  }
  setupWSConnection(conn, req, { docName });
  wsGuard.attach(docName);
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

  try {
    jwt.verify(token, config.jwt.secret);
  } catch {
    logger.warn('y-websocket_connection_rejected: invalid token');
    socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
    socket.destroy();
    return;
  }

  wss.handleUpgrade(request, socket, head, (ws) => {
    wss.emit('connection', ws, request);
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
