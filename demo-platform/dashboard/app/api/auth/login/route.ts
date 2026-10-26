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
import { DEVICE_COOKIE, deviceCookie, newDeviceId, signDeviceToken, verifyDeviceToken } from "@/lib/device";
import { appendAudit } from "@/lib/control";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AUTH_AUDIT_ID = "_auth";
const CI_KEY_HEADER = "x-ops-ci-key";

async function audit(
  action: "login_ok" | "login_fail" | "global_brake_engaged",
  ip: string,
  detail?: string,
) {
  // Best-effort — never let an audit write failure block the auth decision,
  // and never include the passcode in `detail`.
  try {
    await appendAudit({ tenantId: AUTH_AUDIT_ID, action, actor: `ip:${ip}`, detail });
  } catch {
    /* swallow */
  }
}

function loginClient(req: NextRequest, ip: string, secret: string): LoginClient {
  const ciKey = env.dashboardCiKey;
  const presented = req.headers.get(CI_KEY_HEADER);
  if (ciKey && presented && constantTimeEqual(presented, ciKey)) {
    return { lane: "ci", key: "ci" };
  }
  const deviceId = verifyDeviceToken(req.cookies.get(DEVICE_COOKIE)?.value, secret);
  if (deviceId) return { lane: "device", key: `device:${deviceId}` };
  return { lane: "ip", key: `ip:${ip}` };
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function POST(req: NextRequest): Promise<NextResponse> {
  const ip = clientIp(req.headers);

  const secret = env.sessionSecret;
  const passcode = env.dashboardPasscode;
  if (!secret || !passcode) {
    return NextResponse.json(
      { error: "server not configured" },
      { status: 500 },
    );
  }

  // Validate before touching the limiter so empty/malformed bodies cannot
  // reserve global queue slots.
  let submitted = "";
  try {
    const body = (await req.json()) as { passcode?: unknown };
    submitted = typeof body.passcode === "string" ? body.passcode : "";
  } catch {
    submitted = "";
  }
  if (!submitted) {
    return NextResponse.json({ error: "passcode required" }, { status: 400 });
  }

  const client = loginClient(req, ip, secret);
  const rate = checkRateLimit(client);
  if (!rate.allowed) {
    await audit("login_fail", ip, `rate_limited:${rate.reason}:${client.lane}`);
    return NextResponse.json(
      { error: "too many attempts" },
      { status: 429, headers: { "Retry-After": String(Math.max(1, Math.ceil(rate.retryAfterMs / 1000))) } },
    );
  }

  // Global brake: anonymous attempts wait for their queue slot instead of
  // being refused, so a facilitator still gets in while an attack is running.
  if (rate.delayMs > 0) await sleep(rate.delayMs);

  const ok = constantTimeEqual(submitted, passcode);
  if (!ok) {
    const engaged = recordFailure(client);
    await audit("login_fail", ip, client.lane === "ip" ? undefined : client.lane);
    if (engaged) {
      console.warn("login_global_brake_engaged: anonymous logins are now queued");
      await audit("global_brake_engaged", ip);
    }
    return NextResponse.json({ error: "invalid passcode" }, { status: 401 });
  }

  recordSuccess(client);
  const { token } = signSession("facilitator", secret);
  await audit("login_ok", ip, client.lane === "ip" ? undefined : client.lane);

  const res = NextResponse.json({ ok: true });
  res.cookies.set(sessionCookie(token));
  const deviceId = client.lane === "device" ? client.key.slice("device:".length) : newDeviceId();
  res.cookies.set(deviceCookie(signDeviceToken(deviceId, secret)));
  return res;
}
