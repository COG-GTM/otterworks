// Continuous-delivery authentication: a GitHub Actions OIDC token, verified
// here, exchanged for a dashboard session bound to ONE tenant.
//
// CD used to log in with the facilitator passcode, so any branch the CD role
// trusts (every workshop-*/demo-* in every trusted repository, each running a
// workflow definition its pusher wrote) could read the passcode and get a
// session that controls every tenant. A CD session instead carries the tenant
// derived from the token's own `repository` and `ref` claims, and the API
// lets it do only what `tenant.sh sync` needs: read that tenant, create it,
// and redeploy it from that branch.
//
// Deliberately free of `@/` imports and Next.js APIs so it can be unit tested
// with plain `node --test` (see lib/__tests__).

import crypto from "node:crypto";
import { sanitizeId } from "./util";

export const GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com";
export const GITHUB_OIDC_JWKS_URL = `${GITHUB_OIDC_ISSUER}/.well-known/jwks`;
export const DEFAULT_CD_AUDIENCE = "otterworks-demo-ops";

// GitHub's clock and ours may drift; the token itself is valid for minutes.
const CLOCK_SKEW_SECONDS = 60;

// Events whose ref is a branch the pusher (or a dispatcher with write access)
// chose. pull_request tokens name refs/pull/..., which no pattern matches, but
// they are excluded explicitly so a pattern like `*` cannot widen to them.
const CD_EVENTS = new Set(["push", "workflow_dispatch"]);

export interface CdRepoTrust {
  // Branch patterns (git ref names; `*` matches any run of characters,
  // including `/`, as in the IAM StringLike trust it replaces).
  refs: string[];
  // TENANT_PREFIX that repository's CD uses; "" for none.
  tenantPrefix: string;
}

export type CdTrustPolicy = Record<string, CdRepoTrust>;

export interface GithubOidcClaims {
  iss?: string;
  aud?: string | string[];
  sub?: string;
  exp?: number;
  nbf?: number;
  iat?: number;
  repository?: string;
  ref?: string;
  ref_type?: string;
  event_name?: string;
  [claim: string]: unknown;
}

export interface CdGrant {
  // The only tenant this session may touch.
  tenantId: string;
  // The branch it was issued for; checkout/redeploy must name exactly this one.
  branch: string;
  repository: string;
  // The owner recorded on tenants this grant creates, and the actor in audit.
  actor: string;
}

export class CdAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CdAuthError";
  }
}

export interface Jwk {
  kty: string;
  kid?: string;
  alg?: string;
  use?: string;
  n?: string;
  e?: string;
}

export type JwksLookup = (kid: string) => Promise<Jwk | undefined>;

/**
 * Parse the CD_OIDC_TRUST setting:
 *   {"owner/repo": {"refs": ["workshop-*"], "tenantPrefix": "gtm"}, ...}
 * Anything malformed yields an empty policy, i.e. CD login refused -- a typo
 * must not widen trust.
 */
export function parseTrustPolicy(raw: string | undefined): CdTrustPolicy {
  if (!raw || !raw.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};

  const policy: CdTrustPolicy = {};
  for (const [repo, value] of Object.entries(parsed as Record<string, unknown>)) {
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) return {};
    if (!value || typeof value !== "object") return {};
    const v = value as { refs?: unknown; tenantPrefix?: unknown };
    if (!Array.isArray(v.refs) || !v.refs.every((r) => typeof r === "string" && r.trim())) return {};
    const prefix = v.tenantPrefix ?? "";
    if (typeof prefix !== "string" || (prefix !== "" && sanitizeId(prefix) !== prefix)) return {};
    policy[repo] = { refs: (v.refs as string[]).map((r) => r.trim()), tenantPrefix: prefix };
  }
  return policy;
}

/** IAM StringLike semantics: `*` is any run of characters, `?` any one. */
export function refMatches(branch: string, pattern: string): boolean {
  const re = pattern
    .split("")
    .map((c) => (c === "*" ? ".*" : c === "?" ? "." : c.replace(/[\\^$.|+()[\]{}]/g, "\\$&")))
    .join("");
  return new RegExp(`^${re}$`).test(branch);
}

/**
 * The tenant id a branch deploys to. Must stay identical to `sync` in
 * scripts/tenant.sh and branch_tenant_id in scripts/lib/tenant-common.sh.
 */
export function tenantIdForBranch(branch: string, tenantPrefix: string): string {
  const stripped = sanitizeId(branch.replace(/^(workshop|demo)[-/]/, ""));
  // A bare `workshop-` must not resolve to the prefix itself (tenant `gtm`).
  if (!stripped) return "";
  return sanitizeId(tenantPrefix ? `${tenantPrefix}-${stripped}` : stripped);
}

/** branch_tag_slug from scripts/lib/tenant-common.sh. */
export function branchTagSlug(branch: string): string {
  return branch.toLowerCase().replace(/[^a-z0-9._-]/g, "-");
}

/**
 * Map verified token claims to a grant, or throw. Repository, ref type, event
 * and branch pattern must all match the trust policy.
 */
export function grantFromClaims(claims: GithubOidcClaims, policy: CdTrustPolicy): CdGrant {
  const repository = typeof claims.repository === "string" ? claims.repository : "";
  const trust = Object.prototype.hasOwnProperty.call(policy, repository) ? policy[repository] : undefined;
  if (!trust) throw new CdAuthError(`repository '${repository}' is not trusted for CD`);

  if (typeof claims.event_name !== "string" || !CD_EVENTS.has(claims.event_name)) {
    throw new CdAuthError(`event '${String(claims.event_name)}' may not deploy`);
  }
  const ref = typeof claims.ref === "string" ? claims.ref : "";
  if (claims.ref_type !== "branch" || !ref.startsWith("refs/heads/")) {
    throw new CdAuthError("only branch refs may deploy");
  }
  const branch = ref.slice("refs/heads/".length);
  if (!branch || !trust.refs.some((p) => refMatches(branch, p))) {
    throw new CdAuthError(`branch '${branch}' of ${repository} is not trusted for CD`);
  }
  // The subject must agree with the claims it is checked against: AWS trusted
  // `sub`, and a token whose sub named another repo or ref would be forged.
  if (claims.sub !== `repo:${repository}:ref:${ref}`) {
    throw new CdAuthError("token subject does not match its repository/ref claims");
  }

  const tenantId = tenantIdForBranch(branch, trust.tenantPrefix);
  if (!/^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$/.test(tenantId)) {
    throw new CdAuthError(`cannot derive a tenant id from branch '${branch}'`);
  }
  return { tenantId, branch, repository, actor: `ci:${repository}` };
}

/**
 * Image tags a grant may ask its tenant to run: this branch's own immutable
 * builds (<prefix>-<slug>-<sha>, as cd-tenant.yml names them) or the tenant's
 * pointer tag. Anything else would let a branch deploy another tenant's build.
 */
export function imageTagAllowed(grant: CdGrant, tenantPrefix: string, imageTag: string): boolean {
  if (imageTag === `tenant-${grant.tenantId}`) return true;
  const own = `${tenantPrefix ? `${tenantPrefix}-` : ""}${branchTagSlug(grant.branch)}-`;
  return imageTag.startsWith(own) && /^[a-f0-9]{7,40}$/.test(imageTag.slice(own.length));
}

function decodeSegment<T>(segment: string): T {
  return JSON.parse(Buffer.from(segment, "base64url").toString("utf8")) as T;
}

/**
 * Verify a GitHub Actions OIDC JWT: RS256 signature against GitHub's JWKS,
 * issuer, audience and validity window. Returns the claims or throws.
 */
export async function verifyGithubOidcToken(
  token: string,
  opts: { audience: string; jwks: JwksLookup; now?: number },
): Promise<GithubOidcClaims> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts.some((p) => !p)) throw new CdAuthError("malformed token");
  const [h, p, s] = parts as [string, string, string];

  let header: { alg?: string; kid?: string; typ?: string };
  let claims: GithubOidcClaims;
  try {
    header = decodeSegment(h);
    claims = decodeSegment(p);
  } catch {
    throw new CdAuthError("malformed token");
  }
  // Pin the algorithm: never let the token choose (alg=none, HS256 with the
  // public key as the secret, ...).
  if (header.alg !== "RS256" || typeof header.kid !== "string" || !header.kid) {
    throw new CdAuthError("unsupported token algorithm");
  }

  const jwk = await opts.jwks(header.kid);
  if (!jwk || jwk.kty !== "RSA" || (jwk.alg && jwk.alg !== "RS256")) {
    throw new CdAuthError("unknown signing key");
  }
  let key: crypto.KeyObject;
  try {
    key = crypto.createPublicKey({ key: { kty: "RSA", n: jwk.n, e: jwk.e }, format: "jwk" });
  } catch {
    throw new CdAuthError("unusable signing key");
  }
  const valid = crypto.verify(
    "RSA-SHA256",
    Buffer.from(`${h}.${p}`, "utf8"),
    key,
    Buffer.from(s, "base64url"),
  );
  if (!valid) throw new CdAuthError("bad token signature");

  const now = opts.now ?? Math.floor(Date.now() / 1000);
  if (claims.iss !== GITHUB_OIDC_ISSUER) throw new CdAuthError("wrong token issuer");
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!aud.includes(opts.audience)) throw new CdAuthError("wrong token audience");
  if (typeof claims.exp !== "number" || claims.exp + CLOCK_SKEW_SECONDS < now) {
    throw new CdAuthError("token expired");
  }
  if (typeof claims.nbf === "number" && claims.nbf - CLOCK_SKEW_SECONDS > now) {
    throw new CdAuthError("token not yet valid");
  }
  return claims;
}

/**
 * JWKS lookup with a small cache. An unknown kid triggers at most one refetch
 * per minute (GitHub rotates keys), so junk kids cannot hammer GitHub.
 */
export function cachedJwks(
  url: string = GITHUB_OIDC_JWKS_URL,
  fetchImpl: typeof fetch = fetch,
  ttlMs = 10 * 60 * 1000,
): JwksLookup {
  let keys: Jwk[] = [];
  let fetchedAt = 0;

  async function refresh(): Promise<void> {
    fetchedAt = Date.now();
    const res = await fetchImpl(url, { headers: { accept: "application/json" } });
    if (!res.ok) throw new CdAuthError(`JWKS fetch failed (HTTP ${res.status})`);
    const body = (await res.json()) as { keys?: Jwk[] };
    keys = Array.isArray(body.keys) ? body.keys : [];
  }

  return async (kid: string) => {
    if (fetchedAt === 0 || Date.now() - fetchedAt > ttlMs) await refresh();
    let found = keys.find((k) => k.kid === kid);
    if (!found && Date.now() - fetchedAt > 60 * 1000) {
      await refresh();
      found = keys.find((k) => k.kid === kid);
    }
    return found;
  };
}
