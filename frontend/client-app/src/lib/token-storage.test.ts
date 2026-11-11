import { beforeEach, describe, expect, it } from "vitest";
import {
  clearSession,
  getAccessToken,
  purgeLegacyRefreshToken,
  storeSession,
} from "./token-storage";

describe("token-storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists only the access token, never the refresh token", () => {
    storeSession({ accessToken: "access-123", refreshToken: "refresh-456" } as never);

    expect(getAccessToken()).toBe("access-123");
    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
    expect(JSON.stringify({ ...localStorage })).not.toContain("refresh-456");
  });

  it("purges a refresh token left by older builds when storing a session", () => {
    localStorage.setItem("otter_refresh_token", "stale-refresh");

    storeSession({ accessToken: "access-123" });

    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
  });

  it("purgeLegacyRefreshToken removes a leftover refresh token and keeps the access token", () => {
    localStorage.setItem("otter_access_token", "access-123");
    localStorage.setItem("otter_refresh_token", "stale-refresh");

    purgeLegacyRefreshToken();

    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
    expect(getAccessToken()).toBe("access-123");
  });

  it("clearSession removes both keys", () => {
    localStorage.setItem("otter_access_token", "access-123");
    localStorage.setItem("otter_refresh_token", "stale-refresh");

    clearSession();

    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
  });
});
