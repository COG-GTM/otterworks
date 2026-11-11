import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import {
  createJwksKeyResolver,
  GITHUB_OIDC_ISSUER,
  OidcRejectedError,
  refPatternMatches,
  verifyGithubActionsToken,
  type VerifyOptions,
} from "./github-oidc";
import { isValidImageTag, tenantIdForBranch } from "./util";

const AUD = "otterworks-demo-ops";
const NOW = 1_800_000_000;
const KID = "test-kid";
const { privateKey, publicKey } = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
const other = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });

const TRUSTED: Record<string, string[]> = {
  "Cognition-Partner-Workshops/otterworks": ["main", "workshop-*", "demo-*"],
  "COG-GTM/otterworks": ["workshop-*", "demo-*"],
};

function b64(obj: unknown): string {
  return Buffer.from(JSON.stringify(obj)).toString("base64url");
}

function mint(
  overrides: Record<string, unknown> = {},
  opts: { header?: Record<string, unknown>; key?: crypto.KeyObject } = {},
): string {
  const repository = (overrides.repository as string) ?? "COG-GTM/otterworks";
  const ref = (overrides.ref as string) ?? "refs/heads/workshop-derek";
  const claims = {
    iss: GITHUB_OIDC_ISSUER,
    aud: AUD,
    sub: `repo:${repository}:ref:${ref}`,
    repository,
    ref,
    ref_type: "branch",
    iat: NOW - 10,
    nbf: NOW - 10,
    exp: NOW + 300,
    run_id: "42",
    ...overrides,
  };
  const h = b64({ alg: "RS256", kid: KID, typ: "JWT", ...opts.header });
  const p = b64(claims);
  const sig = crypto.sign("RSA-SHA256", Buffer.from(`${h}.${p}`), opts.key ?? privateKey);
  return `${h}.${p}.${sig.toString("base64url")}`;
}

const options: VerifyOptions = {
  audience: AUD,
  trustedRefs: TRUSTED,
  now: NOW,
  getKey: async (kid) => (kid === KID ? publicKey : undefined),
};

async function rejects(token: string, status: number, opts: VerifyOptions = options) {
  await assert.rejects(verifyGithubActionsToken(token, opts), (err: unknown) => {
    assert.ok(err instanceof OidcRejectedError, String(err));
    assert.equal(err.status, status);
    return true;
  });
}

test("accepts a trusted fork workshop branch and returns its identity", async () => {
  const id = await verifyGithubActionsToken(mint(), options);
  assert.equal(id.repository, "COG-GTM/otterworks");
  assert.equal(id.branch, "workshop-derek");
});

test("accepts upstream main", async () => {
  const id = await verifyGithubActionsToken(
    mint({ repository: "Cognition-Partner-Workshops/otterworks", ref: "refs/heads/main" }),
    options,
  );
  assert.equal(id.branch, "main");
});

test("refuses refs and repositories outside the trust map", async () => {
  await rejects(mint({ ref: "refs/heads/main" }), 403);
  await rejects(mint({ ref: "refs/heads/feature-x" }), 403);
  await rejects(mint({ repository: "evil/otterworks" }), 403);
  await rejects(mint({ repository: "__proto__" }), 403);
});

test("refuses non-branch subjects", async () => {
  await rejects(mint({ sub: "repo:COG-GTM/otterworks:pull_request" }), 403);
  await rejects(mint({ sub: "repo:COG-GTM/otterworks:environment:prod" }), 403);
  await rejects(mint({ ref: "refs/tags/workshop-derek", ref_type: "tag" }), 403);
});

test("refuses wrong issuer, audience and expired tokens", async () => {
  await rejects(mint({ iss: "https://evil.example" }), 401);
  await rejects(mint({ aud: "sts.amazonaws.com" }), 401);
  await rejects(mint({ exp: NOW - 120 }), 401);
  await rejects(mint({ nbf: NOW + 600 }), 401);
  await rejects(mint({ iat: NOW + 600 }), 401);
});

test("refuses forged signatures, unknown keys and other algorithms", async () => {
  await rejects(mint({}, { key: other.privateKey }), 401);
  await rejects(mint({}, { header: { kid: "nope" } }), 401);
  await rejects(mint({}, { header: { alg: "none" } }), 401);
  await rejects(mint({}, { header: { alg: "HS256" } }), 401);
  const [h, p] = mint().split(".");
  await rejects(`${h}.${p}.`, 401);
  await rejects("not-a-jwt", 401);
});

test("refuses a payload swapped under a valid signature", async () => {
  const [h, , s] = mint().split(".");
  const forged = b64({ repository: "Cognition-Partner-Workshops/otterworks", ref: "refs/heads/main" });
  await rejects(`${h}.${forged}.${s}`, 401);
});

test("branch patterns follow IAM StringLike semantics", () => {
  assert.ok(refPatternMatches("workshop-*", "workshop-derek"));
  assert.ok(refPatternMatches("workshop-*", "workshop-a/b"));
  assert.ok(!refPatternMatches("workshop-*", "xworkshop-derek"));
  assert.ok(!refPatternMatches("main", "main2"));
  assert.ok(!refPatternMatches("demo.*", "demoX"));
});

test("tenant ids match branch_tenant_id() in tenant-common.sh", () => {
  assert.equal(tenantIdForBranch("workshop-derek"), "derek");
  assert.equal(tenantIdForBranch("demo/Derek_X"), "derek-x");
  assert.equal(tenantIdForBranch("main"), "main");
  assert.equal(tenantIdForBranch("demo-derek", "gtm"), "gtm-derek");
});

test("image tags are restricted to OCI tag syntax", () => {
  assert.ok(isValidImageTag("gtm-workshop-derek-abc1234"));
  assert.ok(!isValidImageTag("-x"));
  assert.ok(!isValidImageTag("a b"));
  assert.ok(!isValidImageTag("a".repeat(129)));
});

test("JWKS resolver imports RSA keys and throttles refetches for unknown kids", async () => {
  const jwk = publicKey.export({ format: "jwk" });
  let calls = 0;
  const fakeFetch = (async () => {
    calls += 1;
    return new Response(JSON.stringify({ keys: [{ ...jwk, kid: KID, alg: "RS256", use: "sig" }] }));
  }) as typeof fetch;
  const resolve = createJwksKeyResolver("https://jwks.test", fakeFetch, 60_000);

  const key = await resolve(KID);
  assert.ok(key);
  assert.ok(await verifyGithubActionsToken(mint(), { ...options, getKey: resolve }));
  assert.equal(await resolve("unknown-1"), undefined);
  assert.equal(await resolve("unknown-2"), undefined);
  assert.equal(calls, 1);
});
