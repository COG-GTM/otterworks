// Cross-site request gate for every state-changing /api request.
//
// The session cookie is SameSite=Strict, but SameSite keys on the *site*
// (registrable domain), and every tenant host (t-<id>.demo.otterworks.app,
// t-main.otterworks.app) is same-site with ops.otterworks.app. Tenant hosts
// serve participant-pushed code, so the cookie alone cannot tell the dashboard
// UI apart from a tenant page. A mutating request must therefore:
//
//   1. not carry a Sec-Fetch-Site other than `same-origin`;
//   2. carry an Origin that is exactly the dashboard's own origin; and
//   3. be `Content-Type: application/json`, which a no-cors / form / text/plain
//      request cannot send without a CORS preflight the dashboard never answers.
//
// No Node-only imports: middleware runs this on the Edge runtime.

export const SAFE_METHODS: ReadonlySet<string> = new Set(["GET", "HEAD", "OPTIONS"]);

export interface HeaderSource {
  get(name: string): string | null;
}

function normaliseOrigin(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * Parse DASHBOARD_ALLOWED_ORIGINS (comma-separated, e.g.
 * `https://ops.otterworks.app`). Entries that are not an http(s) origin are
 * dropped. An empty result means "fall back to the request's own Host".
 */
export function parseAllowedOrigins(raw: string | undefined): Set<string> {
  const out = new Set<string>();
  for (const entry of (raw ?? "").split(",")) {
    const origin = normaliseOrigin(entry.trim());
    if (origin) out.add(origin);
  }
  return out;
}

function requestHost(headers: HeaderSource): string | null {
  // X-Forwarded-Host is set by the ingress; a browser cannot add it to a
  // cross-origin request without a preflight, so it is not attacker-steerable
  // from a tenant page.
  const forwarded = headers.get("x-forwarded-host")?.split(",")[0]?.trim();
  const host = forwarded || headers.get("host")?.trim();
  return host ? host.toLowerCase() : null;
}

function isJsonContentType(value: string | null): boolean {
  if (!value) return false;
  const mediaType = value.split(";")[0]?.trim().toLowerCase();
  return mediaType === "application/json";
}

/**
 * Returns null when the request may proceed, or a short reason when it must be
 * refused with 403. Safe methods are always allowed.
 */
export function crossSiteRejection(
  method: string,
  headers: HeaderSource,
  allowedOrigins: ReadonlySet<string> = new Set(),
): string | null {
  if (SAFE_METHODS.has(method.toUpperCase())) return null;

  const fetchSite = headers.get("sec-fetch-site");
  if (fetchSite !== null && fetchSite.trim().toLowerCase() !== "same-origin") {
    return "cross-site request refused";
  }

  const rawOrigin = headers.get("origin");
  const origin = rawOrigin ? normaliseOrigin(rawOrigin.trim()) : null;
  if (!origin) return "missing or invalid Origin";

  if (allowedOrigins.size > 0) {
    if (!allowedOrigins.has(origin)) return "origin not allowed";
  } else {
    const host = requestHost(headers);
    if (!host || new URL(origin).host !== host) return "origin not allowed";
  }

  if (!isJsonContentType(headers.get("content-type"))) {
    return "Content-Type must be application/json";
  }
  return null;
}
