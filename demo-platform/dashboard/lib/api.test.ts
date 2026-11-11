import { beforeAll, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { withSession } from "@/lib/api";
import { SESSION_COOKIE, signSession } from "@/lib/session";

const SECRET = "test-secret";
const URL_ = "https://ops.otterworks.app/api/tenants/main/checkin";

beforeAll(() => {
  process.env.SESSION_SECRET = SECRET;
});

function request(headers: Record<string, string>, method = "POST") {
  const { token } = signSession("facilitator", SECRET);
  return new NextRequest(URL_, {
    method,
    headers: { host: "ops.otterworks.app", cookie: `${SESSION_COOKIE}=${token}`, ...headers },
  });
}

const ctx = { params: Promise.resolve({ id: "main" }) };

describe("withSession CSRF gate", () => {
  it("refuses a forged same-site POST before the handler runs", async () => {
    const handler = vi.fn(async () => NextResponse.json({ ok: true }));
    const res = await withSession(handler)(
      request({
        origin: "https://t-attacker.demo.otterworks.app",
        "sec-fetch-site": "same-site",
        "content-type": "text/plain;charset=UTF-8",
      }),
      ctx,
    );
    expect(res.status).toBe(403);
    expect(handler).not.toHaveBeenCalled();
  });

  it("runs the handler for a same-origin JSON POST", async () => {
    const handler = vi.fn(async () => NextResponse.json({ ok: true }));
    const res = await withSession(handler)(
      request({
        origin: "https://ops.otterworks.app",
        "sec-fetch-site": "same-origin",
        "content-type": "application/json",
      }),
      ctx,
    );
    expect(res.status).toBe(200);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("does not gate GET", async () => {
    const handler = vi.fn(async () => NextResponse.json({ ok: true }));
    const res = await withSession(handler)(
      request({ origin: "https://t-attacker.demo.otterworks.app", "sec-fetch-site": "same-site" }, "GET"),
      ctx,
    );
    expect(res.status).toBe(200);
  });
});
