import type { IncomingHttpHeaders, IncomingMessage } from 'http';
import type { Duplex } from 'stream';
import jwt from 'jsonwebtoken';
import type { Logger } from 'pino';
import type { WebSocketServer } from 'ws';

// y-websocket clients authenticate with an `Authorization: Bearer` header or, for
// browsers (which cannot set headers on a WebSocket), by offering the subprotocols
// `otterworks.collab.v1, otterworks.bearer.<JWT>`. Credentials in the URL query
// string are refused: URLs end up in access logs, browser history and Referer.
export const COLLAB_SUBPROTOCOL = 'otterworks.collab.v1';
export const BEARER_SUBPROTOCOL_PREFIX = 'otterworks.bearer.';

const URL_CREDENTIAL_PARAMS = ['token', 'access_token', 'jwt', 'auth', 'authorization'];

export type UpgradeAuthResult =
  | { ok: true; claims: jwt.JwtPayload | string }
  | { ok: false; reason: 'token_in_url' | 'no_token' | 'invalid_token' };

interface UpgradeRequest {
  url?: string;
  headers: IncomingHttpHeaders;
}

function parseUrl(rawUrl: string | undefined): URL | null {
  try {
    return new URL(rawUrl || '/', 'http://localhost');
  } catch {
    return null;
  }
}

/** Request path without the query string, safe to log. */
export function loggablePath(rawUrl: string | undefined): string {
  return parseUrl(rawUrl)?.pathname ?? '/';
}

export function hasUrlCredential(rawUrl: string | undefined): boolean {
  const url = parseUrl(rawUrl);
  if (!url) return false;
  return Array.from(url.searchParams.keys()).some((name) =>
    URL_CREDENTIAL_PARAMS.includes(name.toLowerCase()),
  );
}

export function parseSubprotocols(header: string | string[] | undefined): string[] {
  if (!header) return [];
  return (Array.isArray(header) ? header : [header])
    .flatMap((value) => value.split(','))
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}

function tokenFromSubprotocols(header: string | string[] | undefined): string | null {
  const bearer = parseSubprotocols(header).find((protocol) =>
    protocol.startsWith(BEARER_SUBPROTOCOL_PREFIX),
  );
  return bearer?.slice(BEARER_SUBPROTOCOL_PREFIX.length) || null;
}

function tokenFromAuthorization(header: string | undefined): string | null {
  const match = header?.match(/^Bearer\s+(\S+)$/i);
  return match ? match[1] : null;
}

/** Access token from the Authorization or Sec-WebSocket-Protocol header; never the URL. */
export function extractUpgradeToken(request: UpgradeRequest): string | null {
  return (
    tokenFromAuthorization(request.headers.authorization) ||
    tokenFromSubprotocols(request.headers['sec-websocket-protocol'])
  );
}

export function authenticateUpgrade(
  request: UpgradeRequest,
  secret: string,
): UpgradeAuthResult {
  if (hasUrlCredential(request.url)) {
    return { ok: false, reason: 'token_in_url' };
  }
  const token = extractUpgradeToken(request);
  if (!token) {
    return { ok: false, reason: 'no_token' };
  }
  try {
    return { ok: true, claims: jwt.verify(token, secret) };
  } catch {
    return { ok: false, reason: 'invalid_token' };
  }
}

/** `handleProtocols` for the ws server: echo the app protocol, never the bearer token. */
export function selectSubprotocol(protocols: Set<string>): string | false {
  return protocols.has(COLLAB_SUBPROTOCOL) ? COLLAB_SUBPROTOCOL : false;
}

/**
 * HTTP `upgrade` listener for y-websocket: authenticates the request and hands it
 * to `wss`, or answers 401. Socket.IO paths are left to Socket.IO.
 */
export function createYWebsocketUpgradeHandler(
  wss: WebSocketServer,
  secret: string,
  logger: Logger,
) {
  return (request: IncomingMessage, socket: Duplex, head: Buffer): void => {
    if (request.url?.startsWith('/socket.io')) {
      return;
    }

    const auth = authenticateUpgrade(request, secret);
    if (!auth.ok) {
      logger.warn(
        { path: loggablePath(request.url), reason: auth.reason },
        'y-websocket_connection_rejected',
      );
      socket.write('HTTP/1.1 401 Unauthorized\r\n\r\n');
      socket.destroy();
      return;
    }

    wss.handleUpgrade(request, socket, head, (ws) => {
      wss.emit('connection', ws, request);
    });
  };
}
