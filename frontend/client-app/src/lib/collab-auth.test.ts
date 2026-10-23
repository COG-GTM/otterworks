import { describe, it, expect } from "vitest";
import { collabSubprotocols, collabWebSocketClass } from "./collab-auth";

describe("collab websocket auth", () => {
  it("offers the app protocol and the bearer token as subprotocols", () => {
    expect(collabSubprotocols("abc.def.ghi")).toEqual([
      "otterworks.collab.v1",
      "otterworks.bearer.abc.def.ghi",
    ]);
  });

  it("offers only the app protocol without a token", () => {
    expect(collabSubprotocols(null)).toEqual(["otterworks.collab.v1"]);
  });

  it("opens the socket with the subprotocols and a token-free URL", () => {
    const calls: Array<[string | URL, string | string[] | undefined]> = [];
    class FakeWebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        calls.push([url, protocols]);
      }
    }
    const Ws = collabWebSocketClass("abc.def.ghi", FakeWebSocket as unknown as typeof WebSocket);
    new Ws("ws://collab.test/document-1");
    expect(calls).toEqual([
      ["ws://collab.test/document-1", ["otterworks.collab.v1", "otterworks.bearer.abc.def.ghi"]],
    ]);
  });
});
