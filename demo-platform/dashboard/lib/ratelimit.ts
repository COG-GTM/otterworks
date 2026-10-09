// In-memory login rate limiter for the single shared facilitator passcode.
// Two layers, both per-pod (adequate for a single-pod ops dashboard; a
// distributed limiter would move this into the control table):
//
//   1. Per-IP: max 5 attempts / IP / 15 min with exponential backoff. Best
//      effort only — the client IP is derived from X-Forwarded-For / X-Real-IP,
//      which are attacker-controllable, so this layer is for UX and honest
//      clients, NOT a security boundary.
//   2. Global: a hard ceiling on TOTAL failed attempts across ALL clients in
//      the window. This CANNOT be bypassed by rotating X-Forwarded-For, so it
//      is the actual brute-force guarantee. Trade-off: under active attack it
//      can briefly lock out legitimate facilitators; acceptable for a single
//      high-entropy passcode, and any successful login resets it immediately.

const WINDOW_MS = 15 * 60 * 1000;
const MAX_ATTEMPTS = 5;
const GLOBAL_MAX_ATTEMPTS = 20;
const BASE_BACKOFF_MS = 1000;
// Bounds per-IP state: the client IP comes from X-Forwarded-For, so an attacker
// can mint a new "IP" per request. The global ceiling still applies to all.
const MAX_TRACKED_IPS = 10_000;

interface Bucket {
  count: number;
  windowStart: number;
  lastAttempt: number;
}

const buckets = new Map<string, Bucket>();
let globalBucket: Bucket = { count: 0, windowStart: 0, lastAttempt: 0 };

export interface RateResult {
  allowed: boolean;
  // Milliseconds the caller must wait before the next attempt is permitted.
  retryAfterMs: number;
  remaining: number;
}

function roll(b: Bucket, now: number): Bucket {
  if (now - b.windowStart > WINDOW_MS) return { count: 0, windowStart: now, lastAttempt: 0 };
  return b;
}

export function checkRateLimit(ip: string, now: number = Date.now()): RateResult {
  // Global ceiling first — this is the guarantee that survives IP spoofing.
  globalBucket = roll(globalBucket, now);
  if (globalBucket.count >= GLOBAL_MAX_ATTEMPTS) {
    return {
      allowed: false,
      retryAfterMs: globalBucket.windowStart + WINDOW_MS - now,
      remaining: 0,
    };
  }

  // Read-only: a bucket is only created by recordFailure, so requests that
  // never fail (or are rejected here) cannot grow the map.
  const b = buckets.get(ip);
  if (!b || now - b.windowStart > WINDOW_MS) {
    return { allowed: true, retryAfterMs: 0, remaining: MAX_ATTEMPTS };
  }

  if (b.count >= MAX_ATTEMPTS) {
    return {
      allowed: false,
      retryAfterMs: b.windowStart + WINDOW_MS - now,
      remaining: 0,
    };
  }

  // Exponential backoff between successive failed attempts within the window.
  if (b.count > 0) {
    const backoff = BASE_BACKOFF_MS * 2 ** (b.count - 1);
    const waited = now - b.lastAttempt;
    if (waited < backoff) {
      return { allowed: false, retryAfterMs: backoff - waited, remaining: MAX_ATTEMPTS - b.count };
    }
  }

  return { allowed: true, retryAfterMs: 0, remaining: MAX_ATTEMPTS - b.count };
}

// Drop expired buckets; if every bucket is still live, drop the oldest
// (Map iteration is insertion order, and buckets are re-inserted on reset).
function evictBuckets(now: number): void {
  for (const [ip, b] of buckets) {
    if (now - b.windowStart > WINDOW_MS) buckets.delete(ip);
  }
  while (buckets.size >= MAX_TRACKED_IPS) {
    const oldest = buckets.keys().next().value;
    if (oldest === undefined) break;
    buckets.delete(oldest);
  }
}

/** Record a failed attempt (advances the backoff + count) on both layers. */
export function recordFailure(ip: string, now: number = Date.now()): void {
  let b = buckets.get(ip);
  if (!b || now - b.windowStart > WINDOW_MS) {
    b = { count: 0, windowStart: now, lastAttempt: 0 };
    buckets.delete(ip);
    if (buckets.size >= MAX_TRACKED_IPS) evictBuckets(now);
    buckets.set(ip, b);
  }
  b.count += 1;
  b.lastAttempt = now;

  globalBucket = roll(globalBucket, now);
  if (globalBucket.count === 0) globalBucket.windowStart = now;
  globalBucket.count += 1;
  globalBucket.lastAttempt = now;
}

/** Clear per-IP and global state on a successful login. */
export function recordSuccess(ip: string): void {
  buckets.delete(ip);
  globalBucket = { count: 0, windowStart: 0, lastAttempt: 0 };
}

export function clientIp(headers: Headers): string {
  const xff = headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }
  return headers.get("x-real-ip") || "unknown";
}

/** Number of per-IP buckets currently held (exposed for tests). */
export function trackedIpCount(): number {
  return buckets.size;
}

/** Clear all limiter state (tests only). */
export function resetRateLimit(): void {
  buckets.clear();
  globalBucket = { count: 0, windowStart: 0, lastAttempt: 0 };
}
