import { test } from "node:test";
import assert from "node:assert/strict";
import { env } from "./env";
import { DEFAULT_MAX_TTL_SECONDS, NEVER_TTL_SECONDS, checkTtl } from "./util";

const MAX = DEFAULT_MAX_TTL_SECONDS;

test("checkTtl accepts ttls up to the cap", () => {
  assert.deepEqual(checkTtl("8h", MAX), { ok: true, seconds: 8 * 3600 });
  assert.deepEqual(checkTtl("72h", MAX), { ok: true, seconds: 72 * 3600 });
  assert.deepEqual(checkTtl("7d", MAX), { ok: true, seconds: MAX });
});

test("checkTtl refuses a ttl just under the perpetual threshold", () => {
  assert.deepEqual(checkTtl("3649d", MAX), { ok: false, reason: "too_long" });
  assert.deepEqual(checkTtl("87599h", MAX), { ok: false, reason: "too_long" });
  assert.deepEqual(checkTtl("8d", MAX), { ok: false, reason: "too_long" });
  assert.deepEqual(checkTtl(`${MAX / 60 + 1}m`, MAX), { ok: false, reason: "too_long" });
});

test("checkTtl reports never and decade-long ttls as perpetual", () => {
  assert.deepEqual(checkTtl("never", MAX), { ok: false, reason: "perpetual" });
  assert.deepEqual(checkTtl("3650d", MAX), { ok: false, reason: "perpetual" });
  assert.deepEqual(checkTtl("3650d", NEVER_TTL_SECONDS), { ok: false, reason: "perpetual" });
});

test("checkTtl rejects malformed ttls", () => {
  for (const ttl of ["", "0h", "-1h", "1w", "abc", "1.5h"]) {
    assert.deepEqual(checkTtl(ttl, MAX), { ok: false, reason: "invalid" }, ttl);
  }
});

test("env.maxTtlSeconds defaults to 7d and cannot be lifted to perpetual", () => {
  const saved = process.env.MAX_TTL_SECONDS;
  try {
    delete process.env.MAX_TTL_SECONDS;
    assert.equal(env.maxTtlSeconds, 7 * 86400);
    process.env.MAX_TTL_SECONDS = "86400";
    assert.equal(env.maxTtlSeconds, 86400);
    for (const bad of ["", "0", "-5", "abc", "1.5", String(NEVER_TTL_SECONDS), String(NEVER_TTL_SECONDS - 1 + 1e9)]) {
      process.env.MAX_TTL_SECONDS = bad;
      assert.equal(env.maxTtlSeconds, DEFAULT_MAX_TTL_SECONDS, bad);
    }
  } finally {
    if (saved === undefined) delete process.env.MAX_TTL_SECONDS;
    else process.env.MAX_TTL_SECONDS = saved;
  }
});
