import { NextRequest, NextResponse } from "next/server";
import { requireSession, UnauthorizedError, type SessionPayload } from "@/lib/session";
import { env } from "@/lib/env";
import { imageTagAllowed, parseTrustPolicy } from "@/lib/cdauth";

export function json<T>(data: T, init?: number | ResponseInit): NextResponse {
  const responseInit = typeof init === "number" ? { status: init } : init;
  return NextResponse.json(data, responseInit);
}

export function error(status: number, message: string): NextResponse {
  return NextResponse.json({ error: message }, { status });
}

export interface SessionContext {
  actor: string;
  session: SessionPayload;
  params?: Record<string, string>;
}

/** True for a CD session (bound to one tenant/branch), false for a facilitator. */
export function isCdSession(session: SessionPayload): boolean {
  return session.scope === "cd";
}

/**
 * A CD session may only address the tenant it was issued for. Returns the 403
 * to send, or null when `id` is in scope (always, for a facilitator).
 */
export function forbidOtherTenant(session: SessionPayload, id: string): NextResponse | null {
  if (!isCdSession(session) || session.tenant === id) return null;
  return error(403, `this CD session may only act on tenant '${session.tenant}'`);
}

/**
 * For a CD session, check everything a deploy request names against the
 * session's binding: its own branch, an image tag built from that branch, and
 * a repository that is still trusted (so dropping a repo from CD_OIDC_TRUST
 * revokes its live sessions too). Returns the 403 to send, or null.
 */
export function forbidCdDeploy(
  session: SessionPayload,
  req: { branch?: string; imageTag?: string },
): NextResponse | null {
  if (!isCdSession(session)) return null;
  const trust = session.repo ? parseTrustPolicy(env.cdOidcTrust)[session.repo] : undefined;
  if (!trust) return error(403, `repository '${session.repo ?? "-"}' is no longer trusted for CD`);
  if (req.branch !== session.branch) {
    return error(403, `this CD session may only deploy branch '${session.branch}'`);
  }
  if (
    req.imageTag !== undefined &&
    !imageTagAllowed(
      { tenantId: session.tenant ?? "", branch: session.branch ?? "", repository: session.repo ?? "", actor: session.sub },
      trust.tenantPrefix,
      req.imageTag,
    )
  ) {
    return error(403, `image tag '${req.imageTag}' was not built from '${session.branch}'`);
  }
  return null;
}

/**
 * Wrap an authenticated /api route handler. Enforces requireSession() (defense
 * in depth alongside middleware) and translates known errors to status codes.
 * The `actor` passed to the handler comes only from the signed session.
 *
 * CD sessions (scope "cd") are refused with 403 unless the route passes
 * `{ allowCd: true }`, and a route that does must then confine them to their
 * own tenant -- see forbidOtherTenant().
 */
export function withSession(
  handler: (req: NextRequest, ctx: SessionContext) => Promise<NextResponse>,
  opts: { allowCd?: boolean } = {},
) {
  return async (
    req: NextRequest,
    routeCtx: { params: Promise<Record<string, string>> },
  ) => {
    let session: SessionPayload;
    try {
      session = requireSession(req);
    } catch (err) {
      if (err instanceof UnauthorizedError) return error(401, "unauthorized");
      throw err;
    }
    if (isCdSession(session) && !opts.allowCd) {
      return error(403, "CD sessions may only read, check out and redeploy their own tenant");
    }

    try {
      const params = routeCtx?.params ? await routeCtx.params : undefined;
      return await handler(req, { actor: session.sub, session, params });
    } catch (err) {
      return translateError(err);
    }
  };
}

export function translateError(err: unknown): NextResponse {
  if (err instanceof UnauthorizedError) return error(401, "unauthorized");
  const name = err instanceof Error ? err.name : "";
  if (name === "LockConflictError") return error(409, (err as Error).message);
  if (name === "ConditionalCheckFailedException") return error(404, "not found");
  // Missing configuration (e.g. RUNNER_IMAGE) → 503 so the client can retry
  // once the platform is fully wired.
  if (err instanceof Error && /is not configured/.test(err.message)) {
    return error(503, err.message);
  }
  const detail = err instanceof Error ? err.message : "internal error";
  return error(500, detail);
}

export function requireConfigured(): NextResponse | null {
  if (!env.sessionSecret) return error(500, "SESSION_SECRET is not configured");
  return null;
}
