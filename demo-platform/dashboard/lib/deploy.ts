import { appendAudit } from "@/lib/control";
import { activeRunnerJob, createRunnerJob } from "@/lib/jobs";
import { env } from "@/lib/env";
import { secondsToTtl } from "@/lib/util";
import type { Tenant } from "@/lib/types";

export type RedeployResult = { conflict: string } | { job: string; ttl: string };

/**
 * Ship the tenant's branch into the environment it already owns, keeping the
 * same owner, branch and expiry. Callers enforce who may redeploy which tenant.
 */
export async function redeployTenant(
  tenant: Tenant,
  imageTag: string | undefined,
  actor: string,
): Promise<RedeployResult> {
  const id = tenant.id;

  // Not caught: if the cluster cannot be listed we do not know whether a deploy
  // is already running, and guessing "no" is how a tenant gets two concurrent
  // `helm upgrade`s.
  const inFlight = await activeRunnerJob(id, "deploy");
  if (inFlight) return { conflict: `deploy already running for '${id}' (${inFlight})` };

  // Keep whatever lifetime is left. The floor matters because the runner writes
  // now+TTL on success: a tenant redeployed in its last seconds would otherwise
  // come back already expired and be reaped mid-deploy.
  const remaining = Math.max(300, tenant.expiresAt - Math.floor(Date.now() / 1000));
  const ttl = tenant.persistent ? "never" : secondsToTtl(remaining);

  let jobName: string;
  try {
    jobName = await createRunnerJob({
      action: "deploy",
      tenantId: id,
      branch: tenant.branch,
      tier: tenant.tier,
      imageTag,
      ttl,
      hostSuffix: hostSuffixOf(tenant.url) ?? env.hostSuffix,
      redeploy: true,
    });
  } catch (err) {
    await appendAudit({
      tenantId: id,
      action: "deploy_fail",
      actor,
      detail: err instanceof Error ? err.message : "job create failed",
    });
    throw err;
  }

  await appendAudit({
    tenantId: id,
    action: "redeploy",
    actor,
    detail: `branch=${tenant.branch ?? "-"} image_tag=${imageTag ?? "-"} job=${jobName}`,
  });

  return { job: jobName, ttl };
}

// The tenant's own host, not the current default: the perpetual tenant lives on
// a different suffix, and a redeploy that changed it would move the URL out
// from under whoever is using it.
function hostSuffixOf(url?: string): string | undefined {
  if (!url) return undefined;
  try {
    const host = new URL(url).hostname;
    const dot = host.indexOf(".");
    return dot === -1 ? undefined : host.slice(dot + 1);
  } catch {
    return undefined;
  }
}
