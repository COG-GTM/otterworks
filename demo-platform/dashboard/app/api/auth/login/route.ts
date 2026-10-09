import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { constantTimeEqual, signSession, sessionCookie } from "@/lib/session";
import { checkRateLimit, clientIp, recordFailure, recordSuccess } from "@/lib/ratelimit";
import { appendAudit } from "@/lib/control";
import {
  formatLoginRejectionDetail,
  LoginRejectionAggregator,
  mergeRetainedDetail,
  type LoginRejection,
} from "@/lib/audit-policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const AUTH_AUDIT_ID = "_auth";

// This route is public, so a rejected attempt must never cost a durable write
// of its own: rejections (bad passcode and 429s alike) are counted in memory
// and written as one aggregate `login_fail` item per flush interval.
const rejections = new LoginRejectionAggregator(env.loginAuditFlushSeconds * 1000);
let flushTimer: ReturnType<typeof setTimeout> | null = null;
// Aggregate whose write failed; retried (merged with the next one) each interval.
let retainedDetail: string | null = null;

async function writeAudit(
  action: "login_ok" | "login_fail",
  actor: string,
  detail?: string,
): Promise<boolean> {
  // Best-effort — never let an audit write failure block the auth decision,
  // and never include the passcode in `detail`.
  try {
    await appendAudit({ tenantId: AUTH_AUDIT_ID, action, actor, detail });
    return true;
  } catch {
    return false;
  }
}

function scheduleFlush(): void {
  if (!flushTimer) {
    flushTimer = setTimeout(() => void flushRejections(), rejections.flushIntervalMs);
  }
}

async function flushRejections(now: number = Date.now()): Promise<void> {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  const summary = rejections.drain(now);
  const detail = mergeRetainedDetail(retainedDetail, summary && formatLoginRejectionDetail(summary));
  if (!detail) return;
  retainedDetail = null;
  if (!(await writeAudit("login_fail", "anonymous", detail))) {
    retainedDetail = mergeRetainedDetail(detail, retainedDetail);
    scheduleFlush();
  }
}

function recordRejection(ip: string, reason: LoginRejection): void {
  const now = Date.now();
  if (rejections.due(now)) void flushRejections(now);
  rejections.record(ip, reason, now);
  scheduleFlush();
}

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

  const rate = checkRateLimit(ip);
  if (!rate.allowed) {
    recordRejection(ip, "rate_limited");
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
    recordFailure(ip);
    recordRejection(ip, "invalid_passcode");
    return NextResponse.json({ error: "invalid passcode" }, { status: 401 });
  }

  recordSuccess(ip);
  const { token } = signSession("facilitator", secret);
  await flushRejections();
  await writeAudit("login_ok", `ip:${ip}`);

  const res = NextResponse.json({ ok: true });
  res.cookies.set(sessionCookie(token));
  return res;
}
