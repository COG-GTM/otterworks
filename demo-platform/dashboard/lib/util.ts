// Sanitize an attendee id to an RFC-1123 label fragment (a-z0-9-, <=40 chars).
export function sanitizeId(raw: string): string {
  const s = raw
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/g, "");
  return s;
}

export function isValidId(id: string): boolean {
  return /^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$/.test(id);
}

// A perpetual tenant still carries a real expires_at, ten years out. The
// reaper skips it on `persistent`, so this is only a second line of defence:
// if that check ever regresses, the tenant survives rather than being torn
// down on the next pass.
export const NEVER_TTL_SECONDS = 10 * 365 * 86400;

export function isNeverTtl(ttl: string): boolean {
  return ttl.trim().toLowerCase() === "never";
}

// Parse a compact TTL (e.g. "8h", "30m", "2d") into seconds. Defaults unit to
// hours when omitted. "never" means perpetual. Returns null on invalid input.
export function ttlToSeconds(ttl: string): number | null {
  if (isNeverTtl(ttl)) return NEVER_TTL_SECONDS;
  const m = /^(\d+)\s*([hmdHMD]?)$/.exec(ttl.trim());
  if (!m) return null;
  const num = Number(m[1]);
  if (!Number.isFinite(num) || num <= 0) return null;
  const unit = (m[2] || "h").toLowerCase();
  switch (unit) {
    case "m":
      return num * 60;
    case "h":
      return num * 3600;
    case "d":
      return num * 86400;
    default:
      return null;
  }
}

// Longest TTL any non-perpetual tenant may be given (checkout, extend, or
// leaving the perpetual regime). Anything near NEVER_TTL_SECONDS is immortal in
// practice, so a ceiling well below it is what keeps PERPETUAL_TENANT_IDS the
// only way to an environment the reaper never collects.
export const DEFAULT_MAX_TTL_SECONDS = 7 * 86400;

// Bounds on the MAX_TTL_SECONDS override. The floor keeps every built-in
// default TTL valid (checkout 8h, un-persist 24h, CD 72h); the ceiling keeps a
// misconfiguration from turning a TTL back into years-long immortality.
export const MIN_MAX_TTL_SECONDS = 72 * 3600;
export const MAX_MAX_TTL_SECONDS = 30 * 86400;

function clampMaxTtlSeconds(n: number): number {
  return Math.min(MAX_MAX_TTL_SECONDS, Math.max(MIN_MAX_TTL_SECONDS, n));
}

// MAX_TTL_SECONDS override: unparseable or non-positive falls back to the
// default; anything else is clamped into [MIN_MAX_TTL_SECONDS, MAX_MAX_TTL_SECONDS].
export function parseMaxTtlSeconds(raw: string | undefined): number {
  if (raw === undefined || !/^\d+$/.test(raw.trim())) return DEFAULT_MAX_TTL_SECONDS;
  const n = Number(raw.trim());
  if (!Number.isSafeInteger(n) || n <= 0) return DEFAULT_MAX_TTL_SECONDS;
  return clampMaxTtlSeconds(n);
}

export type FiniteTtlCheck =
  | { ok: true; seconds: number }
  | { ok: false; reason: "invalid" | "perpetual" | "too_long" };

// Validate a TTL for a tenant that is NOT perpetual: it must parse, must not be
// `never`, and must not exceed maxSeconds (clamped like parseMaxTtlSeconds).
export function checkFiniteTtl(ttl: string, maxSeconds: number): FiniteTtlCheck {
  if (isNeverTtl(ttl)) return { ok: false, reason: "perpetual" };
  const seconds = ttlToSeconds(ttl);
  if (seconds === null) return { ok: false, reason: "invalid" };
  const cap =
    Number.isSafeInteger(maxSeconds) && maxSeconds > 0
      ? clampMaxTtlSeconds(maxSeconds)
      : DEFAULT_MAX_TTL_SECONDS;
  if (seconds > cap) return { ok: false, reason: "too_long" };
  return { ok: true, seconds };
}

// Exact human-readable duration for messages (never rounded, so a displayed
// maximum is always itself accepted when it is expressible as a TTL).
export function formatTtl(seconds: number): string {
  if (seconds % 86400 === 0) return `${seconds / 86400}d`;
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

// Render seconds back into the compact TTL the runner and deploy scripts take.
// Minutes, because they are the finest unit those parsers accept; rounded up,
// so a redeploy never shortens the lifetime the tenant already had.
export function secondsToTtl(seconds: number): string {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return `${minutes}m`;
}

// Short random suffix for auto-generated tenant ids.
export function randomIdSuffix(): string {
  return Math.random().toString(36).slice(2, 6);
}
