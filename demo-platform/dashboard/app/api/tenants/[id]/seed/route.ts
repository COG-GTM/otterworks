import { NextRequest } from "next/server";
import { withSession, json, error } from "@/lib/api";
import { appendAudit, getTenant } from "@/lib/control";
import { activeRunnerJob, createRunnerJob, SEED_LOADER_JOB } from "@/lib/jobs";
import { getTenantWithLiveState } from "@/lib/tenants";
import { jobIsActive } from "@/lib/k8s";
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
const DEPARTMENTS_RE = /^[A-Za-z0-9,_ -]+$/;

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
  // status, so `active` alone does not mean anything is listening.
  if (tenant.live && tenant.live.readyPods === 0) {
    return error(409, `tenant '${id}' is scaled to zero (idle-suspended); wake it before seeding`);
  }

  // Two loaders writing the same drive concurrently is not corruption (the
  // generator is idempotent), but the runner deletes the old loader before
  // applying the new one, so a second seed throws away everything the first
  // has uploaded so far. The loader Job in the tenant namespace is the one
  // that runs for hours; the runner Job only covers the dispatch window.
  if (await jobIsActive(tenant.namespace, SEED_LOADER_JOB)) {
    return error(409, `a seed is already loading '${id}' (${tenant.namespace}/${SEED_LOADER_JOB})`);
  }
  const running = await activeRunnerJob(id, "seed");
  if (running) return error(409, `a seed is already running for '${id}' (${running})`);

  await appendAudit({
    tenantId: id,
    action: "seed",
    actor,
    detail: `scale=${scale} departments=${departments}`,
  });
  const jobName = await createRunnerJob({
    action: "seed",
    tenantId: id,
    // Fixed-point, because the runner passes this string to render-seed-job.sh,
    // which only accepts plain decimals.
    scale: scale.toFixed(3),
    departments,
  });
  return json({ ok: true, job: jobName });
});
