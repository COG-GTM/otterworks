import { afterEach, describe, expect, it } from "vitest";
import { csrfRejection } from "@/lib/csrf";

const DASHBOARD = "https://ops.otterworks.app";
const TENANT = "https://t-attacker.demo.otterworks.app";

function req(method: string, headers: Record<string, string> = {}) {
  return { method, headers: new Headers({ host: "ops.otterworks.app", ...headers }) };
}

const browserSameOrigin = {
  origin: DASHBOARD,
  "sec-fetch-site": "same-origin",
  "content-type": "application/json",
};

afterEach(() => {
  delete process.env.DASHBOARD_ORIGIN;
});

describe("csrfRejection", () => {
  it("lets safe methods through regardless of headers", () => {
    for (const m of ["GET", "HEAD", "OPTIONS"]) {
      expect(csrfRejection(req(m, { origin: TENANT, "sec-fetch-site": "same-site" }))).toBeNull();
    }
  });

  it("accepts the dashboard's own same-origin JSON requests", () => {
    for (const m of ["POST", "PUT", "DELETE"]) {
      expect(csrfRejection(req(m, browserSameOrigin))).toBeNull();
    }
  });

  it("refuses a same-site tenant page (the reported attack)", () => {
    const r = csrfRejection(
      req("POST", { origin: TENANT, "sec-fetch-site": "same-site", "content-type": "text/plain;charset=UTF-8" }),
    );
    expect(r?.status).toBe(403);
  });

  it("refuses a foreign Origin even without Sec-Fetch-Site", () => {
    expect(csrfRejection(req("POST", { origin: TENANT, "content-type": "application/json" }))?.status).toBe(403);
    expect(
      csrfRejection(req("POST", { origin: "https://t-main.otterworks.app", "content-type": "application/json" }))
        ?.status,
    ).toBe(403);
  });

  it("refuses the opaque null origin", () => {
    expect(csrfRejection(req("POST", { origin: "null", "content-type": "application/json" }))?.status).toBe(403);
  });

  it("refuses Sec-Fetch-Site other than same-origin", () => {
    for (const site of ["same-site", "cross-site", "none"]) {
      expect(
        csrfRejection(req("POST", { ...browserSameOrigin, "sec-fetch-site": site }))?.status,
      ).toBe(403);
    }
  });

  it("refuses non-JSON bodies (simple-CORS / form / no-cors)", () => {
    for (const ct of ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"]) {
      expect(csrfRejection(req("POST", { ...browserSameOrigin, "content-type": ct }))?.status).toBe(415);
    }
  });

  it("refuses a bodyless POST with no Content-Type", () => {
    expect(csrfRejection(req("POST", { origin: DASHBOARD, "sec-fetch-site": "same-origin" }))?.status).toBe(415);
  });

  it("accepts JSON with parameters", () => {
    expect(
      csrfRejection(req("POST", { ...browserSameOrigin, "content-type": "application/json; charset=utf-8" })),
    ).toBeNull();
  });

  it("accepts non-browser clients that send JSON (scripts/tenant.sh)", () => {
    expect(csrfRejection(req("POST", { "content-type": "application/json" }))).toBeNull();
  });

  it("pins allowed origins to DASHBOARD_ORIGIN when set", () => {
    process.env.DASHBOARD_ORIGIN = "https://ops.otterworks.app/, http://localhost:3000";
    expect(csrfRejection(req("POST", browserSameOrigin))).toBeNull();
    expect(
      csrfRejection(req("POST", { ...browserSameOrigin, origin: "http://localhost:3000" })),
    ).toBeNull();
    // Host alone no longer decides: a matching Host with an unlisted origin is refused.
    expect(
      csrfRejection({
        method: "POST",
        headers: new Headers({ ...browserSameOrigin, host: "evil.example", origin: "https://evil.example" }),
      })?.status,
    ).toBe(403);
  });
});
