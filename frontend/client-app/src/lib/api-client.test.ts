import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiClient, refreshAccessToken } from "./api-client";
import { clearLegacyTokenStorage, getAccessToken, setAccessToken } from "./auth-token";
import { billingServer as server } from "../test-setup";

const API = "http://localhost:3000/api/v1";

describe("api-client token handling", () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken(null);
  });

  afterEach(() => {
    setAccessToken(null);
  });

  it("sends the in-memory access token without persisting it to localStorage", async () => {
    let authHeader: string | null = null;
    server.use(
      http.get(`${API}/files`, ({ request }) => {
        authHeader = request.headers.get("Authorization");
        return HttpResponse.json({ files: [] });
      })
    );

    setAccessToken("access-123");
    await apiClient.get("/files");

    expect(authHeader).toBe("Bearer access-123");
    expect(localStorage.length).toBe(0);
  });

  it("refreshes via the HttpOnly cookie without an Authorization header and retries once on 401", async () => {
    let refreshAuthHeader: string | null = "unset";
    let refreshCalls = 0;
    const seenTokens: Array<string | null> = [];
    server.use(
      http.post(`${API}/auth/refresh`, ({ request }) => {
        refreshCalls += 1;
        refreshAuthHeader = request.headers.get("Authorization");
        return HttpResponse.json({ accessToken: "fresh-456", tokenType: "Bearer" });
      }),
      http.get(`${API}/documents`, ({ request }) => {
        const header = request.headers.get("Authorization");
        seenTokens.push(header);
        return header === "Bearer fresh-456"
          ? HttpResponse.json({ items: [] })
          : new HttpResponse(null, { status: 401 });
      })
    );

    setAccessToken("expired-access");
    const res = await apiClient.get("/documents");

    expect(res.status).toBe(200);
    expect(refreshCalls).toBe(1);
    expect(refreshAuthHeader).toBeNull();
    expect(seenTokens).toEqual(["Bearer expired-access", "Bearer fresh-456"]);
    expect(getAccessToken()).toBe("fresh-456");
    expect(localStorage.length).toBe(0);
  });

  it("shares a single refresh request between concurrent callers", async () => {
    let refreshCalls = 0;
    server.use(
      http.post(`${API}/auth/refresh`, () => {
        refreshCalls += 1;
        return HttpResponse.json({ accessToken: "shared-789" });
      })
    );

    const [a, b] = await Promise.all([refreshAccessToken(), refreshAccessToken()]);

    expect(a).toBe("shared-789");
    expect(b).toBe("shared-789");
    expect(refreshCalls).toBe(1);
  });

  it("clears the in-memory token when the refresh cookie is rejected", async () => {
    server.use(
      http.post(`${API}/auth/refresh`, () => new HttpResponse(null, { status: 401 }))
    );

    setAccessToken("stale");
    expect(await refreshAccessToken()).toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("removes tokens persisted by older builds", () => {
    localStorage.setItem("otter_access_token", "old-access");
    localStorage.setItem("otter_refresh_token", "old-refresh");
    localStorage.setItem("otterworks:starred", "{}");

    clearLegacyTokenStorage();

    expect(localStorage.getItem("otter_access_token")).toBeNull();
    expect(localStorage.getItem("otter_refresh_token")).toBeNull();
    expect(localStorage.getItem("otterworks:starred")).toBe("{}");
  });
});
