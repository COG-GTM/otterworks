import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { signSession, sessionCookie } from "@/lib/session";
import { clientIp } from "@/lib/ratelimit";
import { appendAudit } from "@/lib/control";
import {
  CdAuthError,
  cachedJwks,
  grantFromClaims,
  parseTrustPolicy,
  verifyGithubOidcToken,
} from "@/lib/cdauth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AUTH_AUDIT_ID = "_auth";

// One cache per server process.
const jwks = cachedJwks();

async function audit(action: "login_ok" | "login_fail", actor: string, detail?: string) {
  try {
    await appendAudit({ tenantId: AUTH_AUDIT_ID, action, actor, detail });
  } catch {
    /* swallow */
  }
}

/**
 * CD login: exchange a GitHub Actions OIDC token for a short session bound to
 * the one tenant (and branch) the token's repository/ref map to. This is what
 * `tenant.sh sync` uses in CI instead of the facilitator passcode.
 */
export async function POST(req: NextRequest): Promise<NextResponse> {
  const ip = clientIp(req.headers);
  const secret = env.sessionSecret;
  const policy = parseTrustPolicy(env.cdOidcTrust);
  if (!secret || Object.keys(policy).length === 0) {
    return NextResponse.json({ error: "CD login is not configured" }, { status: 503 });
  }

  let token = "";
  try {
    const body = (await req.json()) as { token?: unknown };
    token = typeof body.token === "string" ? body.token : "";
  } catch {
    token = "";
  }
  if (!token || token.length > 8192) {
    return NextResponse.json({ error: "missing token" }, { status: 400 });
  }

  try {
    const claims = await verifyGithubOidcToken(token, { audience: env.cdOidcAudience, jwks });
    const grant = grantFromClaims(claims, policy);
    const ttl = env.cdSessionTtlSeconds;
    const { token: session } = signSession(
      grant.actor,
      secret,
      { scope: "cd", tenant: grant.tenantId, branch: grant.branch, repo: grant.repository },
      ttl,
    );
    await audit("login_ok", grant.actor, `cd tenant=${grant.tenantId} branch=${grant.branch} ip=${ip}`);

    const res = NextResponse.json({ ok: true, tenant: grant.tenantId, branch: grant.branch });
    res.cookies.set(sessionCookie(session, ttl));
    return res;
  } catch (err) {
    if (err instanceof CdAuthError) {
      await audit("login_fail", `ip:${ip}`, `cd: ${err.message}`);
      return NextResponse.json({ error: err.message }, { status: 401 });
    }
    throw err;
  }
}
