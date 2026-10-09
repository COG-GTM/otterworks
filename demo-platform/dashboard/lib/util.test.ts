import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_MAX_TTL_SECONDS,
  NEVER_TTL_SECONDS,
  checkFiniteTtl,
  formatTtl,
  parseMaxTtlSeconds,
} from "./util.ts";

const MAX = DEFAULT_MAX_TTL_SECONDS;

test("default max TTL is 7 days", () => {
  assert.equal(MAX, 7 * 86400);
});

test("accepts ordinary TTLs up to and including the max", () => {
  assert.deepEqual(checkFiniteTtl("8h", MAX), { ok: true, seconds: 8 * 3600 });
  assert.deepEqual(checkFiniteTtl("30m", MAX), { ok: true, seconds: 1800 });
  assert.deepEqual(checkFiniteTtl("72h", MAX), { ok: true, seconds: 72 * 3600 });
  assert.deepEqual(checkFiniteTtl("7d", MAX), { ok: true, seconds: MAX });
  assert.deepEqual(checkFiniteTtl("24", MAX), { ok: true, seconds: 24 * 3600 });
});

test("rejects TTLs just under the perpetual threshold", () => {
  for (const ttl of ["3649d", "87599h", "3650d", "8d", "169h", "10081m"]) {
    assert.deepEqual(checkFiniteTtl(ttl, MAX), { ok: false, reason: "too_long" }, ttl);
  }
});

test("rejects `never` as perpetual, never as a finite TTL", () => {
  assert.deepEqual(checkFiniteTtl("never", MAX), { ok: false, reason: "perpetual" });
  assert.deepEqual(checkFiniteTtl(" NEVER ", MAX), { ok: false, reason: "perpetual" });
});

test("rejects unparseable TTLs", () => {
  for (const ttl of ["", "0h", "-1h", "1w", "abc", "1.5h"]) {
    assert.deepEqual(checkFiniteTtl(ttl, MAX), { ok: false, reason: "invalid" }, ttl);
  }
});

test("a misconfigured max can never reach the perpetual threshold", () => {
  assert.deepEqual(checkFiniteTtl("3649d", NEVER_TTL_SECONDS * 2), { ok: false, reason: "too_long" });
});

test("parseMaxTtlSeconds honours sane overrides and falls back otherwise", () => {
  assert.equal(parseMaxTtlSeconds(undefined), MAX);
  assert.equal(parseMaxTtlSeconds("86400"), 86400);
  assert.equal(parseMaxTtlSeconds(" 1209600 "), 1209600);
  for (const raw of ["", "0", "-5", "abc", "1e9", String(NEVER_TTL_SECONDS), String(NEVER_TTL_SECONDS + 1)]) {
    assert.equal(parseMaxTtlSeconds(raw), MAX, raw);
  }
});

test("formatTtl renders whole days/hours, else minutes", () => {
  assert.equal(formatTtl(MAX), "7d");
  assert.equal(formatTtl(36 * 3600), "36h");
  assert.equal(formatTtl(90 * 60), "90m");
});
