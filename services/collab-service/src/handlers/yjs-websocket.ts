import type { IncomingMessage, Server as HttpServer } from 'http';
import type { Duplex } from 'stream';
import { WebSocketServer, type WebSocket } from 'ws';
import type { Logger } from 'pino';
import { extractBearerToken, userFromToken } from '../middleware/auth';
import {
  type DocumentAccessChecker,
  documentIdFromYjsRequestUrl,
  yjsRoomName,
} from '../services/document-access';

export const YJS_ACCESS_REVOKED = 4403;

export type SetupWSConnection = (
  conn: WebSocket,
  req: IncomingMessage,
  options: { docName: string },
) => void;

export interface YjsWebsocketOptions {
  jwtSecret: string;
  documentAccess: DocumentAccessChecker;
  setupWSConnection: SetupWSConnection;
  logger: Logger;
  revalidateIntervalMs: number;
}

interface YjsAuth {
  token: string;
  userId: string;
  documentId: string;
}

/**
 * Serves y-websocket on every non-Socket.IO upgrade. A connection is only handed
 * to y-websocket after the caller's access token is verified and document-service
 * confirms the caller may open the `document-<uuid>` room named in the URL.
 */
export function attachYjsWebsocket(
  httpServer: HttpServer,
  options: YjsWebsocketOptions,
): WebSocketServer {
  const { jwtSecret, documentAccess, setupWSConnection, logger, revalidateIntervalMs } =
    options;
  const wss = new WebSocketServer({ noServer: true });
  const authByRequest = new WeakMap<IncomingMessage, YjsAuth>();

  // Open connections are re-authorized periodically so revoked access (or an
  // expired token) does not keep a live editor attached to the document.
  function watchAccess(conn: WebSocket, auth: YjsAuth): void {
    if (revalidateIntervalMs <= 0) return;
    const timer = setInterval(() => {
      documentAccess
        .canAccess(auth.token, auth.userId, auth.documentId, { fresh: true })
        .then((allowed) => {
          if (allowed) return;
          logger.warn(
            { documentId: auth.documentId, userId: auth.userId },
            'y-websocket_access_revoked',
          );
          conn.close(YJS_ACCESS_REVOKED, 'Access revoked');
        })
        .catch((err) => logger.error({ err }, 'y-websocket_access_revalidation_failed'));
    }, revalidateIntervalMs);
    timer.unref?.();
    conn.on('close', () => clearInterval(timer));
  }

  wss.on('connection', (conn: WebSocket, req: IncomingMessage) => {
    const auth = authByRequest.get(req);
    if (!auth) {
      conn.close(YJS_ACCESS_REVOKED, 'Access denied');
      return;
    }
    // The room comes from the authorized document id, never from req.url.
    setupWSConnection(conn, req, { docName: yjsRoomName(auth.documentId) });
    watchAccess(conn, auth);
    logger.info(
      { documentId: auth.documentId, userId: auth.userId },
      'y-websocket_client_connected',
    );
  });

  httpServer.on('upgrade', (request: IncomingMessage, socket: Duplex, head: Buffer) => {
    if (request.url?.startsWith('/socket.io')) {
      // Socket.IO handles its own upgrades via its internal listener
      return;
    }

    const reject = (status: string, reason: string): void => {
      logger.warn({ reason }, 'y-websocket_connection_rejected');
      socket.write(
        `HTTP/1.1 ${status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`,
      );
      socket.destroy();
    };

    const url = new URL(request.url || '', 'http://collab-service');
    const token =
      url.searchParams.get('token') || extractBearerToken(request.headers.authorization);
    if (!token) {
      reject('401 Unauthorized', 'no token');
      return;
    }

    let userId: string;
    try {
      userId = userFromToken(token, jwtSecret).userId;
    } catch {
      reject('401 Unauthorized', 'invalid token');
      return;
    }

    const documentId = documentIdFromYjsRequestUrl(request.url);
    if (!documentId) {
      reject('400 Bad Request', 'invalid document room');
      return;
    }

    documentAccess
      .canAccess(token, userId, documentId)
      .then((allowed) => {
        if (!allowed) {
          reject('403 Forbidden', 'document access denied');
          return;
        }
        if (socket.destroyed) return;
        wss.handleUpgrade(request, socket, head, (ws) => {
          authByRequest.set(request, { token, userId, documentId });
          wss.emit('connection', ws, request);
        });
      })
      .catch((err) => {
        logger.error({ err }, 'y-websocket_access_check_failed');
        reject('503 Service Unavailable', 'access check failed');
      });
  });

  return wss;
}
