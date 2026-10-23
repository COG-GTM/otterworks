import type { IncomingHttpHeaders, IncomingMessage } from 'http';
import type { Duplex } from 'stream';
import jwt from 'jsonwebtoken';
import type { Logger } from 'pino';
import type { WebSocketServer } from 'ws';

// y-websocket clients authenticate by offering two WebSocket subprotocols:
// the app protocol below, which the server echoes back, and
// `otterworks.bearer.<JWT>`, which carries the access token and is never
// echoed. Browsers cannot set an Authorization header on a WebSocket, and a
// `?token=` query parameter ends up in service, gateway and proxy access logs.
export const COLLAB_SUBPROTOCOL = 'otterworks.collab.v1';
export const BEARER_SUBPROTOCOL_PREFIX = 'otterworks.bearer.';

const URL_CREDENTIAL_PARAMS = ['token', 'access_token', 'jwt'];
const HMAC_ALGORITHMS: jwt.Algorithm[] = ['HS256', 'HS384', 'HS512'];

export const LOG_REDACT_PATHS = [
  'url',
  'token',
  'headers.authorization',
  'headers["sec-websocket-protocol"]',
  'req.url',
  'req.headers.authorization',
  'req.headers["sec-websocket-protocol"]',
];

export interface AccessTokenClaims extends jwt.JwtPayload {
  sub: string;
  type: 'access';
  email?: string;
  name?: string;
  display_name?: string;
  roles?: string[];
}

export class TokenRejectedError extends Error {}

/**
 * Verifies an auth-service access token. Refresh tokens (`type: "refresh"`,
 * 30-day lifetime) and tokens without a type are rejected.
 */
export function verifyAccessToken(token: string, secret: string): AccessTokenClaims {
  const decoded = jwt.verify(token, secret, { algorithms: HMAC_ALGORITHMS });
  if (typeof decoded === 'string' || decoded.type !== 'access') {
    throw new TokenRejectedError('not an access token');
  }
  if (typeof decoded.sub !== 'string' || decoded.sub.length === 0) {
    throw new TokenRejectedError('token has no subject');
  }
  return decoded as AccessTokenClaims;
}

interface UpgradeRequest {
  url?: string;
  headers: IncomingHttpHeaders;
}

export function parseSubprotocols(header: string | string[] | undefined): string[] {
  if (!header) return [];
  const values = Array.isArray(header) ? header : [header];
  return values
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

function parseUrl(rawUrl: string | undefined): URL | null {
  try {
    return new URL(rawUrl || '/', 'http://localhost');
  } catch {
    return null;
  }
}

/** True when the request URL carries a credential in its query string. */
export function hasUrlCredential(rawUrl: string | undefined): boolean {
  const url = parseUrl(rawUrl);
  if (!url) return false;
  return URL_CREDENTIAL_PARAMS.some((name) => url.searchParams.has(name));
}

/**
 * Returns the access token for a y-websocket upgrade request from the
 * Sec-WebSocket-Protocol or Authorization header. The URL is never consulted.
 */
export function extractUpgradeToken(request: UpgradeRequest): string | null {
  return (
    tokenFromSubprotocols(request.headers['sec-websocket-protocol']) ||
    tokenFromAuthorization(request.headers.authorization)
  );
}

export type UpgradeAuthResult =
  | { ok: true; claims: AccessTokenClaims }
  | { ok: false; reason: 'token_in_url' | 'no_token' | 'invalid_token' };

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
    return { ok: true, claims: verifyAccessToken(token, secret) };
  } catch {
    return { ok: false, reason: 'invalid_token' };
  }
}

/** `handleProtocols` for the ws server: echo the app protocol, never the bearer token. */
export function selectSubprotocol(protocols: Set<string>): string | false {
  return protocols.has(COLLAB_SUBPROTOCOL) ? COLLAB_SUBPROTOCOL : false;
}

/** Request path without the query string, safe to log. */
export function loggablePath(rawUrl: string | undefined): string {
  return parseUrl(rawUrl)?.pathname ?? '/';
}

/**
 * HTTP `upgrade` listener for y-websocket: authenticates the request and hands
 * it to `wss`, or answers 401. Socket.IO paths are left to Socket.IO.
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
