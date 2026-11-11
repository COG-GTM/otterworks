// In-memory login rate limiter for the single shared facilitator passcode.
// Two layers, both per-pod (adequate for a single-pod ops dashboard; a
// distributed limiter would move this into the control table):
//
//   1. Per-IP: max 5 attempts / IP / 15 min with exponential backoff. Best
//      effort only — the client IP is derived from X-Forwarded-For / X-Real-IP,
//      which are attacker-controllable, so this layer is for UX and honest
//      clients, NOT a security boundary.
//   2. Global: a brake on the TOTAL attempt rate across ALL clients. It cannot
//      be bypassed by rotating X-Forwarded-For, so it is the actual brute-force
//      guarantee. It paces rather than refuses: after GLOBAL_FREE_FAILURES
//      failures, attempts are serialised into global slots spaced by an
//      exponential backoff (capped at GLOBAL_MAX_DELAY_MS), and each caller is
//      held server-side until its slot. A legitimate login during an attack is
//      therefore delayed, not locked out; only a caller whose slot is more than
//      GLOBAL_MAX_WAIT_MS away is refused. Any successful login resets it.

const WINDOW_MS = 15 * 60 * 1000;
const MAX_ATTEMPTS = 5;
const BASE_BACKOFF_MS = 1000;

const GLOBAL_FREE_FAILURES = 20;
const GLOBAL_BASE_DELAY_MS = 1000;
const GLOBAL_MAX_DELAY_MS = 10_000;
const GLOBAL_MAX_WAIT_MS = 30_000;

interface Bucket {
  count: number;
  windowStart: number;
  lastAttempt: number;
}

interface GlobalState {
  // Failures since the last quiet period of WINDOW_MS with no failure at all,
  // so a sustained attack cannot reset the backoff by outlasting a window.
  failures: number;
  lastFailure: number;
  // Earliest time the next paced attempt may be evaluated.
  nextSlot: number;
}

const buckets = new Map<string, Bucket>();
let globalState: GlobalState = { failures: 0, lastFailure: 0, nextSlot: 0 };

export interface RateResult {
  allowed: boolean;
  // Milliseconds the caller must wait before the next attempt is permitted.
  retryAfterMs: number;
  remaining: number;
  // When allowed: milliseconds the server must hold this attempt before
  // evaluating it (its global slot).
  delayMs: number;
}

function rollGlobal(now: number): void {
  if (globalState.failures > 0 && now - globalState.lastFailure > WINDOW_MS) {
    globalState = { failures: 0, lastFailure: 0, nextSlot: 0 };
  }
}

function globalSpacingMs(now: number): number {
  rollGlobal(now);
  const over = globalState.failures - GLOBAL_FREE_FAILURES;
  if (over < 0) return 0;
  return Math.min(GLOBAL_BASE_DELAY_MS * 2 ** over, GLOBAL_MAX_DELAY_MS);
}

export function checkRateLimit(ip: string, now: number = Date.now()): RateResult {
  let b = buckets.get(ip);
  if (!b || now - b.windowStart > WINDOW_MS) {
    b = { count: 0, windowStart: now, lastAttempt: 0 };
    buckets.set(ip, b);
  }

  if (b.count >= MAX_ATTEMPTS) {
    return {
      allowed: false,
      retryAfterMs: b.windowStart + WINDOW_MS - now,
      remaining: 0,
      delayMs: 0,
    };
  }

  // Exponential backoff between successive failed attempts within the window.
  if (b.count > 0) {
    const backoff = BASE_BACKOFF_MS * 2 ** (b.count - 1);
    const waited = now - b.lastAttempt;
    if (waited < backoff) {
      return {
        allowed: false,
        retryAfterMs: backoff - waited,
        remaining: MAX_ATTEMPTS - b.count,
        delayMs: 0,
      };
    }
  }

  const remaining = MAX_ATTEMPTS - b.count;
  const spacing = globalSpacingMs(now);
  if (spacing === 0) return { allowed: true, retryAfterMs: 0, remaining, delayMs: 0 };

  // Reserve the next global slot. Reservation is synchronous, so concurrent
  // requests on this single-threaded pod cannot share a slot.
  const slot = Math.max(now, globalState.nextSlot);
  const wait = slot - now;
  if (wait > GLOBAL_MAX_WAIT_MS) {
    return { allowed: false, retryAfterMs: wait - GLOBAL_MAX_WAIT_MS, remaining, delayMs: 0 };
  }
  globalState.nextSlot = slot + spacing;
  return { allowed: true, retryAfterMs: 0, remaining, delayMs: wait };
}

/** Record a failed attempt (advances the backoff + count) on both layers. */
export function recordFailure(ip: string, now: number = Date.now()): void {
  const b = buckets.get(ip) ?? { count: 0, windowStart: now, lastAttempt: 0 };
  b.count += 1;
  b.lastAttempt = now;
  buckets.set(ip, b);

  rollGlobal(now);
  globalState.failures += 1;
  globalState.lastFailure = now;
}

/** Clear per-IP and global state on a successful login. */
export function recordSuccess(ip: string): void {
  buckets.delete(ip);
  globalState = { failures: 0, lastFailure: 0, nextSlot: 0 };
}

export function clientIp(headers: Headers): string {
  const xff = headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }
  return headers.get("x-real-ip") || "unknown";
}
