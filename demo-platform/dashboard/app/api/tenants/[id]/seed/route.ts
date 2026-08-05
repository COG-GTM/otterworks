import { NextRequest } from "next/server";
import { withSession, json, error } from "@/lib/api";
import { appendAudit, getTenant } from "@/lib/control";
import { activeRunnerJob, createRunnerJob, SEED_LOADER_JOB } from "@/lib/jobs";
import { getTenantWithLiveState } from "@/lib/tenants";
import { jobIsActive, namespaceExists } from "@/lib/k8s";
import type { SeedRequest } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// scale 1.0 is the whole drive (~2,445 files); 0.1 (~110 files) is enough for a
// data-rich UI. The ceiling keeps one caller from asking for a corpus that
// outlives the tenant's TTL and fills the shared bucket; the floor keeps the
// value out of JS exponential notation (`String(1e-7)`), which the renderer's
// numeric check rejects, and off an empty drive.
const MAX_SCALE = 2;
const MIN_SCALE = 0.01;
// `&` is in there because three departments are named with one ("Supply Chain
// & Logistics"); the renderer escapes it before it becomes sed replacement text.
const DEPARTMENTS_RE = /^[A-Za-z0-9,_ &-]+$/;

export const POST = withSession(async (req: NextRequest, { actor, params }) => {
  const id = params?.id;
  if (!id) return error(400, "missing id");

  const body = (await req.json().catch(() => ({}))) as SeedRequest;

  const scale = body.scale === undefined ? 1 : Number(body.scale);
  if (!Number.isFinite(scale) || scale < MIN_SCALE || scale > MAX_SCALE) {
    return error(400, `invalid scale (${MIN_SCALE} <= scale <= ${MAX_SCALE})`);
  }

  const departments =
    typeof body.departments === "string" && body.departments.trim()
      ? body.departments.trim()
      : "all";
  if (!DEPARTMENTS_RE.test(departments)) return error(400, "invalid departments");

  // `force` throws away whatever the running loader has uploaded so far. It is
  // here because the alternative recovery -- deleting the Job -- needs the very
  // cluster access this route exists to stand in for, and a loader whose pod is
  // never admitted (a tenant ResourceQuota with nothing left in it) has no
  // terminal condition and would otherwise 409 every later seed for good.
  const force = body.force === true;

  const base = await getTenant(id);
  if (!base) return error(404, "not found");
  // The loader writes through the tenant's own api-gateway, so there has to be
  // one: seeding a tenant that is still deploying (or draining) would just be a
  // Job crash-looping against a Service that is not there yet.
  const tenant = await getTenantWithLiveState(base);
  if (tenant.status !== "active") {
    return error(409, `tenant '${id}' is ${tenant.status}; seed it once it is active`);
  }
  // Idle-suspend scales a tenant to zero without touching its control-table
  // status, so `active` alone does not mean anything is listening. Live state
  // that could not be read is not evidence that it is: getTenantWithLiveState()
  // swallows the cluster error, so an absent `live` says nothing either way.
  if (!tenant.live) {
    return error(503, `could not read live state for '${id}'; try again`);
  }
  if (tenant.live.readyPods === 0) {
    // No pods at all is a suspended tenant -- or one whose namespace is gone,
    // since a pod LIST answers 200 either way and the control table can still
    // say `active` after a reap. Pods that are simply not Ready is a broken or
    // still-starting tenant, and telling that operator to "wake it" points at
    // the wrong remedy. The remedy named is the one the seed caller can
    // actually run: scripts/tenant-scale.sh needs the cluster access this route
    // exists to stand in for, a redeploy does not.
    const redeploy = `tenant.sh sync ${tenant.branch ?? "<branch>"}`;
    if (tenant.live.totalPods > 0) {
      return error(
        409,
        `tenant '${id}' has no ready pods (${tenant.live.phase}); it cannot serve the loader yet`,
      );
    }
    return error(
      409,
      (await namespaceExists(tenant.namespace))
        ? `tenant '${id}' is scaled to zero (idle-suspended); wake it with a redeploy (${redeploy}) before seeding`
        : `namespace ${tenant.namespace} no longer exists; re-create the tenant (${redeploy}) before seeding`,
    );
  }

  // Two loaders writing the same drive concurrently is not corruption (the
  // generator is idempotent), but the runner deletes the old loader before
  // applying the new one, so a second seed throws away everything the first
  // has uploaded so far. The loader Job in the tenant namespace is the one
  // that runs for hours; the runner Job only covers the dispatch window.
  // A read that fails is not "nothing is running": the runner would go on to
  // delete the loader, so an unreadable Job blocks the request instead.
  if (!force) {
    let loading: boolean;
    try {
      loading = await jobIsActive(tenant.namespace, SEED_LOADER_JOB);
    } catch {
      return error(503, `could not check for a running seed in ${tenant.namespace}; try again`);
    }
    if (loading) {
      return error(
        409,
        `a seed is already loading '${id}' (${tenant.namespace}/${SEED_LOADER_JOB}); force to restart it`,
      );
    }
  }
  // Skipped under force for the same reason as the loader check: a runner Job
  // can also get stuck active (it waits on a foreground delete of a loader pod
  // that will not terminate), and a check that cannot be bypassed is a lockout.
  if (!force) {
    const running = await activeRunnerJob(id, "seed");
    if (running) {
      return error(409, `a seed is already running for '${id}' (${running}); force to dispatch anyway`);
    }
  }

  await appendAudit({
    tenantId: id,
    action: "seed",
    actor,
    detail: `scale=${scale} departments=${departments}${force ? " force=true" : ""}`,
  });
  const jobName = await createRunnerJob({
    action: "seed",
    tenantId: id,
    // Fixed-point, because the runner passes this string to render-seed-job.sh,
    // which only accepts plain decimals.
    scale: scale.toFixed(3),
    departments,
    force,
  });
  return json({ ok: true, job: jobName });
});
