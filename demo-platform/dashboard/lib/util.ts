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

// The longest TTL any non-perpetual tenant may be given (checkout, extend, or
// clearing the perpetual flag). Without it, a ttl one day short of `never`
// would be accepted and leave a tenant the reaper will not collect for a
// decade. Override with MAX_TTL_SECONDS.
export const DEFAULT_MAX_TTL_SECONDS = 7 * 86400;

export type TtlCheck =
  | { ok: true; seconds: number }
  | { ok: false; reason: "invalid" | "perpetual" | "too_long" };

// Parse a caller-supplied TTL for a tenant that is *not* perpetual. "never"
// (or anything at least as long) is "perpetual": only /persist, for an id in
// PERPETUAL_TENANT_IDS, may grant that. Anything above maxSeconds is refused.
export function checkTtl(ttl: string, maxSeconds: number): TtlCheck {
  const seconds = ttlToSeconds(ttl);
  if (seconds === null) return { ok: false, reason: "invalid" };
  if (seconds >= NEVER_TTL_SECONDS) return { ok: false, reason: "perpetual" };
  if (seconds > maxSeconds) return { ok: false, reason: "too_long" };
  return { ok: true, seconds };
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
