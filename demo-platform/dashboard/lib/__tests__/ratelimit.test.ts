import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import {
  GLOBAL_BRAKE_THRESHOLD,
  GLOBAL_MAX_SPACING_MS,
  GLOBAL_MAX_WAIT_MS,
  MAX_ATTEMPTS,
  checkRateLimit,
  globalSpacingMs,
  recordFailure,
  recordSuccess,
  resetRateLimits,
  type LoginClient,
} from "../ratelimit";

const T0 = 1_000_000_000;
const anon = (n: number): LoginClient => ({ lane: "ip", key: `ip:203.0.113.${n}` });

// Failures that have already landed in the window, from rotating (spoofed) IPs.
function floodGlobal(count: number, now: number): void {
  for (let i = 0; i < count; i += 1) recordFailure(anon(i), now);
}

beforeEach(() => resetRateLimits());

test("21 wrong passcodes do not refuse a fresh client; it is delayed, not locked out", () => {
  // The finding's exploit, end to end through the limiter.
  for (let i = 0; i <= GLOBAL_BRAKE_THRESHOLD; i += 1) {
    const c = anon(i);
    assert.equal(checkRateLimit(c, T0).allowed, true);
    recordFailure(c, T0);
  }
  const r = checkRateLimit(anon(200), T0 + 1);
  assert.equal(r.allowed, true);
  assert.ok(r.delayMs <= GLOBAL_MAX_WAIT_MS);
});

test("the global brake spaces anonymous attempts and grows with failures", () => {
  assert.equal(globalSpacingMs(GLOBAL_BRAKE_THRESHOLD - 1), 0);
  assert.ok(globalSpacingMs(GLOBAL_BRAKE_THRESHOLD) > 0);
  assert.ok(globalSpacingMs(GLOBAL_BRAKE_THRESHOLD + 10) > globalSpacingMs(GLOBAL_BRAKE_THRESHOLD));
  assert.equal(globalSpacingMs(10_000), GLOBAL_MAX_SPACING_MS);

  floodGlobal(GLOBAL_BRAKE_THRESHOLD + 30, T0);
  const first = checkRateLimit(anon(300), T0);
  const second = checkRateLimit(anon(301), T0);
  assert.equal(first.delayMs, 0);
  assert.equal(second.delayMs, GLOBAL_MAX_SPACING_MS);
});

test("anonymous requests are refused only once the queue exceeds the max wait", () => {
  floodGlobal(GLOBAL_BRAKE_THRESHOLD + 30, T0);
  const queued = Math.floor(GLOBAL_MAX_WAIT_MS / GLOBAL_MAX_SPACING_MS) + 1;
  for (let i = 0; i < queued; i += 1) {
    assert.equal(checkRateLimit(anon(400 + i), T0).allowed, true, `queued #${i}`);
  }
  const over = checkRateLimit(anon(999), T0);
  assert.equal(over.allowed, false);
  assert.equal(over.reason, "global_queue_full");
  // The queue drains with time.
  assert.equal(checkRateLimit(anon(998), T0 + GLOBAL_MAX_WAIT_MS).allowed, true);
});

test("CI and trusted-device lanes skip the global brake entirely", () => {
  floodGlobal(GLOBAL_BRAKE_THRESHOLD + 30, T0);
  for (let i = 0; i < 20; i += 1) checkRateLimit(anon(500 + i), T0); // fill the queue
  assert.equal(checkRateLimit(anon(600), T0).allowed, false);

  const ci = checkRateLimit({ lane: "ci", key: "ci" }, T0);
  assert.deepEqual([ci.allowed, ci.delayMs], [true, 0]);
  const dev = checkRateLimit({ lane: "device", key: "device:abc" }, T0);
  assert.deepEqual([dev.allowed, dev.delayMs], [true, 0]);
});

test("per-client limit and backoff still apply in every lane", () => {
  for (const c of [anon(1), { lane: "ci", key: "ci" } as LoginClient]) {
    let now = T0;
    for (let i = 0; i < MAX_ATTEMPTS; i += 1) {
      const r = checkRateLimit(c, now);
      assert.equal(r.allowed, true);
      recordFailure(c, now);
      const early = checkRateLimit(c, now + 1);
      assert.equal(early.allowed, false);
      now += 60_000;
    }
    const r = checkRateLimit(c, now);
    assert.equal(r.allowed, false);
    assert.equal(r.reason, "client_limit");
  }
});

test("a successful login clears only the caller's bucket, not attack pressure", () => {
  floodGlobal(GLOBAL_BRAKE_THRESHOLD, T0);
  const ci: LoginClient = { lane: "ci", key: "ci" };
  recordFailure(ci, T0);
  recordSuccess(ci);
  assert.equal(checkRateLimit(ci, T0 + 1).allowed, true);
  checkRateLimit(anon(700), T0 + 1);
  assert.ok(checkRateLimit(anon(701), T0 + 1).delayMs > 0);
});

test("recordFailure reports the brake engaging exactly once per window", () => {
  const engaged: boolean[] = [];
  for (let i = 0; i < GLOBAL_BRAKE_THRESHOLD + 5; i += 1) engaged.push(recordFailure(anon(i), T0));
  assert.equal(engaged.filter(Boolean).length, 1);
  assert.equal(engaged.indexOf(true), GLOBAL_BRAKE_THRESHOLD - 1);
});
