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

// The branch a tenant deploys from must be that tenant's own: workshop-<id> or
// demo-<id> (CD may prepend a TENANT_PREFIX to the id, so `<prefix>-<id>` also
// matches), or `main` for a perpetual tenant. The runner only uses it to pick
// the tenant's image tags, but it must never name another attendee's branch or
// anything that isn't a plain ref name. Returns null when acceptable.
const TENANT_BRANCH_RE = /^(workshop|demo)[-/]([A-Za-z0-9][A-Za-z0-9._-]{0,62})$/;

export function tenantBranchError(
  branch: string,
  tenantId: string,
  perpetualIds: ReadonlySet<string>,
): string | null {
  if (branch === "main") {
    return perpetualIds.has(tenantId)
      ? null
      : `branch 'main' is reserved for the perpetual tenant; use workshop-${tenantId}`;
  }
  const m = TENANT_BRANCH_RE.exec(branch);
  const suffix = m?.[2] ? sanitizeId(m[2]) : "";
  if (!m || branch.includes("..") || !suffix) {
    return `invalid branch '${branch}': expected workshop-${tenantId} or demo-${tenantId}`;
  }
  if (tenantId !== suffix && !tenantId.endsWith(`-${suffix}`)) {
    return `branch '${branch}' does not belong to tenant '${tenantId}'; expected workshop-${tenantId} or demo-${tenantId}`;
  }
  return null;
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
