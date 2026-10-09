import { test } from "node:test";
import assert from "node:assert/strict";
import {
  auditExpiresAt,
  DEFAULT_AUDIT_RETENTION_DAYS,
  formatLoginRejectionDetail,
  MAX_RETAINED_DETAIL_CHARS,
  mergeRetainedDetail,
  LoginRejectionAggregator,
  pushNewest,
} from "../lib/audit-policy.ts";
import type { AuditEvent } from "../lib/types.ts";

const DAY = 86_400;

test("auditExpiresAt returns epoch seconds `retentionDays` after the event", () => {
  const tsMs = 1_790_000_000_123;
  assert.equal(auditExpiresAt(tsMs, 30), 1_790_000_000 + 30 * DAY);
});

test("auditExpiresAt falls back to the default for unusable retention", () => {
  const tsMs = 1_790_000_000_000;
  const expected = 1_790_000_000 + DEFAULT_AUDIT_RETENTION_DAYS * DAY;
  for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.equal(auditExpiresAt(tsMs, bad), expected);
  }
  assert.equal(auditExpiresAt(tsMs), expected);
});

const evt = (ts: number): AuditEvent => ({ tenantId: "t", action: "checkout", actor: "a", ts });

test("pushNewest keeps only the newest `limit` events, newest first", () => {
  const top: AuditEvent[] = [];
  const order = [5, 1, 9, 3, 7, 2, 8, 6, 4, 10];
  for (const ts of order) pushNewest(top, evt(ts), 3);
  assert.deepEqual(
    top.map((e) => e.ts),
    [10, 9, 8],
  );
});

test("pushNewest never holds more than `limit` events over a large scan", () => {
  const top: AuditEvent[] = [];
  let peak = 0;
  for (let i = 0; i < 50_000; i++) {
    pushNewest(top, evt((i * 7919) % 50_000), 100);
    peak = Math.max(peak, top.length);
  }
  assert.equal(peak, 100);
  assert.equal(top[0]!.ts, 49_999);
  assert.equal(top[99]!.ts, 49_900);
});

test("pushNewest with a non-positive limit keeps nothing", () => {
  const top: AuditEvent[] = [];
  pushNewest(top, evt(1), 0);
  assert.equal(top.length, 0);
});

test("aggregator collapses many rejections into one summary per interval", () => {
  const agg = new LoginRejectionAggregator(60_000);
  const t0 = 1_000_000;
  assert.equal(agg.drain(t0), null);

  for (let i = 0; i < 10_000; i++) {
    agg.record(i % 2 ? "203.0.113.9" : `198.51.100.${i % 50}`, i % 3 ? "rate_limited" : "invalid_passcode", t0 + i);
  }
  assert.equal(agg.due(t0 + 59_999), false);
  assert.equal(agg.due(t0 + 60_000), true);

  const s = agg.drain(t0 + 60_000);
  assert.ok(s);
  assert.equal(s.invalidPasscode + s.rateLimited, 10_000);
  assert.equal(s.invalidPasscode, 3334);
  assert.equal(s.distinctIps, 26);
  assert.equal(s.ipsTruncated, false);
  assert.deepEqual(s.topIps[0], { ip: "203.0.113.9", count: 5000 });
  assert.equal(s.topIps.length, 5);

  // Drained: nothing pending, next window starts fresh.
  assert.equal(agg.pending, false);
  assert.equal(agg.drain(t0 + 60_001), null);
  agg.record("192.0.2.1", "invalid_passcode", t0 + 90_000);
  assert.equal(agg.due(t0 + 149_999), false);
  assert.equal(agg.due(t0 + 150_000), true);
});

test("aggregator memory is bounded when every request spoofs a new IP", () => {
  const agg = new LoginRejectionAggregator(60_000);
  for (let i = 0; i < 20_000; i++) agg.record(`10.${i >> 16}.${(i >> 8) & 255}.${i & 255}`, "rate_limited", i);
  const s = agg.drain(20_000);
  assert.ok(s);
  assert.equal(s.rateLimited, 20_000);
  assert.equal(s.distinctIps, 1000);
  assert.equal(s.ipsTruncated, true);
  assert.match(formatLoginRejectionDetail(s), /distinct_ips=1000\+ /);
});

test("aggregator truncates oversized IP strings", () => {
  const agg = new LoginRejectionAggregator(1);
  agg.record("x".repeat(10_000), "invalid_passcode", 0);
  const s = agg.drain(1);
  assert.ok(s);
  assert.equal(s.topIps[0]!.ip.length, 64);
});

test("formatLoginRejectionDetail summarises counts, window and top sources", () => {
  const detail = formatLoginRejectionDetail({
    windowStart: 0,
    windowEnd: 300_000,
    invalidPasscode: 3,
    rateLimited: 120,
    distinctIps: 2,
    ipsTruncated: false,
    topIps: [
      { ip: "1.2.3.4", count: 100 },
      { ip: "5.6.7.8", count: 23 },
    ],
  });
  assert.equal(
    detail,
    "invalid_passcode=3 rate_limited=120 distinct_ips=2 window=300s top=1.2.3.4=100,5.6.7.8=23",
  );
});

test("pushNewest floors a fractional limit instead of throwing", () => {
  const top: AuditEvent[] = [];
  for (const ts of [1, 2, 3]) pushNewest(top, { tenantId: "t", action: "checkout", actor: "a", ts }, 1.5);
  assert.deepEqual(top.map((e) => e.ts), [3]);
});

test("mergeRetainedDetail keeps a failed aggregate for the next flush, bounded", () => {
  assert.equal(mergeRetainedDetail(null, null), null);
  assert.equal(mergeRetainedDetail(null, "b"), "b");
  assert.equal(mergeRetainedDetail("a", null), "a");
  assert.equal(mergeRetainedDetail("a", "b"), "a | b");
  let retained: string | null = null;
  for (let i = 0; i < 10_000; i++) retained = mergeRetainedDetail(retained, "invalid_passcode=1 rate_limited=99");
  assert.ok(retained!.length <= MAX_RETAINED_DETAIL_CHARS);
  assert.ok(retained!.startsWith("invalid_passcode=1"));
});
