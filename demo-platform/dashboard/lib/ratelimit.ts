// In-memory login rate limiter for the single shared facilitator passcode.
// Per-pod state (adequate for the single-replica ops dashboard; a distributed
// limiter would move this into the control table).
//
// Each attempt belongs to a lane:
//
//   - device: the browser presented a valid signed `ow_ops_device` cookie
//     (issued only after a correct passcode, see lib/device.ts).
//   - ci:     the request carried the pre-shared `DASHBOARD_CI_KEY` in the
//     `x-ops-ci-key` header (the CD pipeline's tenant.sh).
//   - ip:     everything else, keyed on X-Forwarded-For / X-Real-IP. Those
//     headers are attacker-controllable, so this key is best effort.
//
// Layers:
//
//   1. Per-lane bucket: max 5 failures / key / 15 min, with exponential backoff
//      between failures. Device and CI keys cannot be forged, so for those
//      lanes this is a real per-client limit.
//   2. Global brake (anonymous `ip` lane only): once the failures in the window
//      cross GLOBAL_BRAKE_THRESHOLD, anonymous attempts are no longer refused
//      outright. They are queued: each one waits for a global slot, and the
//      spacing between slots doubles every GLOBAL_BRAKE_STEP failures, up to
//      GLOBAL_MAX_SPACING_MS. This caps the brute-force rate across all
//      spoofed IPs, but a correct passcode from a fresh client still gets
//      through after a delay. A request is refused (429) only when the queue
//      is already more than GLOBAL_MAX_WAIT_MS long, which takes a sustained
//      flood rather than 20 requests every 15 minutes.
//
// Trusted lanes skip the global brake entirely, so an anonymous flood cannot
// lock out facilitators who have signed in before or the CD pipeline.

export const WINDOW_MS = 15 * 60 * 1000;
export const MAX_ATTEMPTS = 5;
export const BASE_BACKOFF_MS = 1000;
export const GLOBAL_BRAKE_THRESHOLD = 20;
export const GLOBAL_BRAKE_STEP = 5;
export const GLOBAL_BASE_SPACING_MS = 250;
export const GLOBAL_MAX_SPACING_MS = 2000;
export const GLOBAL_MAX_WAIT_MS = 30_000;
const MAX_TRACKED_KEYS = 10_000;

export type LoginLane = "ip" | "device" | "ci";

export interface LoginClient {
  lane: LoginLane;
  key: string;
}

interface Bucket {
  count: number;
  windowStart: number;
  lastAttempt: number;
}

const buckets = new Map<string, Bucket>();
let globalBucket: Bucket = { count: 0, windowStart: 0, lastAttempt: 0 };
let nextGlobalSlot = 0;

export interface RateResult {
  allowed: boolean;
  // Milliseconds the caller must wait before the next attempt is permitted.
  retryAfterMs: number;
  remaining: number;
  // When allowed: milliseconds to hold the request before checking the
  // passcode (the global brake's queue position). 0 when the brake is off.
  delayMs: number;
  reason?: "client_limit" | "client_backoff" | "global_queue_full";
}

function roll(b: Bucket, now: number): Bucket {
  if (now - b.windowStart > WINDOW_MS) return { count: 0, windowStart: now, lastAttempt: 0 };
  return b;
}

/** Spacing between anonymous attempts for a given number of global failures. */
export function globalSpacingMs(failures: number): number {
  if (failures < GLOBAL_BRAKE_THRESHOLD) return 0;
  const steps = Math.floor((failures - GLOBAL_BRAKE_THRESHOLD) / GLOBAL_BRAKE_STEP);
  return Math.min(GLOBAL_BASE_SPACING_MS * 2 ** Math.min(steps, 30), GLOBAL_MAX_SPACING_MS);
}

export function globalBrakeActive(now: number = Date.now()): boolean {
  globalBucket = roll(globalBucket, now);
  return globalBucket.count >= GLOBAL_BRAKE_THRESHOLD;
}

export function checkRateLimit(client: LoginClient, now: number = Date.now()): RateResult {
  let b = buckets.get(client.key);
  if (!b || now - b.windowStart > WINDOW_MS) {
    b = { count: 0, windowStart: now, lastAttempt: 0 };
  }

  if (b.count >= MAX_ATTEMPTS) {
    return {
      allowed: false,
      retryAfterMs: b.windowStart + WINDOW_MS - now,
      remaining: 0,
      delayMs: 0,
      reason: "client_limit",
    };
  }

  if (b.count > 0) {
    const backoff = BASE_BACKOFF_MS * 2 ** (b.count - 1);
    const waited = now - b.lastAttempt;
    if (waited < backoff) {
      return {
        allowed: false,
        retryAfterMs: backoff - waited,
        remaining: MAX_ATTEMPTS - b.count,
        delayMs: 0,
        reason: "client_backoff",
      };
    }
  }

  let delayMs = 0;
  if (client.lane === "ip" && globalBrakeActive(now)) {
    const slot = Math.max(now, nextGlobalSlot);
    const wait = slot - now;
    if (wait > GLOBAL_MAX_WAIT_MS) {
      return {
        allowed: false,
        retryAfterMs: wait - GLOBAL_MAX_WAIT_MS,
        remaining: MAX_ATTEMPTS - b.count,
        delayMs: 0,
        reason: "global_queue_full",
      };
    }
    nextGlobalSlot = slot + globalSpacingMs(globalBucket.count);
    delayMs = wait;
  }

  return { allowed: true, retryAfterMs: 0, remaining: MAX_ATTEMPTS - b.count, delayMs };
}

function remember(key: string, b: Bucket): void {
  buckets.delete(key);
  buckets.set(key, b);
  // Map preserves insertion order, so the first key is the least recently used.
  while (buckets.size > MAX_TRACKED_KEYS) {
    const oldest = buckets.keys().next().value;
    if (oldest === undefined) break;
    buckets.delete(oldest);
  }
}

/**
 * Record a failed attempt on the caller's bucket and the global window.
 * Returns true exactly once per window: when this failure engages the brake.
 */
export function recordFailure(client: LoginClient, now: number = Date.now()): boolean {
  const prev = buckets.get(client.key);
  const b = prev && now - prev.windowStart <= WINDOW_MS
    ? prev
    : { count: 0, windowStart: now, lastAttempt: 0 };
  b.count += 1;
  b.lastAttempt = now;
  remember(client.key, b);

  globalBucket = roll(globalBucket, now);
  if (globalBucket.count === 0) globalBucket.windowStart = now;
  globalBucket.count += 1;
  globalBucket.lastAttempt = now;
  return globalBucket.count === GLOBAL_BRAKE_THRESHOLD;
}

/**
 * Clear the caller's own bucket on a successful login. The global window is
 * left alone: it measures attack pressure, and one facilitator signing in does
 * not mean the attack stopped.
 */
export function recordSuccess(client: LoginClient): void {
  buckets.delete(client.key);
}

/** Test hook: forget all limiter state. */
export function resetRateLimits(): void {
  buckets.clear();
  globalBucket = { count: 0, windowStart: 0, lastAttempt: 0 };
  nextGlobalSlot = 0;
}

export function clientIp(headers: Headers): string {
  const xff = headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }
  return headers.get("x-real-ip") || "unknown";
}
