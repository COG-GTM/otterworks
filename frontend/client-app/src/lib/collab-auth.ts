// Must match COLLAB_SUBPROTOCOL / BEARER_SUBPROTOCOL_PREFIX in
// services/collab-service/src/ws-auth.ts.
export const COLLAB_SUBPROTOCOL = "otterworks.collab.v1";
export const BEARER_SUBPROTOCOL_PREFIX = "otterworks.bearer.";

// Browsers can't set an Authorization header on a WebSocket, and collab-service
// refuses tokens in the URL, so the access token travels in Sec-WebSocket-Protocol.
export function collabSubprotocols(token: string | null): string[] {
  return token ? [COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}${token}`] : [COLLAB_SUBPROTOCOL];
}

// Passed to y-websocket as WebSocketPolyfill so the subprotocols are always offered,
// whether or not the provider forwards its own `protocols` option.
export function collabWebSocketClass(
  token: string | null,
  Base: typeof WebSocket = WebSocket,
): typeof WebSocket {
  const protocols = collabSubprotocols(token);
  return class CollabWebSocket extends Base {
    constructor(url: string | URL) {
      super(url, protocols);
    }
  };
}
