// Must match COLLAB_SUBPROTOCOL / BEARER_SUBPROTOCOL_PREFIX in
// services/collab-service/src/ws-auth.ts.
export const COLLAB_SUBPROTOCOL = "otterworks.collab.v1";
export const BEARER_SUBPROTOCOL_PREFIX = "otterworks.bearer.";

// The access token travels in Sec-WebSocket-Protocol rather than the URL so it
// never lands in collab-service or ingress access logs.
export function collabSubprotocols(token: string | null): string[] {
  return token ? [COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}${token}`] : [COLLAB_SUBPROTOCOL];
}
