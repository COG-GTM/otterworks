import { withSession, json, error } from "@/lib/api";
import { getTenant, queryAudit } from "@/lib/control";
import { getTenantWithLiveState } from "@/lib/tenants";
import { latestJobLogs, podsForNamespace } from "@/lib/k8s";
import { jobNamePrefixes } from "@/lib/jobs";
import { env } from "@/lib/env";
import type { TenantDetail } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export const GET = withSession(async (_req, { params }) => {
  const id = params?.id;
  if (!id) return error(400, "missing id");

  const base = await getTenant(id);
  if (!base) return error(404, "not found");

  const [tenant, pods, audit, logs] = await Promise.all([
    getTenantWithLiveState(base),
    podsForNamespace(base.namespace),
    queryAudit(id, 50),
    // Logs of whichever runner Job ran last for this tenant. A seed that never
    // produced a loader Job (missing Secret, tenant asleep) leaves its reason
    // only here, so seed Jobs are in the set too.
    latestJobLogs(env.platformNamespace, jobNamePrefixes(id)),
  ]);

  const detail: TenantDetail = { ...tenant, pods, audit, logs };
  return json(detail);
});
