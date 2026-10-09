import { beforeEach, describe, expect, it } from "vitest";
import {
  ACCESS_TOKEN_KEY,
  LEGACY_REFRESH_TOKEN_KEY,
  clearSession,
  getAccessToken,
  purgeLegacyRefreshToken,
  storeSession,
} from "./auth-tokens";

describe("auth token storage", () => {
  beforeEach(() => localStorage.clear());

  it("persists only the access token", () => {
    storeSession({ accessToken: "access-1", refreshToken: "refresh-1" } as never);
    expect(getAccessToken()).toBe("access-1");
    expect(localStorage.getItem(LEGACY_REFRESH_TOKEN_KEY)).toBeNull();
    expect(Object.values({ ...localStorage })).not.toContain("refresh-1");
  });

  it("drops a refresh token left by an older build when a session is stored", () => {
    localStorage.setItem(LEGACY_REFRESH_TOKEN_KEY, "old-refresh");
    storeSession({ accessToken: "access-2" });
    expect(localStorage.getItem(LEGACY_REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("purges a leftover refresh token without touching the access token", () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, "access-3");
    localStorage.setItem(LEGACY_REFRESH_TOKEN_KEY, "old-refresh");
    purgeLegacyRefreshToken();
    expect(getAccessToken()).toBe("access-3");
    expect(localStorage.getItem(LEGACY_REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("clears both keys on logout", () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, "access-4");
    localStorage.setItem(LEGACY_REFRESH_TOKEN_KEY, "old-refresh");
    clearSession();
    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem(LEGACY_REFRESH_TOKEN_KEY)).toBeNull();
  });
});
