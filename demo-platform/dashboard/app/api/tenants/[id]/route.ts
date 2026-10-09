import { withSession, json, error, forbidOtherTenant, isCdSession } from "@/lib/api";
import { getTenant, queryAudit } from "@/lib/control";
import { getTenantWithLiveState } from "@/lib/tenants";
import { latestJobLogs, podsForNamespace } from "@/lib/k8s";
import { env } from "@/lib/env";
import type { TenantDetail } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// CD reads its own tenant (tenant.sh sync decides create vs redeploy from it).
export const GET = withSession(async (_req, { session, params }) => {
  const id = params?.id;
  if (!id) return error(400, "missing id");
  const denied = forbidOtherTenant(session, id);
  if (denied) return denied;

  const base = await getTenant(id);
  if (!base) return error(404, "not found");

  // CD needs only status (tenant.sh sync: create vs redeploy). Never pods,
  // audit or job logs: without a TENANT_PREFIX, two repositories can map one
  // branch name to the same tenant id.
  if (isCdSession(session)) {
    if (base.owner?.startsWith("ci:") && base.owner !== session.sub) {
      return error(403, `tenant '${id}' belongs to ${base.owner}`);
    }
    return json({ id: base.id, status: base.status, branch: base.branch });
  }

  const [tenant, pods, audit, logs] = await Promise.all([
    getTenantWithLiveState(base),
    podsForNamespace(base.namespace),
    queryAudit(id, 50),
    // Stream the latest deploy/teardown Job pod logs for this tenant.
    latestJobLogs(env.platformNamespace, `deploy-${id}-`).then(
      (d) => d ?? latestJobLogs(env.platformNamespace, `teardown-${id}-`),
    ),
  ]);

  const detail: TenantDetail = { ...tenant, pods, audit, logs };
  return json(detail);
}, { allowCd: true });
