import { withSession, json, error } from "@/lib/api";
import { listTenants } from "@/lib/control";
import { listTenantNamespaces, listPersistentNamespaces } from "@/lib/k8s";
import type { Orphan } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const asError = (err: unknown): Error => (err instanceof Error ? err : new Error(String(err)));

// Live tenant namespaces with no matching TENANT# record are orphans — a
// preview of what the sweeper would GC.
//
// Except the persistent ones. A standing per-person environment (deploy-tenant.sh
// --ttl none, one per name in scripts/tenant-roster.txt) never gets a control-table
// item, so it has exactly the shape this looks for, and the reaper refuses to
// delete it on the demo/persistent=true label alone. Listing the whole roster here
// would be a preview of deletions that cannot happen, burying any real orphan in
// ~95 rows and inviting somebody to clear them by hand.
//
// A query that fails lists nothing rather than everything: this page is read as a
// delete list, and the reaper is the thing that actually decides. It says so though
// — an empty list is also what a clean cluster looks like, so returning one silently
// would hide a real orphan for as long as the API server keeps failing. Both
// namespace queries, not just the label one: they go to the same API server, and a
// failure of either produces the same misleading "nothing here". listTenants() is
// the third input and the most dangerous one to get wrong — an empty tenant list
// makes every namespace an orphan — but it throws rather than defaulting, and
// withSession turns that into a non-200, so it is left to reject.
export const GET = withSession(async () => {
  const [tenants, namespaces, persistent] = await Promise.all([
    listTenants(),
    listTenantNamespaces().catch(asError),
    listPersistentNamespaces().catch(asError),
  ]);
  if (namespaces instanceof Error) {
    return error(503, `cannot list tenant namespaces: ${namespaces.message}`);
  }
  if (persistent instanceof Error) {
    return error(503, `cannot tell which namespaces are persistent: ${persistent.message}`);
  }
  const known = new Set(tenants.map((t) => t.namespace));
  const orphans: Orphan[] = namespaces
    .filter((ns) => !known.has(ns) && !persistent.has(ns))
    .map((ns) => ({ kind: "namespace", name: ns, detail: "no matching TENANT# record" }));
  return json(orphans);
});
