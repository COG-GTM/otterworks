import { test } from "node:test";
import assert from "node:assert/strict";
import { branchTagSlug, isPerpetualPinTag, isValidImageTag } from "./util";

test("isValidImageTag accepts Docker tags", () => {
  for (const tag of ["main", "tenant-derek", "main-abc1234", "v1.2.3", "_x", "a".repeat(128)]) {
    assert.equal(isValidImageTag(tag), true, tag);
  }
});

test("isValidImageTag rejects Helm --set syntax and non-tags", () => {
  for (const tag of [
    "",
    "x,image.repository=evil.example/img",
    "x,serviceAccount.roleArn=arn:aws:iam::1:role/other",
    "a=b",
    "a[0]",
    "a]",
    "a\\b",
    "-x",
    ".x",
    "a b",
    "a/b",
    "a:b",
    "a\nb",
    "main-abc1234\n",
    "main-abc1234\r\n",
    "a".repeat(129),
  ]) {
    assert.equal(isValidImageTag(tag), false, JSON.stringify(tag));
  }
});

test("branchTagSlug matches branch_tag_slug", () => {
  assert.equal(branchTagSlug("main"), "main");
  assert.equal(branchTagSlug("Feature/X_y.z"), "feature-x_y.z");
});

test("isPerpetualPinTag allows only the branch's own CD build", () => {
  assert.equal(isPerpetualPinTag("main-abc1234", "main"), true);
  assert.equal(isPerpetualPinTag("feature-x-0123abc", "feature/x"), true);

  assert.equal(isPerpetualPinTag("main", "main"), false);
  assert.equal(isPerpetualPinTag("tenant-main", "main"), false);
  assert.equal(isPerpetualPinTag("main-abc123", "main"), false);
  assert.equal(isPerpetualPinTag("main-ABC1234", "main"), false);
  assert.equal(isPerpetualPinTag("main-abc12345", "main"), false);
  assert.equal(isPerpetualPinTag("workshop-derek-abc1234", "main"), false);
  assert.equal(isPerpetualPinTag("x-main-abc1234", "main"), false);
  assert.equal(isPerpetualPinTag("main-abc1234,image.repository=evil", "main"), false);
  assert.equal(isPerpetualPinTag("main-abc1234", undefined), false);
});
