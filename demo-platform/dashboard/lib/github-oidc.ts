import crypto from "node:crypto";

// Verifies GitHub Actions OIDC tokens so CD can authenticate to the dashboard
// without holding the shared facilitator passcode. Deliberately free of `@/`
// imports so it can be unit-tested outside Next.js.

export const GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com";
export const GITHUB_OIDC_JWKS_URL = `${GITHUB_OIDC_ISSUER}/.well-known/jwks`;

// Allowed clock skew between GitHub and the dashboard, seconds.
const CLOCK_SKEW_SECONDS = 60;

export interface GithubActionsClaims {
  iss: string;
  aud: string | string[];
  sub: string;
  repository: string;
  ref: string;
  ref_type?: string;
  exp: number;
  iat: number;
  nbf?: number;
  run_id?: string;
  actor?: string;
}

export interface VerifiedCdIdentity {
  repository: string;
  branch: string;
  claims: GithubActionsClaims;
}

export type KeyResolver = (kid: string) => Promise<crypto.KeyObject | undefined>;

export interface VerifyOptions {
  audience: string;
  // owner/repo => branch patterns (`*` wildcard), mirroring the CD role's
  // github_actions_trusted_repos in infra/terraform/variables.tf.
  trustedRefs: Record<string, string[]>;
  getKey: KeyResolver;
  now?: number;
}

export class OidcRejectedError extends Error {
  constructor(
    message: string,
    readonly status: 401 | 403 = 401,
  ) {
    super(message);
    this.name = "OidcRejectedError";
  }
}

// IAM StringLike semantics: `*` matches any run of characters, including `/`.
export function refPatternMatches(pattern: string, branch: string): boolean {
  const re = pattern
    .split("*")
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${re}$`).test(branch);
}

function decodeSegment<T>(segment: string, what: string): T {
  try {
    return JSON.parse(Buffer.from(segment, "base64url").toString("utf8")) as T;
  } catch {
    throw new OidcRejectedError(`malformed token ${what}`);
  }
}

export async function verifyGithubActionsToken(
  token: string,
  opts: VerifyOptions,
): Promise<VerifiedCdIdentity> {
  const parts = token.split(".");
  if (parts.length !== 3 || parts.some((p) => !p)) {
    throw new OidcRejectedError("malformed token");
  }
  const [h, p, s] = parts as [string, string, string];

  const header = decodeSegment<{ alg?: unknown; kid?: unknown }>(h, "header");
  // Pin the algorithm: never let the token choose (alg=none, HS256 with the
  // public key as the secret, ...).
  if (header.alg !== "RS256") throw new OidcRejectedError("unsupported token algorithm");
  if (typeof header.kid !== "string" || !header.kid) {
    throw new OidcRejectedError("token has no key id");
  }

  const key = await opts.getKey(header.kid);
  if (!key) throw new OidcRejectedError("unknown signing key");

  const valid = crypto.verify(
    "RSA-SHA256",
    Buffer.from(`${h}.${p}`, "utf8"),
    key,
    Buffer.from(s, "base64url"),
  );
  if (!valid) throw new OidcRejectedError("bad token signature");

  const claims = decodeSegment<GithubActionsClaims>(p, "payload");
  const now = opts.now ?? Math.floor(Date.now() / 1000);

  if (claims.iss !== GITHUB_OIDC_ISSUER) throw new OidcRejectedError("wrong token issuer");
  const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!opts.audience || !audiences.includes(opts.audience)) {
    throw new OidcRejectedError("wrong token audience");
  }
  if (typeof claims.exp !== "number" || claims.exp + CLOCK_SKEW_SECONDS < now) {
    throw new OidcRejectedError("token expired");
  }
  if (typeof claims.nbf === "number" && claims.nbf - CLOCK_SKEW_SECONDS > now) {
    throw new OidcRejectedError("token not yet valid");
  }
  if (typeof claims.iat !== "number" || claims.iat - CLOCK_SKEW_SECONDS > now) {
    throw new OidcRejectedError("token issued in the future");
  }

  if (typeof claims.repository !== "string" || typeof claims.ref !== "string") {
    throw new OidcRejectedError("token has no repository or ref");
  }
  // Branch pushes only, the same subject shape the CD role's trust policy
  // accepts: pull_request, environment and tag subjects are refused.
  const prefix = "refs/heads/";
  if (!claims.ref.startsWith(prefix) || (claims.ref_type && claims.ref_type !== "branch")) {
    throw new OidcRejectedError("token is not for a branch", 403);
  }
  if (claims.sub !== `repo:${claims.repository}:ref:${claims.ref}`) {
    throw new OidcRejectedError("token subject is not a branch ref", 403);
  }

  const branch = claims.ref.slice(prefix.length);
  const patterns = Object.prototype.hasOwnProperty.call(opts.trustedRefs, claims.repository)
    ? opts.trustedRefs[claims.repository]
    : undefined;
  if (!patterns || !patterns.some((pat) => refPatternMatches(pat, branch))) {
    throw new OidcRejectedError(`${claims.repository}@${branch} is not trusted for CD`, 403);
  }

  return { repository: claims.repository, branch, claims };
}

interface Jwk {
  kid?: string;
  kty?: string;
  alg?: string;
  use?: string;
  n?: string;
  e?: string;
}

// Caches GitHub's signing keys. An unknown kid triggers a refetch (GitHub
// rotates keys), but at most once per `minRefetchMs`, so a flood of tokens with
// made-up key ids cannot turn the dashboard into a JWKS request amplifier.
export function createJwksKeyResolver(
  url: string = GITHUB_OIDC_JWKS_URL,
  fetchImpl: typeof fetch = fetch,
  minRefetchMs = 60_000,
): KeyResolver {
  let keys = new Map<string, crypto.KeyObject>();
  let lastFetch = 0;

  async function refresh(): Promise<void> {
    lastFetch = Date.now();
    const res = await fetchImpl(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`JWKS fetch failed: HTTP ${res.status}`);
    const body = (await res.json()) as { keys?: Jwk[] };
    const next = new Map<string, crypto.KeyObject>();
    for (const jwk of body.keys ?? []) {
      if (!jwk.kid || jwk.kty !== "RSA" || !jwk.n || !jwk.e) continue;
      try {
        next.set(
          jwk.kid,
          crypto.createPublicKey({ key: { kty: "RSA", n: jwk.n, e: jwk.e }, format: "jwk" }),
        );
      } catch {
        // Skip keys Node cannot import rather than failing the whole set.
      }
    }
    keys = next;
  }

  return async (kid: string) => {
    if (!keys.has(kid) && Date.now() - lastFetch >= minRefetchMs) await refresh();
    return keys.get(kid);
  };
}
