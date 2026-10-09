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

// Docker tag grammar. The tag ends up inside `helm --set-string image.tag=...`
// in deploy-tenant.sh / inject-bug.sh, where `,` `=` `[` `]` `\` are Helm
// syntax: an unchecked tag could set image.repository, serviceAccount.roleArn
// or config/secrets on every chart. None of those characters fit this grammar.
// Keep in sync with valid_image_tag in scripts/lib/tenant-common.sh.
const IMAGE_TAG_RE = /^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$/;

export function isValidImageTag(tag: string): boolean {
  return IMAGE_TAG_RE.test(tag);
}

// Mirrors branch_tag_slug in scripts/lib/tenant-common.sh.
export function branchTagSlug(branch: string): string {
  return branch.toLowerCase().replace(/[^a-z0-9._-]/g, "-");
}

// A perpetual tenant is everyone's shared environment, so the only tag that
// may be pinned on it is the immutable `<branch-slug>-<sha7>` build CD
// publishes for that tenant's own branch -- not a bug variant or another
// tenant's image.
export function isPerpetualPinTag(tag: string, branch: string | undefined): boolean {
  if (!branch || !isValidImageTag(tag)) return false;
  const slug = branchTagSlug(branch);
  return tag.length === slug.length + 8 && tag.startsWith(`${slug}-`) && /^[0-9a-f]{7}$/.test(tag.slice(-7));
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
