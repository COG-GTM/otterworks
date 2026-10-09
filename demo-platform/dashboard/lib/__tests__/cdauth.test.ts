import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import {
  CdAuthError,
  GITHUB_OIDC_ISSUER,
  cachedJwks,
  grantFromClaims,
  imageTagAllowed,
  parseTrustPolicy,
  refMatches,
  tenantIdForBranch,
  verifyGithubOidcToken,
  type GithubOidcClaims,
  type Jwk,
} from "../cdauth";

const POLICY = parseTrustPolicy(
  JSON.stringify({
    "Cognition-Partner-Workshops/otterworks": { refs: ["main", "workshop-*", "demo-*"], tenantPrefix: "" },
    "COG-GTM/otterworks": { refs: ["workshop-*", "demo-*"], tenantPrefix: "gtm" },
  }),
);

function claimsFor(repository: string, branch: string, extra: Partial<GithubOidcClaims> = {}): GithubOidcClaims {
  const ref = `refs/heads/${branch}`;
  return { repository, ref, ref_type: "branch", event_name: "push", sub: `repo:${repository}:ref:${ref}`, ...extra };
}

// ---------------------------------------------------------------- trust policy

test("parseTrustPolicy reads repositories, refs and prefixes", () => {
  assert.deepEqual(POLICY["COG-GTM/otterworks"], { refs: ["workshop-*", "demo-*"], tenantPrefix: "gtm" });
  assert.equal(POLICY["Cognition-Partner-Workshops/otterworks"]?.tenantPrefix, "");
});

test("parseTrustPolicy fails closed on anything malformed", () => {
  for (const raw of [
    undefined,
    "",
    "not json",
    "[]",
    '{"no-slash": {"refs": ["x"]}}',
    '{"a/b": {"refs": "workshop-*"}}',
    '{"a/b": {"refs": [""]}}',
    '{"a/b": {"refs": ["x"], "tenantPrefix": "Bad Prefix"}}',
    '{"a/b": {"refs": ["x"]}, "c/d": null}',
  ]) {
    assert.deepEqual(parseTrustPolicy(raw), {}, String(raw));
  }
});

test("refMatches follows IAM StringLike semantics and escapes regex syntax", () => {
  assert.ok(refMatches("workshop-derek", "workshop-*"));
  assert.ok(refMatches("workshop-a/b", "workshop-*"));
  assert.ok(refMatches("demo-x", "demo-?"));
  assert.ok(!refMatches("main", "workshop-*"));
  assert.ok(!refMatches("xworkshop-derek", "workshop-*"));
  assert.ok(!refMatches("mainX", "main"));
  assert.ok(!refMatches("ab", "a.")); // `.` is literal
});

test("tenantIdForBranch matches tenant.sh / branch_tenant_id", () => {
  assert.equal(tenantIdForBranch("workshop-derek", ""), "derek");
  assert.equal(tenantIdForBranch("demo/Derek_X", ""), "derek-x");
  assert.equal(tenantIdForBranch("demo-derek", "gtm"), "gtm-derek");
  assert.equal(tenantIdForBranch("main", ""), "main");
  assert.equal(tenantIdForBranch("workshop-", "gtm"), "");
});

// ---------------------------------------------------------------- claims -> grant

test("grantFromClaims binds a session to the branch's own tenant", () => {
  assert.deepEqual(grantFromClaims(claimsFor("COG-GTM/otterworks", "workshop-derek"), POLICY), {
    tenantId: "gtm-derek",
    branch: "workshop-derek",
    repository: "COG-GTM/otterworks",
    actor: "ci:COG-GTM/otterworks",
  });
  assert.equal(grantFromClaims(claimsFor("Cognition-Partner-Workshops/otterworks", "main"), POLICY).tenantId, "main");
  assert.equal(
    grantFromClaims(claimsFor("COG-GTM/otterworks", "demo-x", { event_name: "workflow_dispatch" }), POLICY).tenantId,
    "gtm-x",
  );
});

test("grantFromClaims rejects untrusted repositories, refs, events and forged subjects", () => {
  const cases: Array<[string, GithubOidcClaims]> = [
    ["untrusted repo", claimsFor("evil/otterworks", "workshop-x")],
    ["prototype key", claimsFor("__proto__", "workshop-x")],
    ["fork main", claimsFor("COG-GTM/otterworks", "main")],
    ["other branch", claimsFor("COG-GTM/otterworks", "feature-x")],
    ["pull_request", claimsFor("COG-GTM/otterworks", "workshop-x", { event_name: "pull_request" })],
    ["no event", claimsFor("COG-GTM/otterworks", "workshop-x", { event_name: undefined })],
    ["tag", claimsFor("COG-GTM/otterworks", "workshop-x", { ref_type: "tag", ref: "refs/tags/workshop-x" })],
    [
      "sub names another ref",
      claimsFor("COG-GTM/otterworks", "workshop-x", { sub: "repo:COG-GTM/otterworks:ref:refs/heads/workshop-y" }),
    ],
    [
      "sub names another repo",
      claimsFor("COG-GTM/otterworks", "workshop-x", { sub: "repo:evil/otterworks:ref:refs/heads/workshop-x" }),
    ],
    ["no tenant id", claimsFor("COG-GTM/otterworks", "workshop-")],
  ];
  for (const [name, claims] of cases) {
    assert.throws(() => grantFromClaims(claims, POLICY), CdAuthError, name);
  }
  assert.throws(() => grantFromClaims(claimsFor("COG-GTM/otterworks", "workshop-x"), {}), CdAuthError);
});

// ---------------------------------------------------------------- image tags

test("imageTagAllowed admits only the tenant pointer and the branch's own builds", () => {
  const grant = grantFromClaims(claimsFor("COG-GTM/otterworks", "workshop-derek"), POLICY);
  assert.ok(imageTagAllowed(grant, "gtm", "tenant-gtm-derek"));
  assert.ok(imageTagAllowed(grant, "gtm", "gtm-workshop-derek-abc1234"));
  assert.ok(!imageTagAllowed(grant, "gtm", "tenant-derek"));
  assert.ok(!imageTagAllowed(grant, "gtm", "main"));
  assert.ok(!imageTagAllowed(grant, "gtm", "gtm-workshop-alice-abc1234"));
  assert.ok(!imageTagAllowed(grant, "gtm", "workshop-derek-abc1234"));
  assert.ok(!imageTagAllowed(grant, "gtm", "gtm-workshop-derek-notasha"));
});

// ---------------------------------------------------------------- JWT verification

const { publicKey, privateKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
const KID = "test-key";
const JWK: Jwk = { ...(publicKey.export({ format: "jwk" }) as Jwk), kid: KID, alg: "RS256" };
const jwks = async (kid: string) => (kid === KID ? JWK : undefined);
const AUD = "otterworks-demo-ops";
const NOW = 1_800_000_000;

function b64(o: unknown): string {
  return Buffer.from(JSON.stringify(o)).toString("base64url");
}

function mint(claims: Record<string, unknown>, header: Record<string, unknown> = { alg: "RS256", kid: KID }): string {
  const body = `${b64(header)}.${b64(claims)}`;
  const sig = crypto.sign("RSA-SHA256", Buffer.from(body), privateKey).toString("base64url");
  return `${body}.${sig}`;
}

const GOOD = {
  ...claimsFor("COG-GTM/otterworks", "workshop-derek"),
  iss: GITHUB_OIDC_ISSUER,
  aud: AUD,
  iat: NOW - 10,
  nbf: NOW - 10,
  exp: NOW + 300,
};

test("verifyGithubOidcToken accepts a correctly signed GitHub token", async () => {
  const claims = await verifyGithubOidcToken(mint(GOOD), { audience: AUD, jwks, now: NOW });
  assert.equal(claims.repository, "COG-GTM/otterworks");
});

test("verifyGithubOidcToken rejects bad signatures, algorithms, issuers, audiences and times", async () => {
  const [h, p] = mint(GOOD).split(".");
  const tampered = `${h}.${b64({ ...GOOD, repository: "Cognition-Partner-Workshops/otterworks" })}.${mint(GOOD).split(".")[2]}`;
  const hs256Body = `${b64({ alg: "HS256", kid: KID })}.${p}`;
  const hs256 = `${hs256Body}.${crypto.createHmac("sha256", JSON.stringify(JWK)).update(hs256Body).digest("base64url")}`;
  const cases: Array<[string, string]> = [
    ["malformed", "a.b"],
    ["garbage", "a.b.c"],
    ["tampered payload", tampered],
    ["alg none", `${b64({ alg: "none", kid: KID })}.${p}.`],
    ["alg none with sig", `${b64({ alg: "none", kid: KID })}.${p}.x`],
    ["HS256", hs256],
    ["unknown kid", mint(GOOD, { alg: "RS256", kid: "other" })],
    ["no kid", mint(GOOD, { alg: "RS256" })],
    ["wrong issuer", mint({ ...GOOD, iss: "https://evil.example" })],
    ["wrong audience", mint({ ...GOOD, aud: "sts.amazonaws.com" })],
    ["expired", mint({ ...GOOD, exp: NOW - 120 })],
    ["no exp", mint({ ...GOOD, exp: undefined })],
    ["not yet valid", mint({ ...GOOD, nbf: NOW + 120 })],
  ];
  void h;
  for (const [name, token] of cases) {
    await assert.rejects(verifyGithubOidcToken(token, { audience: AUD, jwks, now: NOW }), CdAuthError, name);
  }
});

test("cachedJwks caches keys and limits refetches for unknown kids", async () => {
  let calls = 0;
  const fakeFetch = (async () => {
    calls++;
    return new Response(JSON.stringify({ keys: [JWK] }), { status: 200 });
  }) as typeof fetch;
  const lookup = cachedJwks("https://jwks.invalid", fakeFetch);
  assert.equal((await lookup(KID))?.kid, KID);
  assert.equal(await lookup("unknown"), undefined);
  assert.equal(await lookup("unknown"), undefined);
  assert.equal(calls, 1);
});

test("cachedJwks surfaces a failed fetch as an auth error", async () => {
  const failing = (async () => new Response("nope", { status: 503 })) as typeof fetch;
  await assert.rejects(cachedJwks("https://jwks.invalid", failing)(KID), CdAuthError);
});

test("cachedJwks retries after a failed fetch instead of caching the failure", async () => {
  let calls = 0;
  const flaky = (async () => {
    calls++;
    return calls === 1
      ? new Response("nope", { status: 503 })
      : new Response(JSON.stringify({ keys: [JWK] }), { status: 200 });
  }) as typeof fetch;
  const lookup = cachedJwks("https://jwks.invalid", flaky);
  await assert.rejects(lookup(KID), CdAuthError);
  assert.equal((await lookup(KID))?.kid, KID);
});

test("cachedJwks keeps the last good keys when a refresh fails", async () => {
  let calls = 0;
  const failsLater = (async () => {
    calls++;
    return calls === 1
      ? new Response(JSON.stringify({ keys: [JWK] }), { status: 200 })
      : new Response("nope", { status: 503 });
  }) as typeof fetch;
  const lookup = cachedJwks("https://jwks.invalid", failsLater, 0);
  assert.equal((await lookup(KID))?.kid, KID);
  await new Promise((r) => setTimeout(r, 5));
  assert.equal((await lookup(KID))?.kid, KID);
  assert.ok(calls >= 2);
});
