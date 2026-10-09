import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import {
  GLOBAL_MAX_ATTEMPTS,
  MAX_ATTEMPTS,
  WINDOW_MS,
  checkRateLimit,
  clientIp,
  globalLimitActive,
  recordFailure,
  recordSuccess,
  resetRateLimitState,
  type LoginClient,
} from "../ratelimit";

const T0 = 1_000_000_000_000;
// Comfortably past the longest per-client backoff (2^(MAX_ATTEMPTS-2) s).
const STEP = 60_000;

beforeEach(() => resetRateLimitState());

// Fail once from each of `n` distinct attacker IPs, as an anonymous flood would.
function flood(n: number, now: number): void {
  for (let i = 0; i < n; i += 1) {
    const c: LoginClient = { ip: `203.0.113.${i}` };
    assert.equal(checkRateLimit(c, now).allowed, true);
    recordFailure(c, now);
  }
}

test("global ceiling no longer refuses a facilitator's first attempt", () => {
  flood(GLOBAL_MAX_ATTEMPTS + 5, T0);
  assert.equal(globalLimitActive(T0), true);

  // Before the fix every caller got a 429 here, so the correct passcode could
  // never be compared.
  const facilitator: LoginClient = { ip: "198.51.100.7" };
  assert.equal(checkRateLimit(facilitator, T0 + 1).allowed, true);
});

test("attacker cannot sustain a lockout by refilling the bucket every window", () => {
  const facilitator: LoginClient = { ip: "198.51.100.7" };
  for (let w = 0; w < 4; w += 1) {
    const start = T0 + w * (WINDOW_MS + 1);
    flood(GLOBAL_MAX_ATTEMPTS, start);
    assert.equal(globalLimitActive(start), true);
    assert.equal(checkRateLimit(facilitator, start + 1).allowed, true);
  }
});

test("trusted device is exempt from global pressure even after its own typo", () => {
  flood(GLOBAL_MAX_ATTEMPTS, T0);
  const device: LoginClient = { ip: "203.0.113.1", deviceId: "dev-a" };
  recordFailure(device, T0);
  assert.equal(checkRateLimit(device, T0 + STEP).allowed, true);
});

test("device failures do not count toward global pressure", () => {
  for (let i = 0; i < GLOBAL_MAX_ATTEMPTS; i += 1) {
    recordFailure({ ip: "198.51.100.7", deviceId: `dev-${i}` }, T0);
  }
  assert.equal(globalLimitActive(T0), false);
});

test("under global pressure an untrusted IP gets one attempt per window", () => {
  flood(GLOBAL_MAX_ATTEMPTS, T0);
  const repeat: LoginClient = { ip: "203.0.113.0" };
  const r = checkRateLimit(repeat, T0 + STEP);
  assert.equal(r.allowed, false);
  assert.ok(r.retryAfterMs > 0 && r.retryAfterMs <= WINDOW_MS);
  // The IP's own window expiring restores it.
  assert.equal(checkRateLimit(repeat, T0 + WINDOW_MS + 1).allowed, true);
});

test("without global pressure the per-client limit and backoff still apply", () => {
  const c: LoginClient = { ip: "198.51.100.9" };
  let now = T0;
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) {
    assert.equal(checkRateLimit(c, now).allowed, true);
    recordFailure(c, now);
    assert.equal(checkRateLimit(c, now + 1).allowed, false, "backoff right after a failure");
    now += STEP;
  }
  assert.equal(checkRateLimit(c, now).allowed, false);
  assert.equal(checkRateLimit(c, T0 + WINDOW_MS + 1).allowed, true);
});

test("success clears the client's bucket but not global pressure", () => {
  flood(GLOBAL_MAX_ATTEMPTS, T0);
  const c: LoginClient = { ip: "203.0.113.3" };
  recordSuccess(c);
  assert.equal(checkRateLimit(c, T0 + 1).allowed, true);
  assert.equal(globalLimitActive(T0 + 1), true);
});

test("recordFailure reports the ceiling crossing exactly once per window", () => {
  const reached: number[] = [];
  for (let i = 0; i < GLOBAL_MAX_ATTEMPTS + 3; i += 1) {
    if (recordFailure({ ip: `203.0.113.${i}` }, T0).globalLimitReached) reached.push(i);
  }
  assert.deepEqual(reached, [GLOBAL_MAX_ATTEMPTS - 1]);
});

test("clientIp ignores client-supplied X-Forwarded-For entries", () => {
  const h = (init: Record<string, string>) => new Headers(init);
  assert.equal(clientIp(h({ "x-forwarded-for": "1.1.1.1, 2.2.2.2, 198.51.100.7" })), "198.51.100.7");
  assert.equal(clientIp(h({ "x-forwarded-for": "1.1.1.1, 10.0.0.5, 198.51.100.7" }), 2), "10.0.0.5");
  assert.equal(clientIp(h({ "x-forwarded-for": "198.51.100.7" }), 3), "198.51.100.7");
  assert.equal(clientIp(h({ "x-real-ip": "198.51.100.8" })), "198.51.100.8");
  assert.equal(clientIp(h({ "x-forwarded-for": "1.1.1.1", "x-real-ip": "198.51.100.8" }), 0), "198.51.100.8");
  assert.equal(clientIp(h({})), "unknown");
});
