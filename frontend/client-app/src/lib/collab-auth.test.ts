import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BEARER_SUBPROTOCOL_PREFIX,
  COLLAB_SUBPROTOCOL,
  collabSubprotocols,
  collabWebSocketClass,
} from "./collab-auth";

describe("collabSubprotocols", () => {
  it("offers the app protocol and carries the token as a bearer subprotocol", () => {
    expect(collabSubprotocols("a.b.c")).toEqual([COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}a.b.c`]);
  });

  it("offers only the app protocol when there is no token", () => {
    expect(collabSubprotocols(null)).toEqual([COLLAB_SUBPROTOCOL]);
    expect(collabSubprotocols("")).toEqual([COLLAB_SUBPROTOCOL]);
  });
});

describe("collabWebSocketClass", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the socket with the bearer subprotocols and a token-free URL", () => {
    const calls: unknown[][] = [];
    class FakeWebSocket {
      constructor(...args: unknown[]) {
        calls.push(args);
      }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);

    const Ws = collabWebSocketClass("a.b.c");
    new Ws("ws://collab/document-1");

    expect(calls).toEqual([
      ["ws://collab/document-1", [COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}a.b.c`]],
    ]);
  });
});
