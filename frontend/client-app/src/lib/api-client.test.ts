import axios, { type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient, refreshAccessToken } from "./api-client";
import { clearSession, getAccessToken, purgeLegacyTokenStorage, setAccessToken } from "./auth-session";

function respond(config: InternalAxiosRequestConfig, status: number, data: unknown = {}) {
  const response = { data, status, statusText: String(status), headers: {}, config };
  if (status >= 400) {
    return Promise.reject(Object.assign(new Error(`status ${status}`), { config, response }));
  }
  return Promise.resolve(response);
}

describe("api-client token handling", () => {
  const originalAdapter = apiClient.defaults.adapter;

  beforeEach(() => {
    localStorage.clear();
    clearSession();
  });

  afterEach(() => {
    apiClient.defaults.adapter = originalAdapter;
    vi.restoreAllMocks();
  });

  it("sends the in-memory access token and never writes tokens to Web Storage", async () => {
    const seen: (string | undefined)[] = [];
    apiClient.defaults.adapter = ((config) => {
      seen.push(config.headers.Authorization as string | undefined);
      return respond(config, 200);
    }) as AxiosAdapter;

    setAccessToken("access-123");
    await apiClient.get("/documents");

    expect(seen).toEqual(["Bearer access-123"]);
    expect(localStorage.length).toBe(0);
    expect(apiClient.defaults.withCredentials).toBe(true);
  });

  it("purges tokens persisted in localStorage by older builds", () => {
    localStorage.setItem("otter_access_token", "old-access");
    localStorage.setItem("otter_refresh_token", "old-refresh");

    purgeLegacyTokenStorage();

    expect(localStorage.getItem("otter_access_token")).toBeNull();
    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
  });

  it("refreshes from the HttpOnly cookie on 401 and retries once", async () => {
    const post = vi
      .spyOn(axios, "post")
      .mockResolvedValue({ data: { accessToken: "fresh-access" } });
    const seen: (string | undefined)[] = [];
    apiClient.defaults.adapter = ((config) => {
      const auth = config.headers.Authorization as string | undefined;
      seen.push(auth);
      return respond(config, auth === "Bearer fresh-access" ? 200 : 401);
    }) as AxiosAdapter;

    setAccessToken("expired-access");
    const response = await apiClient.get("/documents");

    expect(response.status).toBe(200);
    expect(seen).toEqual(["Bearer expired-access", "Bearer fresh-access"]);
    expect(post).toHaveBeenCalledWith("/api/v1/auth/refresh", null, { withCredentials: true });
    const [, body, options] = post.mock.calls[0];
    expect(body).toBeNull();
    expect(options).not.toHaveProperty("headers");
    expect(getAccessToken()).toBe("fresh-access");
    expect(localStorage.length).toBe(0);
  });

  it("clears the session when the refresh cookie is rejected", async () => {
    vi.spyOn(axios, "post").mockRejectedValue(new Error("401"));
    setAccessToken("stale");

    await expect(refreshAccessToken()).resolves.toBeNull();
    expect(getAccessToken()).toBeNull();
  });
});
