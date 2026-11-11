import { beforeAll, describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "@/middleware";
import { SESSION_COOKIE, signSession } from "@/lib/session";

const SECRET = "test-secret";

beforeAll(() => {
  process.env.SESSION_SECRET = SECRET;
});

function request(path: string, headers: Record<string, string>, withCookie = true) {
  const all: Record<string, string> = { host: "ops.otterworks.app", ...headers };
  if (withCookie) all.cookie = `${SESSION_COOKIE}=${signSession("facilitator", SECRET).token}`;
  return new NextRequest(`https://ops.otterworks.app${path}`, { method: "POST", headers: all });
}

const forged = {
  origin: "https://t-attacker.demo.otterworks.app",
  "sec-fetch-site": "same-site",
  "content-type": "text/plain;charset=UTF-8",
};

describe("middleware CSRF gate", () => {
  it("refuses a forged mutation that carries a valid session", async () => {
    for (const path of ["/api/tenants/main/persist", "/api/tenants/main/checkin"]) {
      const res = await middleware(request(path, forged));
      expect(res.status).toBe(403);
    }
  });

  it("refuses forged requests to public mutation paths", async () => {
    const res = await middleware(request("/api/auth/logout", forged, false));
    expect(res.status).toBe(403);
  });

  it("passes a same-origin JSON mutation through", async () => {
    const res = await middleware(
      request("/api/tenants/main/checkin", {
        origin: "https://ops.otterworks.app",
        "sec-fetch-site": "same-origin",
        "content-type": "application/json",
      }),
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("x-middleware-next")).toBe("1");
  });
});
