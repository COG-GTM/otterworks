import { test } from "node:test";
import assert from "node:assert/strict";
import { DEVICE_TTL_SECONDS, newDeviceId, signDeviceToken, verifyDeviceToken } from "../device";

const SECRET = "test-session-secret";

test("a signed device token round-trips to its device id", () => {
  const id = newDeviceId();
  assert.equal(verifyDeviceToken(signDeviceToken(id, SECRET), SECRET), id);
});

test("tampered, foreign-key and expired tokens are rejected", () => {
  const id = newDeviceId();
  const token = signDeviceToken(id, SECRET, 1_000);
  const [, exp, sig] = token.split(".");
  assert.equal(verifyDeviceToken(`${newDeviceId()}.${exp}.${sig}`, SECRET, 1_000), null);
  assert.equal(verifyDeviceToken(token, "other-secret", 1_000), null);
  assert.equal(verifyDeviceToken(token, SECRET, 1_000 + DEVICE_TTL_SECONDS + 1), null);
  assert.equal(verifyDeviceToken("garbage", SECRET), null);
  assert.equal(verifyDeviceToken(undefined, SECRET), null);
});
