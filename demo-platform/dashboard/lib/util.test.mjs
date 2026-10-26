// node --experimental-strip-types --test lib/*.test.mjs  (Node >= 22.6)
import { test } from "node:test";
import assert from "node:assert/strict";
import { tenantBranchError } from "./util.ts";

const perpetual = new Set(["main"]);

test("accepts the tenant's own workshop/demo branch", () => {
  for (const b of ["workshop-derek", "demo-derek", "workshop/derek", "workshop-Derek"]) {
    assert.equal(tenantBranchError(b, "derek", perpetual), null, b);
  }
});

test("accepts a TENANT_PREFIX-scoped id for the same branch", () => {
  assert.equal(tenantBranchError("demo-derek", "gtm-derek", perpetual), null);
});

test("refuses another tenant's branch", () => {
  assert.match(tenantBranchError("workshop-alice", "derek", perpetual) ?? "", /does not belong/);
  assert.match(tenantBranchError("workshop-derek", "derek2", perpetual) ?? "", /does not belong/);
});

test("refuses arbitrary or malformed refs", () => {
  for (const b of [
    "feature/x",
    "devin/123-fix",
    "workshop-",
    "workshop-derek/../../x",
    "workshop-..derek",
    "--upload-pack=touch /tmp/x",
    "workshop-derek;id",
    "workshop-derek\n",
    "refs/heads/workshop-derek",
  ]) {
    assert.notEqual(tenantBranchError(b, "derek", perpetual), null, JSON.stringify(b));
  }
});

test("main only for a perpetual tenant", () => {
  assert.equal(tenantBranchError("main", "main", perpetual), null);
  assert.match(tenantBranchError("main", "derek", perpetual) ?? "", /reserved/);
  assert.notEqual(tenantBranchError("main", "main", new Set()), null);
});
