import { NextRequest, NextResponse } from "next/server";
import { crossSiteRejection, parseAllowedOrigins } from "@/lib/csrf";

// NOTE: Next.js middleware runs on the Edge runtime, so it cannot use
// node:crypto. We re-verify the HMAC session token with Web Crypto here. This
// is the first gate; every /api route also independently calls requireSession()
// (node:crypto) for defense in depth.

const SESSION_COOKIE = "ow_ops_session";

function base64urlToBytes(input: string): Uint8Array {
  const b64 = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
  const bin = atob(b64 + pad);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

async function verifyToken(token: string | undefined, secret: string): Promise<boolean> {
  if (!token) return false;
  const dot = token.indexOf(".");
  if (dot <= 0) return false;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);

  let sigBytes: Uint8Array;
  try {
    sigBytes = base64urlToBytes(sig);
  } catch {
    return false;
  }

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    sigBytes as unknown as ArrayBuffer,
    enc.encode(body) as unknown as ArrayBuffer,
  );
  if (!valid) return false;

  try {
    const json = new TextDecoder().decode(base64urlToBytes(body));
    const payload = JSON.parse(json) as { exp?: number };
    if (typeof payload.exp !== "number" || payload.exp < Math.floor(Date.now() / 1000)) {
      return false;
    }
  } catch {
    return false;
  }
  return true;
}

// Paths allowed without a session.
function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname === "/api/auth/login" ||
    pathname === "/api/health" ||
    pathname === "/favicon.ico"
  );
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;

  // Runs before the public-path bypass so login/logout are covered too.
  if (pathname.startsWith("/api/")) {
    const reason = crossSiteRejection(
      req.method,
      req.headers,
      parseAllowedOrigins(process.env.DASHBOARD_ALLOWED_ORIGINS),
    );
    if (reason) return NextResponse.json({ error: reason }, { status: 403 });
  }

  if (isPublicPath(pathname)) return NextResponse.next();

  const secret = process.env.SESSION_SECRET;
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const ok = secret ? await verifyToken(token, secret) : false;
  if (ok) return NextResponse.next();

  // Unauthenticated API calls get a 401; page navigations redirect to login.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  return NextResponse.redirect(url);
}

// Exclude Next.js internals + static assets from the middleware.
export const config = {
  matcher: ["/((?!_next/static|_next/image|assets|favicon.ico).*)"],
};
