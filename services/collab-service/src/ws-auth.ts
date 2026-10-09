import type { IncomingHttpHeaders } from 'http';

// y-websocket clients authenticate by offering two WebSocket subprotocols:
// the app protocol below, which the server echoes back, and
// `otterworks.bearer.<JWT>`, which carries the access token and is never
// echoed. This keeps the JWT out of the request URL, which is written to
// service and ingress access logs.
export const COLLAB_SUBPROTOCOL = 'otterworks.collab.v1';
export const BEARER_SUBPROTOCOL_PREFIX = 'otterworks.bearer.';

export const LOG_REDACT_PATHS = [
  'url',
  'req.url',
  'token',
  'headers.authorization',
  'headers["sec-websocket-protocol"]',
  'req.headers.authorization',
  'req.headers["sec-websocket-protocol"]',
];

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
  const token = bearer?.slice(BEARER_SUBPROTOCOL_PREFIX.length);
  return token || null;
}

function tokenFromAuthorization(header: string | undefined): string | null {
  return header?.replace('Bearer ', '') || null;
}

function tokenFromQuery(rawUrl: string | undefined): string | null {
  if (!rawUrl) return null;
  try {
    return new URL(rawUrl, 'http://localhost').searchParams.get('token') || null;
  } catch {
    return null;
  }
}

/**
 * Returns the access token for a y-websocket upgrade request. The
 * Sec-WebSocket-Protocol and Authorization headers are preferred; the
 * `?token=` query parameter is still accepted for older clients.
 */
export function extractUpgradeToken(request: UpgradeRequest): string | null {
  return (
    tokenFromSubprotocols(request.headers['sec-websocket-protocol']) ||
    tokenFromAuthorization(request.headers.authorization) ||
    tokenFromQuery(request.url)
  );
}

/** `handleProtocols` for the ws server: echo the app protocol, never the bearer token. */
export function selectSubprotocol(protocols: Set<string>): string | false {
  return protocols.has(COLLAB_SUBPROTOCOL) ? COLLAB_SUBPROTOCOL : false;
}

/** Request path without the query string, safe to log. */
export function loggablePath(rawUrl: string | undefined): string {
  if (!rawUrl) return '/';
  try {
    return new URL(rawUrl, 'http://localhost').pathname;
  } catch {
    return rawUrl.split('?')[0] || '/';
  }
}
