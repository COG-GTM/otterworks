import { after, before, beforeEach, describe, mock, test } from "node:test";
import assert from "node:assert/strict";
import { DynamoDBDocumentClient, PutCommand } from "@aws-sdk/lib-dynamodb";
import { NextRequest } from "next/server";

process.env.DASHBOARD_PASSCODE = "correct-horse";
process.env.SESSION_SECRET = "test-session-secret";
process.env.AWS_REGION = "us-east-1";

const puts: Record<string, unknown>[] = [];
const send = mock.method(DynamoDBDocumentClient.prototype, "send", async (cmd: unknown) => {
  if (cmd instanceof PutCommand) puts.push(cmd.input.Item as Record<string, unknown>);
  return {};
});
after(() => send.mock.restore());

type Route = typeof import("@/app/api/auth/login/route");
let POST: Route["POST"];
let recordSuccess: (ip: string) => void;
let AUDIT_RETENTION_SECONDS: number;

// Imported after the env and the DynamoDB stub are in place.
before(async () => {
  ({ POST } = await import("@/app/api/auth/login/route"));
  ({ recordSuccess } = await import("@/lib/ratelimit"));
  ({ AUDIT_RETENTION_SECONDS } = await import("@/lib/control"));
});

function login(passcode: string, ip: string) {
  return POST(
    new NextRequest("http://localhost/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": ip },
      body: JSON.stringify({ passcode }),
    }),
  );
}

describe("POST /api/auth/login audit writes", () => {
  beforeEach(() => {
    puts.length = 0;
    recordSuccess("reset");
  });

  test("failed attempt writes one audit item carrying a TTL", async () => {
    const before = Math.floor(Date.now() / 1000);
    const res = await login("wrong", "198.51.100.1");
    assert.equal(res.status, 401);
    assert.equal(puts.length, 1);
    const item = puts[0]!;
    assert.equal(item.PK, "AUDIT#_auth");
    assert.equal(item.action, "login_fail");
    const ttl = item.ttl as number;
    assert.equal(typeof ttl, "number");
    assert.ok(ttl >= before + AUDIT_RETENTION_SECONDS);
    assert.ok(ttl <= Math.floor(Date.now() / 1000) + AUDIT_RETENTION_SECONDS);
  });

  test("rate-limited requests write nothing", async () => {
    const first = await login("wrong", "198.51.100.2");
    assert.equal(first.status, 401);
    puts.length = 0;

    for (let i = 0; i < 50; i++) {
      const res = await login("wrong", "198.51.100.2");
      assert.equal(res.status, 429);
    }
    assert.equal(puts.length, 0);
  });

  test("successful login is audited with a TTL", async () => {
    const res = await login("correct-horse", "198.51.100.3");
    assert.equal(res.status, 200);
    assert.equal(puts.length, 1);
    assert.equal(puts[0]!.action, "login_ok");
    assert.equal(typeof puts[0]!.ttl, "number");
  });
});
