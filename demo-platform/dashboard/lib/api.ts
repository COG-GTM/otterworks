import { NextRequest, NextResponse } from "next/server";
import { requireSession, UnauthorizedError } from "@/lib/session";
import { env } from "@/lib/env";
import { csrfRejection } from "@/lib/csrf";

export function json<T>(data: T, init?: number | ResponseInit): NextResponse {
  const responseInit = typeof init === "number" ? { status: init } : init;
  return NextResponse.json(data, responseInit);
}

export function error(status: number, message: string): NextResponse {
  return NextResponse.json({ error: message }, { status });
}

/**
 * Wrap an authenticated /api route handler. Enforces the CSRF gate and
 * requireSession() (defense in depth alongside middleware) and translates
 * known errors to status codes.
 * The `actor` passed to the handler comes only from the signed session.
 */
export function withSession(
  handler: (req: NextRequest, ctx: { actor: string; params?: Record<string, string> }) => Promise<NextResponse>,
) {
  return async (
    req: NextRequest,
    routeCtx: { params: Promise<Record<string, string>> },
  ) => {
    const rejection = csrfRejection(req);
    if (rejection) return error(rejection.status, rejection.error);

    let actor: string;
    try {
      const session = requireSession(req);
      actor = session.sub;
    } catch (err) {
      if (err instanceof UnauthorizedError) return error(401, "unauthorized");
      throw err;
    }

    try {
      const params = routeCtx?.params ? await routeCtx.params : undefined;
      return await handler(req, { actor, params });
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
