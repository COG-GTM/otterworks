import { describe, expect, it } from "vitest";
import { BEARER_SUBPROTOCOL_PREFIX, COLLAB_SUBPROTOCOL, collabSubprotocols } from "./collab-auth";

describe("collabSubprotocols", () => {
  it("offers the app protocol and carries the token as a bearer subprotocol", () => {
    expect(collabSubprotocols("a.b.c")).toEqual([COLLAB_SUBPROTOCOL, `${BEARER_SUBPROTOCOL_PREFIX}a.b.c`]);
  });

  it("offers only the app protocol when there is no token", () => {
    expect(collabSubprotocols(null)).toEqual([COLLAB_SUBPROTOCOL]);
    expect(collabSubprotocols("")).toEqual([COLLAB_SUBPROTOCOL]);
  });
});
