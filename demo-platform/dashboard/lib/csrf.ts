// CSRF gate for state-changing requests. Edge-safe (no node: imports) so the
// middleware and the node-runtime route handlers share one implementation.
//
// SameSite on the session cookie is not enough: it keys on the registrable
// domain, and every tenant host (t-<id>.demo.otterworks.app, t-main.otterworks.app)
// is same-site with the dashboard, so a page on any tenant can send requests
// that carry the facilitator's cookie. Browsers always send Origin and
// Sec-Fetch-Site on non-GET requests; non-browser clients (scripts/tenant.sh)
// send neither, and cannot hold a facilitator's cookie unless they logged in.

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export interface CsrfRequest {
  method: string;
  headers: Headers;
}

export interface CsrfRejection {
  status: 403 | 415;
  error: string;
}

/**
 * Origins allowed to make state-changing requests. DASHBOARD_ORIGIN
 * (comma-separated, e.g. https://ops.otterworks.app) pins them explicitly;
 * unset falls back to the request's own Host, which a browser always sets to
 * the dashboard and a cross-origin page cannot override.
 */
function allowedOrigins(headers: Headers): Set<string> | null {
  const raw = process.env.DASHBOARD_ORIGIN;
  if (raw && raw.trim()) {
    return new Set(
      raw
        .split(",")
        .map((s) => s.trim().replace(/\/+$/, "").toLowerCase())
        .filter(Boolean),
    );
  }
  return headers.get("host") ? null : new Set();
}

function originAllowed(origin: string, headers: Headers): boolean {
  let parsed: URL;
  try {
    parsed = new URL(origin);
  } catch {
    return false; // includes the opaque "null" origin
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return false;
  const allowed = allowedOrigins(headers);
  if (allowed) return allowed.has(parsed.origin.toLowerCase());
  return parsed.host.toLowerCase() === (headers.get("host") || "").toLowerCase();
}

function isJson(contentType: string | null): boolean {
  if (!contentType) return false;
  const mediaType = contentType.split(";")[0]?.trim().toLowerCase();
  return mediaType === "application/json";
}

/**
 * Returns why a state-changing request must be refused, or null if it may
 * proceed. Safe methods always pass.
 *
 * - Sec-Fetch-Site, when present, must be `same-origin` (a tenant page sends
 *   `same-site`).
 * - Origin, when present, must be the dashboard's own origin.
 * - Content-Type must be application/json. A cross-origin browser request
 *   with that type needs a CORS preflight the dashboard never answers, so
 *   no-cors / form / text/plain bodies are refused even if Origin is absent.
 */
export function csrfRejection(req: CsrfRequest): CsrfRejection | null {
  if (SAFE_METHODS.has(req.method.toUpperCase())) return null;

  const fetchSite = req.headers.get("sec-fetch-site");
  if (fetchSite !== null && fetchSite.toLowerCase() !== "same-origin") {
    return { status: 403, error: "cross-site request refused" };
  }

  const origin = req.headers.get("origin");
  if (origin !== null && !originAllowed(origin, req.headers)) {
    return { status: 403, error: "cross-origin request refused" };
  }

  if (!isJson(req.headers.get("content-type"))) {
    return { status: 415, error: "content-type must be application/json" };
  }

  return null;
}
