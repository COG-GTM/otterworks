import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { signSession, verifySession, sessionCookie } from "../session";

const SECRET = "test-secret";

function forge(payload: Record<string, unknown>): string {
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const sig = crypto.createHmac("sha256", SECRET).update(body).digest("base64url");
  return `${body}.${sig}`;
}

test("a facilitator session carries no scope", () => {
  const { token } = signSession("facilitator", SECRET);
  const s = verifySession(token, SECRET);
  assert.equal(s?.sub, "facilitator");
  assert.equal(s?.scope, undefined);
});

test("a CD session round-trips its tenant binding and short TTL", () => {
  const { token, exp } = signSession(
    "ci:COG-GTM/otterworks",
    SECRET,
    { scope: "cd", tenant: "derek", branch: "workshop-derek", repo: "COG-GTM/otterworks" },
    900,
  );
  const s = verifySession(token, SECRET);
  assert.deepEqual(
    { scope: s?.scope, tenant: s?.tenant, branch: s?.branch, repo: s?.repo },
    { scope: "cd", tenant: "derek", branch: "workshop-derek", repo: "COG-GTM/otterworks" },
  );
  assert.ok(exp - Math.floor(Date.now() / 1000) <= 900);
  assert.equal(sessionCookie(token, 900).maxAge, 900);
});

test("a scoped session without its binding is rejected outright", () => {
  const exp = Math.floor(Date.now() / 1000) + 60;
  assert.equal(verifySession(forge({ sub: "x", exp, scope: "cd" }), SECRET), null);
  assert.equal(verifySession(forge({ sub: "x", exp, scope: "cd", tenant: "derek" }), SECRET), null);
  assert.equal(verifySession(forge({ sub: "x", exp, scope: "admin", tenant: "a", branch: "b" }), SECRET), null);
  assert.ok(verifySession(forge({ sub: "x", exp, scope: "cd", tenant: "a", branch: "b" }), SECRET));
});
