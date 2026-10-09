// Run with: npm test  (Node >= 22.6, for --experimental-strip-types)
import { test } from "node:test";
import assert from "node:assert/strict";
import { crossSiteRejection, parseAllowedOrigins } from "./csrf.ts";

const DASHBOARD = "https://ops.otterworks.app";
const allowed = parseAllowedOrigins(DASHBOARD);

function headers(values) {
  const h = new Headers();
  for (const [k, v] of Object.entries(values)) if (v !== undefined) h.set(k, v);
  return h;
}

const dashboardUi = {
  host: "ops.otterworks.app",
  origin: DASHBOARD,
  "sec-fetch-site": "same-origin",
  "content-type": "application/json",
};

test("dashboard UI POST is allowed", () => {
  assert.equal(crossSiteRejection("POST", headers(dashboardUi), allowed), null);
  assert.equal(crossSiteRejection("PUT", headers(dashboardUi), allowed), null);
  assert.equal(
    crossSiteRejection("POST", headers({ ...dashboardUi, "content-type": "application/json; charset=utf-8" }), allowed),
    null,
  );
});

test("safe methods are never gated", () => {
  for (const m of ["GET", "HEAD", "OPTIONS", "get"]) {
    assert.equal(crossSiteRejection(m, headers({ origin: "https://evil.example", "sec-fetch-site": "cross-site" }), allowed), null);
  }
});

test("same-site tenant page forging no-cors checkin/persist is refused", () => {
  for (const tenantOrigin of [
    "https://t-alice.demo.otterworks.app",
    "https://api-t-alice.demo.otterworks.app",
    "https://t-main.otterworks.app",
  ]) {
    const forged = {
      host: "ops.otterworks.app",
      origin: tenantOrigin,
      "sec-fetch-site": "same-site",
      "content-type": "text/plain;charset=UTF-8",
    };
    assert.equal(crossSiteRejection("POST", headers(forged), allowed), "cross-site request refused");
    // Without fetch metadata (older browser) the Origin check still refuses it.
    const noFetchMeta = { ...forged, "sec-fetch-site": undefined };
    assert.equal(crossSiteRejection("POST", headers(noFetchMeta), allowed), "origin not allowed");
    assert.equal(crossSiteRejection("POST", headers(noFetchMeta), new Set()), "origin not allowed");
  }
});

test("cross-site and same-site fetch metadata are refused even with a matching Origin", () => {
  for (const site of ["same-site", "cross-site", "none"]) {
    assert.equal(
      crossSiteRejection("POST", headers({ ...dashboardUi, "sec-fetch-site": site }), allowed),
      "cross-site request refused",
    );
  }
});

test("missing, null or malformed Origin is refused", () => {
  for (const origin of [undefined, "null", "", "not a url", "javascript:alert(1)"]) {
    assert.equal(
      crossSiteRejection("POST", headers({ ...dashboardUi, origin }), allowed),
      "missing or invalid Origin",
    );
  }
});

test("Origin must match exactly, including scheme and port", () => {
  for (const origin of ["http://ops.otterworks.app", "https://ops.otterworks.app:8443", "https://ops.otterworks.app.evil.example"]) {
    assert.equal(crossSiteRejection("POST", headers({ ...dashboardUi, origin }), allowed), "origin not allowed");
  }
});

test("non-JSON bodies are refused", () => {
  for (const ct of [undefined, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "application/jsonx"]) {
    assert.equal(
      crossSiteRejection("POST", headers({ ...dashboardUi, "content-type": ct }), allowed),
      "Content-Type must be application/json",
    );
  }
});

test("without DASHBOARD_ALLOWED_ORIGINS the request Host is the allowed origin", () => {
  const none = parseAllowedOrigins(undefined);
  assert.equal(none.size, 0);
  const local = { host: "localhost:3000", origin: "http://localhost:3000", "content-type": "application/json" };
  assert.equal(crossSiteRejection("POST", headers(local), none), null);
  assert.equal(
    crossSiteRejection("POST", headers({ ...local, origin: "http://localhost:4000" }), none),
    "origin not allowed",
  );
  const viaIngress = { ...dashboardUi, host: "dashboard.otterworks-platform.svc", "x-forwarded-host": "ops.otterworks.app" };
  assert.equal(crossSiteRejection("POST", headers(viaIngress), none), null);
  assert.equal(crossSiteRejection("POST", headers({ ...dashboardUi, host: undefined }), none), "origin not allowed");
});

test("parseAllowedOrigins normalises and drops junk", () => {
  assert.deepEqual(
    [...parseAllowedOrigins(" https://ops.otterworks.app/ , ftp://x, nope, http://localhost:3000 ")],
    ["https://ops.otterworks.app", "http://localhost:3000"],
  );
});
