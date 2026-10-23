// Must match COLLAB_SUBPROTOCOL / BEARER_SUBPROTOCOL_PREFIX in
// services/collab-service/src/ws-auth.ts.
export const COLLAB_SUBPROTOCOL = "otterworks.collab.v1";
export const BEARER_SUBPROTOCOL_PREFIX = "otterworks.bearer.";

// The access token travels in Sec-WebSocket-Protocol rather than the URL so it
// never lands in collab-service, gateway or proxy access logs.
export function collabSubprotocols(token: string | null): string[] {
  return token ? [COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}${token}`] : [COLLAB_SUBPROTOCOL];
}

// Passed to y-websocket as WebSocketPolyfill so the subprotocols are always
// offered, independent of whether the provider forwards a `protocols` option.
export function collabWebSocketClass(token: string | null): typeof WebSocket {
  const protocols = collabSubprotocols(token);
  return class CollabWebSocket extends WebSocket {
    constructor(url: string | URL) {
      super(url, protocols);
    }
  };
}
