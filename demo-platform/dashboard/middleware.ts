import { NextRequest, NextResponse } from "next/server";

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

interface TokenPayload {
  exp?: number;
  scope?: string;
}

async function verifyToken(token: string | undefined, secret: string): Promise<TokenPayload | null> {
  if (!token) return null;
  const dot = token.indexOf(".");
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);

  let sigBytes: Uint8Array;
  try {
    sigBytes = base64urlToBytes(sig);
  } catch {
    return null;
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
  if (!valid) return null;

  try {
    const json = new TextDecoder().decode(base64urlToBytes(body));
    const payload = JSON.parse(json) as TokenPayload;
    if (typeof payload.exp !== "number" || payload.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

// Paths allowed without a session.
function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname === "/api/auth/login" ||
    pathname === "/api/auth/github-oidc" ||
    pathname === "/api/health" ||
    pathname === "/favicon.ico"
  );
}

// The only paths a CD session (scope "cd", from a GitHub OIDC token) may
// reach. Each handler additionally confines it to its own tenant and branch;
// this is the first gate, so the UI and every other route stay facilitator-only.
function isCdPath(pathname: string, method: string): boolean {
  if (pathname === "/api/auth/logout") return true;
  if (method === "POST" && pathname === "/api/tenants/checkout") return true;
  if (method === "POST" && /^\/api\/tenants\/[^/]+\/redeploy$/.test(pathname)) return true;
  return method === "GET" && /^\/api\/tenants\/[^/]+$/.test(pathname) && pathname !== "/api/tenants/checkout";
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;
  if (isPublicPath(pathname)) return NextResponse.next();

  const secret = process.env.SESSION_SECRET;
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const payload = secret ? await verifyToken(token, secret) : null;
  if (payload && payload.scope === undefined) return NextResponse.next();
  if (payload && payload.scope === "cd") {
    if (isCdPath(pathname, req.method)) return NextResponse.next();
    return NextResponse.json({ error: "forbidden for CD sessions" }, { status: 403 });
  }

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
