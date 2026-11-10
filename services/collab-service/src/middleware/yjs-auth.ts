import type { IncomingMessage } from 'http';
import jwt from 'jsonwebtoken';
import type { Logger } from 'pino';
import type { DocumentPermissionChecker } from '../services/document-permissions';

const YJS_ROOM_PATTERN = /^document-(.+)$/;

export type YjsUpgradeDecision =
  | { allowed: true; documentId: string; userId: string }
  | { allowed: false; status: 401 | 403 };

/** Extracts the document id from a y-websocket room path (`/document-<id>`). */
export function parseYjsDocumentId(requestUrl: string | undefined): string | null {
  // y-websocket derives the room name the same way: the path without its leading slash.
  const roomName = (requestUrl || '').slice(1).split('?')[0];
  const match = YJS_ROOM_PATTERN.exec(roomName);
  return match ? match[1] : null;
}

/**
 * Authenticates a y-websocket upgrade and requires write access to the room's
 * document: y-websocket lets every connected client apply updates, so read-only
 * access is not enough.
 */
export async function authorizeYjsUpgrade(
  request: IncomingMessage,
  jwtSecret: string,
  permissions: DocumentPermissionChecker,
  logger: Logger,
): Promise<YjsUpgradeDecision> {
  const url = new URL(request.url || '', 'http://localhost');
  const token =
    url.searchParams.get('token') ||
    request.headers.authorization?.replace('Bearer ', '');

  if (!token) {
    logger.warn('y-websocket_connection_rejected: no token');
    return { allowed: false, status: 401 };
  }

  let userId: string;
  try {
    const decoded = jwt.verify(token, jwtSecret) as jwt.JwtPayload;
    if (typeof decoded.sub !== 'string' || decoded.sub.length === 0) {
      throw new Error('missing sub');
    }
    userId = decoded.sub;
  } catch {
    logger.warn('y-websocket_connection_rejected: invalid token');
    return { allowed: false, status: 401 };
  }

  const documentId = parseYjsDocumentId(request.url);
  if (!documentId) {
    logger.warn({ userId }, 'y-websocket_connection_rejected: unknown room');
    return { allowed: false, status: 403 };
  }

  let access;
  try {
    access = await permissions.checkAccess({ documentId, userId, token });
  } catch (err) {
    logger.error({ err, documentId }, 'y-websocket_access_check_failed');
    access = 'none';
  }
  if (access !== 'write') {
    logger.warn({ documentId, userId }, 'y-websocket_connection_rejected: access denied');
    return { allowed: false, status: 403 };
  }

  return { allowed: true, documentId, userId };
}
