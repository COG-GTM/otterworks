import { withSession, json } from "@/lib/api";
import { listTenants } from "@/lib/control";
import { listTenantNamespaces, listPersistentNamespaces } from "@/lib/k8s";
import type { Orphan } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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
// A label query that fails leaves every namespace protected rather than reported:
// this page is read as a delete list, and the reaper is the thing that actually
// decides.
export const GET = withSession(async () => {
  const [tenants, namespaces, persistent] = await Promise.all([
    listTenants(),
    listTenantNamespaces().catch(() => [] as string[]),
    listPersistentNamespaces().catch(() => null),
  ]);
  const known = new Set(tenants.map((t) => t.namespace));
  const orphans: Orphan[] =
    persistent === null
      ? []
      : namespaces
          .filter((ns) => !known.has(ns) && !persistent.has(ns))
          .map((ns) => ({ kind: "namespace", name: ns, detail: "no matching TENANT# record" }));
  return json(orphans);
});
