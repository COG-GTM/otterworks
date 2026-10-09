import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { constantTimeEqual, signSession, sessionCookie } from "@/lib/session";
import {
  checkRateLimit,
  clientIp,
  recordFailure,
  recordSuccess,
  type LoginClient,
} from "@/lib/ratelimit";
import {
  DEVICE_COOKIE,
  deviceCookie,
  newDeviceId,
  signDeviceToken,
  verifyDeviceToken,
} from "@/lib/device";
import { appendAudit } from "@/lib/control";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AUTH_AUDIT_ID = "_auth";

async function audit(action: "login_ok" | "login_fail", ip: string, detail?: string) {
  // Best-effort — never let an audit write failure block the auth decision,
  // and never include the passcode in `detail`.
  try {
    await appendAudit({ tenantId: AUTH_AUDIT_ID, action, actor: `ip:${ip}`, detail });
  } catch {
    /* swallow */
  }
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const ip = clientIp(req.headers, env.trustedProxyHops);

  const secret = env.sessionSecret;
  const passcode = env.dashboardPasscode;
  if (!secret || !passcode) {
    return NextResponse.json(
      { error: "server not configured" },
      { status: 500 },
    );
  }

  const deviceId = verifyDeviceToken(req.cookies.get(DEVICE_COOKIE)?.value, secret);
  const client: LoginClient = { ip, deviceId };

  const rate = checkRateLimit(client);
  if (!rate.allowed) {
    await audit("login_fail", ip, "rate_limited");
    return NextResponse.json(
      { error: "too many attempts" },
      { status: 429, headers: { "Retry-After": String(Math.ceil(rate.retryAfterMs / 1000)) } },
    );
  }

  let submitted = "";
  try {
    const body = (await req.json()) as { passcode?: unknown };
    submitted = typeof body.passcode === "string" ? body.passcode : "";
  } catch {
    submitted = "";
  }

  const ok = submitted.length > 0 && constantTimeEqual(submitted, passcode);
  if (!ok) {
    const { globalLimitReached } = recordFailure(client);
    await audit("login_fail", ip);
    if (globalLimitReached) {
      // Sustained hits here mean someone is guessing the passcode; alert on it.
      console.warn(
        JSON.stringify({ event: "login_global_limit_reached", ts: new Date().toISOString() }),
      );
      await audit("login_fail", ip, "global_limit_reached");
    }
    return NextResponse.json({ error: "invalid passcode" }, { status: 401 });
  }

  recordSuccess(client);
  const { token } = signSession("facilitator", secret);
  await audit("login_ok", ip);

  const res = NextResponse.json({ ok: true });
  res.cookies.set(sessionCookie(token));
  res.cookies.set(deviceCookie(signDeviceToken(deviceId ?? newDeviceId(), secret)));
  return res;
}
