// In-memory login rate limiter for the single shared facilitator passcode.
// Per-pod state (adequate for a single-pod ops dashboard; a distributed limiter
// would move this into the control table).
//
// Every attempt is keyed on a client:
//
//   - Trusted device: the browser presents a valid `ow_ops_device` cookie,
//     which is only ever issued after a correct passcode (lib/device.ts). It
//     gets its own bucket (5 attempts / 15 min with exponential backoff) and is
//     never affected by attacker-driven global pressure, so a facilitator who
//     has signed in from this browser before cannot be locked out by anyone
//     else. The cookie is HMAC-signed, so an attacker cannot mint one.
//   - Untrusted client: keyed on the client IP as seen by the trusted ingress
//     (see clientIp), 5 attempts / IP / 15 min with exponential backoff. The
//     limit is checked before the passcode is compared.
//
// Global pressure: failed attempts from untrusted clients are also counted
// across ALL clients. Past GLOBAL_MAX_ATTEMPTS in a window the limiter does NOT
// deny everyone (that let one anonymous client lock every facilitator out
// indefinitely). Instead it tightens to one attempt per untrusted IP per
// window: any IP that has already failed is refused until the window ends,
// while a fresh IP still gets its attempt and trusted devices are unaffected.
// Crossing the ceiling is reported so it can be alerted on.

export const WINDOW_MS = 15 * 60 * 1000;
export const MAX_ATTEMPTS = 5;
export const GLOBAL_MAX_ATTEMPTS = 20;
const BASE_BACKOFF_MS = 1000;
// Upper bound on tracked clients; expired buckets are swept first, then the
// oldest are evicted, so memory stays bounded under a flood of distinct IPs.
const MAX_BUCKETS = 10_000;

interface Bucket {
  count: number;
  windowStart: number;
  lastAttempt: number;
}

export interface LoginClient {
  ip: string;
  // Device id from a verified `ow_ops_device` cookie, or null when absent/invalid.
  deviceId?: string | null;
}

export interface RateResult {
  allowed: boolean;
  // Milliseconds the caller must wait before the next attempt is permitted.
  retryAfterMs: number;
  remaining: number;
}

export interface FailureResult {
  // True exactly once per window: on the failure that reaches the global ceiling.
  globalLimitReached: boolean;
}

const buckets = new Map<string, Bucket>();
let globalBucket: Bucket = { count: 0, windowStart: 0, lastAttempt: 0 };

function keyFor(client: LoginClient): string {
  return client.deviceId ? `device:${client.deviceId}` : `ip:${client.ip}`;
}

function expired(b: Bucket, now: number): boolean {
  return now - b.windowStart > WINDOW_MS;
}

function roll(b: Bucket, now: number): Bucket {
  if (expired(b, now)) return { count: 0, windowStart: now, lastAttempt: 0 };
  return b;
}

function makeRoom(now: number): void {
  if (buckets.size < MAX_BUCKETS) return;
  for (const [k, b] of buckets) {
    if (expired(b, now)) buckets.delete(k);
  }
  // Map iteration is insertion order, so this evicts the oldest entries.
  for (const k of buckets.keys()) {
    if (buckets.size < MAX_BUCKETS) break;
    buckets.delete(k);
  }
}

function currentBucket(key: string, now: number): Bucket | undefined {
  const b = buckets.get(key);
  if (b && expired(b, now)) {
    buckets.delete(key);
    return undefined;
  }
  return b;
}

/** True while untrusted failures in the current window are at/over the ceiling. */
export function globalLimitActive(now: number = Date.now()): boolean {
  globalBucket = roll(globalBucket, now);
  return globalBucket.count >= GLOBAL_MAX_ATTEMPTS;
}

export function checkRateLimit(client: LoginClient, now: number = Date.now()): RateResult {
  const b = currentBucket(keyFor(client), now);
  if (!b || b.count === 0) {
    return { allowed: true, retryAfterMs: 0, remaining: MAX_ATTEMPTS };
  }

  const windowLeftMs = b.windowStart + WINDOW_MS - now;
  if (b.count >= MAX_ATTEMPTS) {
    return { allowed: false, retryAfterMs: windowLeftMs, remaining: 0 };
  }

  // Under global pressure an untrusted client that has already failed this
  // window gets no further attempts until its own window ends.
  if (!client.deviceId && globalLimitActive(now)) {
    return { allowed: false, retryAfterMs: windowLeftMs, remaining: 0 };
  }

  // Exponential backoff between successive failed attempts within the window.
  const backoff = BASE_BACKOFF_MS * 2 ** (b.count - 1);
  const waited = now - b.lastAttempt;
  if (waited < backoff) {
    return { allowed: false, retryAfterMs: backoff - waited, remaining: MAX_ATTEMPTS - b.count };
  }

  return { allowed: true, retryAfterMs: 0, remaining: MAX_ATTEMPTS - b.count };
}

/** Record a failed attempt for the client (and globally, for untrusted clients). */
export function recordFailure(client: LoginClient, now: number = Date.now()): FailureResult {
  const key = keyFor(client);
  let b = currentBucket(key, now);
  if (!b) {
    makeRoom(now);
    b = { count: 0, windowStart: now, lastAttempt: 0 };
    buckets.set(key, b);
  }
  b.count += 1;
  b.lastAttempt = now;

  if (client.deviceId) return { globalLimitReached: false };

  globalBucket = roll(globalBucket, now);
  if (globalBucket.count === 0) globalBucket.windowStart = now;
  globalBucket.count += 1;
  globalBucket.lastAttempt = now;
  return { globalLimitReached: globalBucket.count === GLOBAL_MAX_ATTEMPTS };
}

/**
 * Clear the client's own bucket on a successful login. Global pressure is left
 * alone: it measures attack traffic, and one facilitator signing in should not
 * hand an attacker a fresh budget.
 */
export function recordSuccess(client: LoginClient): void {
  buckets.delete(keyFor(client));
}

/** Test hook: drop all limiter state. */
export function resetRateLimitState(): void {
  buckets.clear();
  globalBucket = { count: 0, windowStart: 0, lastAttempt: 0 };
}

/**
 * Client IP as seen by the trusted ingress. ingress-nginx sets/appends the peer
 * address as the LAST X-Forwarded-For entry, so with `trustedProxyHops` proxies
 * in front of the pod the real client is that many entries from the right.
 * Anything to the left of it is client-supplied and ignored, so rotating a
 * forged X-Forwarded-For no longer yields a fresh bucket.
 */
export function clientIp(headers: Headers, trustedProxyHops: number = 1): string {
  const xff = headers.get("x-forwarded-for");
  if (xff && trustedProxyHops > 0) {
    const hops = xff
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (hops.length > 0) {
      return hops[Math.max(0, hops.length - trustedProxyHops)] ?? "unknown";
    }
  }
  return headers.get("x-real-ip")?.trim() || "unknown";
}
