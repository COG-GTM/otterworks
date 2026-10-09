import { test } from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";

process.env.SESSION_SECRET = "test-secret";
process.env.PERPETUAL_TENANT_IDS = "main";
process.env.CD_OIDC_TRUST = JSON.stringify({
  "COG-GTM/otterworks": { refs: ["workshop-*", "demo-*"], tenantPrefix: "" },
});

import { forbidCdDeploy, forbidOtherTenant, withSession, json } from "../api";
import { SESSION_COOKIE, signSession, type SessionPayload } from "../session";
import { middleware } from "../../middleware";
import { POST as checkinPost } from "../../app/api/tenants/[id]/checkin/route";
import { POST as persistPost } from "../../app/api/tenants/[id]/persist/route";
import { POST as injectPost } from "../../app/api/tenants/[id]/inject/route";
import { POST as resetPost } from "../../app/api/tenants/[id]/reset/route";
import { POST as extendPost } from "../../app/api/tenants/[id]/extend/route";
import { POST as redeployPost } from "../../app/api/tenants/[id]/redeploy/route";
import { POST as checkoutPost } from "../../app/api/tenants/checkout/route";

const CD_CLAIMS = { scope: "cd" as const, tenant: "derek", branch: "workshop-derek", repo: "COG-GTM/otterworks" };
const cdToken = () => signSession("ci:COG-GTM/otterworks", "test-secret", CD_CLAIMS, 900).token;
const facilitatorToken = () => signSession("facilitator", "test-secret").token;

function cdSession(): SessionPayload {
  return { sub: "ci:COG-GTM/otterworks", iat: 0, exp: 0, ...CD_CLAIMS };
}

function req(path: string, token: string, method = "POST", body?: unknown): NextRequest {
  return new NextRequest(`http://ops.test${path}`, {
    method,
    headers: { cookie: `${SESSION_COOKIE}=${token}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

const params = (id: string) => ({ params: Promise.resolve<Record<string, string>>({ id }) });
const noParams = () => ({ params: Promise.resolve<Record<string, string>>({}) });

test("forbidOtherTenant confines CD sessions and leaves facilitators alone", () => {
  assert.equal(forbidOtherTenant(cdSession(), "derek"), null);
  assert.equal(forbidOtherTenant(cdSession(), "alice")?.status, 403);
  assert.equal(forbidOtherTenant(cdSession(), "main")?.status, 403);
  assert.equal(forbidOtherTenant({ sub: "facilitator", iat: 0, exp: 0 }, "alice"), null);
});

test("forbidCdDeploy pins the branch, the image tag and the trusted repository", () => {
  const s = cdSession();
  assert.equal(forbidCdDeploy(s, { branch: "workshop-derek" }), null);
  assert.equal(forbidCdDeploy(s, { branch: "workshop-derek", imageTag: "tenant-derek" }), null);
  assert.equal(forbidCdDeploy(s, { branch: "workshop-derek", imageTag: "workshop-derek-abc1234" }), null);
  assert.equal(forbidCdDeploy(s, { branch: "workshop-alice" })?.status, 403);
  assert.equal(forbidCdDeploy(s, { branch: undefined })?.status, 403);
  assert.equal(forbidCdDeploy(s, { branch: "workshop-derek", imageTag: "tenant-alice" })?.status, 403);
  assert.equal(forbidCdDeploy(s, { branch: "workshop-derek", imageTag: "main" })?.status, 403);
  assert.equal(forbidCdDeploy({ ...s, repo: "evil/otterworks" }, { branch: "workshop-derek" })?.status, 403);
  assert.equal(forbidCdDeploy({ sub: "facilitator", iat: 0, exp: 0 }, { branch: "x", imageTag: "y" }), null);
});

test("withSession refuses CD sessions unless the route opts in", async () => {
  const handler = async () => json({ ok: true });
  assert.equal((await withSession(handler)(req("/api/x", cdToken()), noParams())).status, 403);
  assert.equal((await withSession(handler, { allowCd: true })(req("/api/x", cdToken()), noParams())).status, 200);
  assert.equal((await withSession(handler)(req("/api/x", facilitatorToken()), noParams())).status, 200);
  assert.equal((await withSession(handler)(req("/api/x", "bogus"), noParams())).status, 401);
});

test("CD sessions cannot check in, persist, inject, reset or extend -- even their own tenant", async () => {
  for (const id of ["derek", "alice", "main"]) {
    for (const [name, route, body] of [
      ["checkin", checkinPost, undefined],
      ["persist", persistPost, { persistent: false }],
      ["inject", injectPost, { scenario: "x" }],
      ["reset", resetPost, undefined],
      ["extend", extendPost, { ttl: "8h" }],
    ] as const) {
      const res = await route(req(`/api/tenants/${id}/${name}`, cdToken(), "POST", body), params(id));
      assert.equal(res.status, 403, `${name} ${id}`);
    }
  }
});

test("CD checkout is limited to its own tenant, branch, image and an ephemeral TTL", async () => {
  const cases: Array<[string, Record<string, unknown>, RegExp]> = [
    ["other tenant", { id: "alice", branch: "workshop-derek" }, /may only act on tenant 'derek'/],
    ["no id", { branch: "workshop-derek" }, /may only act on tenant 'derek'/],
    ["other branch", { id: "derek", branch: "workshop-alice" }, /may only deploy branch/],
    ["other image", { id: "derek", branch: "workshop-derek", image_tag: "tenant-alice" }, /image tag/],
    ["perpetual", { id: "derek", branch: "workshop-derek", persistent: true }, /may not create the perpetual/],
    ["never ttl", { id: "derek", branch: "workshop-derek", ttl: "never" }, /may not create the perpetual/],
  ];
  for (const [name, body, message] of cases) {
    const res = await checkoutPost(req("/api/tenants/checkout", cdToken(), "POST", body), noParams());
    assert.equal(res.status, 403, name);
    // Refused by the handler's own checks, not by withSession: CD must reach
    // them, or a first push could never create its tenant.
    assert.match(((await res.json()) as { error: string }).error, message, name);
  }
});

test("CD redeploy of another tenant is refused before any lookup", async () => {
  const res = await redeployPost(
    req("/api/tenants/alice/redeploy", cdToken(), "POST", { branch: "workshop-derek" }),
    params("alice"),
  );
  assert.equal(res.status, 403);
});

test("middleware keeps CD sessions off the UI and every non-CD route", async () => {
  const cd = cdToken();
  const allowed: Array<[string, string]> = [
    ["GET", "/api/tenants/derek"],
    ["POST", "/api/tenants/checkout"],
    ["POST", "/api/tenants/derek/redeploy"],
    ["POST", "/api/auth/logout"],
  ];
  const denied: Array<[string, string]> = [
    ["GET", "/"],
    ["GET", "/api/tenants"],
    ["GET", "/api/audit"],
    ["POST", "/api/tenants/derek/checkin"],
    ["POST", "/api/tenants/derek/persist"],
    ["POST", "/api/tenants/derek/inject"],
    ["PUT", "/api/reaper"],
  ];
  for (const [method, path] of allowed) {
    const res = await middleware(req(path, cd, method));
    assert.equal(res.headers.get("x-middleware-next"), "1", `${method} ${path}`);
  }
  for (const [method, path] of denied) {
    assert.equal((await middleware(req(path, cd, method))).status, 403, `${method} ${path}`);
  }
  const fac = await middleware(req("/api/tenants/alice/checkin", facilitatorToken()));
  assert.equal(fac.headers.get("x-middleware-next"), "1");
  assert.equal((await middleware(req("/api/auth/github-oidc", ""))).headers.get("x-middleware-next"), "1");
});
