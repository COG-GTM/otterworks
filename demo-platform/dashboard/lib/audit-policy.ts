// Pure helpers for audit retention and for bounding what anonymous traffic can
// make the dashboard write. Type-only imports on purpose: `npm test` runs these
// directly under node's built-in type stripping.

import type { AuditEvent } from "./types";

export const DEFAULT_AUDIT_RETENTION_DAYS = 90;
const DAY_SECONDS = 24 * 60 * 60;

/**
 * DynamoDB TTL (epoch seconds) for an audit item written at `tsMs`. The control
 * table's TTL is keyed on `ttl`, so every AUDIT# item must carry one or the
 * table grows forever.
 */
export function auditExpiresAt(tsMs: number, retentionDays: number = DEFAULT_AUDIT_RETENTION_DAYS): number {
  const days =
    Number.isFinite(retentionDays) && retentionDays > 0 ? retentionDays : DEFAULT_AUDIT_RETENTION_DAYS;
  return Math.floor(tsMs / 1000) + Math.floor(days * DAY_SECONDS);
}

/**
 * Insert `evt` into `top` (kept sorted newest-first) and trim to `limit`, so a
 * scan over every audit item holds at most `limit` events in memory instead of
 * the whole table.
 */
export function pushNewest(top: AuditEvent[], evt: AuditEvent, limit: number): void {
  if (limit <= 0) return;
  if (top.length >= limit && evt.ts <= top[top.length - 1]!.ts) return;
  let i = top.length;
  while (i > 0 && top[i - 1]!.ts < evt.ts) i--;
  top.splice(i, 0, evt);
  if (top.length > limit) top.length = limit;
}

export type LoginRejection = "invalid_passcode" | "rate_limited";

export interface LoginRejectionSummary {
  windowStart: number;
  windowEnd: number;
  invalidPasscode: number;
  rateLimited: number;
  distinctIps: number;
  // More distinct sources were seen than are tracked; distinctIps is a floor.
  ipsTruncated: boolean;
  // Busiest sources, highest count first.
  topIps: { ip: string; count: number }[];
}

const MAX_TRACKED_IPS = 1000;
const TOP_IPS_IN_DETAIL = 5;
const MAX_IP_LENGTH = 64;

/**
 * Collapses rejected login attempts into at most one audit item per flush
 * interval. `POST /api/auth/login` is public, so writing one durable item per
 * rejected request lets anyone grow the control table at request rate; the
 * aggregate keeps the forensics (counts + busiest sources) at a fixed write rate.
 * Memory is bounded too: past MAX_TRACKED_IPS sources only the totals grow.
 */
export class LoginRejectionAggregator {
  private invalidPasscode = 0;
  private rateLimited = 0;
  private windowStart = 0;
  private readonly perIp = new Map<string, number>();
  private untrackedIps = 0;

  readonly flushIntervalMs: number;

  constructor(flushIntervalMs: number) {
    this.flushIntervalMs = flushIntervalMs;
  }

  get pending(): boolean {
    return this.invalidPasscode + this.rateLimited > 0;
  }

  record(ip: string, reason: LoginRejection, now: number): void {
    if (!this.pending) this.windowStart = now;
    if (reason === "rate_limited") this.rateLimited += 1;
    else this.invalidPasscode += 1;

    const key = ip.slice(0, MAX_IP_LENGTH);
    const seen = this.perIp.get(key);
    if (seen !== undefined) this.perIp.set(key, seen + 1);
    else if (this.perIp.size < MAX_TRACKED_IPS) this.perIp.set(key, 1);
    else this.untrackedIps += 1;
  }

  /** True once the oldest pending rejection is at least one interval old. */
  due(now: number): boolean {
    return this.pending && now - this.windowStart >= this.flushIntervalMs;
  }

  /** Return and reset the pending window, or null when nothing is pending. */
  drain(now: number): LoginRejectionSummary | null {
    if (!this.pending) return null;
    const topIps = [...this.perIp.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .slice(0, TOP_IPS_IN_DETAIL)
      .map(([ip, count]) => ({ ip, count }));
    const summary: LoginRejectionSummary = {
      windowStart: this.windowStart,
      windowEnd: now,
      invalidPasscode: this.invalidPasscode,
      rateLimited: this.rateLimited,
      distinctIps: this.perIp.size,
      ipsTruncated: this.untrackedIps > 0,
      topIps,
    };
    this.invalidPasscode = 0;
    this.rateLimited = 0;
    this.windowStart = 0;
    this.perIp.clear();
    this.untrackedIps = 0;
    return summary;
  }
}

export function formatLoginRejectionDetail(s: LoginRejectionSummary): string {
  const top = s.topIps.map(({ ip, count }) => `${ip}=${count}`).join(",");
  const secs = Math.max(0, Math.round((s.windowEnd - s.windowStart) / 1000));
  return (
    `invalid_passcode=${s.invalidPasscode} rate_limited=${s.rateLimited} ` +
    `distinct_ips=${s.distinctIps}${s.ipsTruncated ? "+" : ""} ` +
    `window=${secs}s top=${top}`
  );
}
