import { test } from "node:test";
import assert from "node:assert/strict";
import { DEVICE_TTL_SECONDS, newDeviceId, signDeviceToken, verifyDeviceToken } from "../device";

const SECRET = "test-session-secret";
const NOW = 1_700_000_000;

test("round-trips a freshly issued device token", () => {
  const id = newDeviceId();
  assert.equal(verifyDeviceToken(signDeviceToken(id, SECRET, NOW), SECRET, NOW), id);
});

test("rejects tampered, foreign-secret, malformed and expired tokens", () => {
  const id = newDeviceId();
  const token = signDeviceToken(id, SECRET, NOW);
  const [, exp, sig] = token.split(".");
  const other = newDeviceId();

  assert.equal(verifyDeviceToken(`${other}.${exp}.${sig}`, SECRET, NOW), null);
  assert.equal(verifyDeviceToken(`${id}.${Number(exp) + 1}.${sig}`, SECRET, NOW), null);
  assert.equal(verifyDeviceToken(token, "another-secret", NOW), null);
  assert.equal(verifyDeviceToken(undefined, SECRET, NOW), null);
  assert.equal(verifyDeviceToken("", SECRET, NOW), null);
  assert.equal(verifyDeviceToken("a.b", SECRET, NOW), null);
  assert.equal(verifyDeviceToken(`${id}.${exp}.${sig}.x`, SECRET, NOW), null);
  assert.equal(verifyDeviceToken(token, SECRET, NOW + DEVICE_TTL_SECONDS + 1), null);
});
