import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  checkRateLimit,
  recordFailure,
  recordSuccess,
  resetRateLimit,
  trackedIpCount,
} from "../lib/ratelimit.ts";

const WINDOW_MS = 15 * 60 * 1000;

beforeEach(() => resetRateLimit());

test("checking the limit never allocates per-IP state", () => {
  for (let i = 0; i < 50_000; i++) {
    assert.equal(checkRateLimit(`spoofed-${i}`, 1_000 + i).allowed, true);
  }
  assert.equal(trackedIpCount(), 0);
});

test("failures still lock out an IP and back off exponentially", () => {
  const ip = "198.51.100.7";
  let now = 1_000_000;
  recordFailure(ip, now);
  assert.equal(checkRateLimit(ip, now + 500).allowed, false);
  assert.equal(checkRateLimit(ip, now + 1_000).allowed, true);

  for (let i = 1; i < 5; i++) {
    now += 60_000;
    recordFailure(ip, now);
  }
  const locked = checkRateLimit(ip, now + 60_000);
  assert.equal(locked.allowed, false);
  assert.equal(locked.remaining, 0);
  assert.equal(checkRateLimit(ip, 1_000_000 + WINDOW_MS + 1).allowed, true);
});

test("the global ceiling holds even when every failure uses a fresh IP", () => {
  const now = 2_000_000;
  for (let i = 0; i < 20; i++) recordFailure(`10.0.0.${i}`, now + i);
  const r = checkRateLimit("10.9.9.9", now + 100);
  assert.equal(r.allowed, false);
  assert.ok(r.retryAfterMs > 0);
});

test("per-IP state is capped and expired buckets are evicted first", () => {
  let now = 3_000_000;
  for (let i = 0; i < 10_000; i++) {
    recordFailure(`old-${i}`, now);
    recordSuccess("reset-global"); // keep the global ceiling out of the way
  }
  assert.equal(trackedIpCount(), 10_000);

  now += WINDOW_MS + 1;
  recordFailure("fresh", now);
  assert.equal(trackedIpCount(), 1);

  for (let i = 0; i < 15_000; i++) {
    recordFailure(`live-${i}`, now);
    recordSuccess("reset-global");
  }
  assert.ok(trackedIpCount() <= 10_000);
});

test("a success clears that IP's bucket", () => {
  recordFailure("192.0.2.5", 5_000_000);
  recordSuccess("192.0.2.5");
  assert.equal(trackedIpCount(), 0);
  assert.equal(checkRateLimit("192.0.2.5", 5_000_001).allowed, true);
});
