import { NextRequest } from "next/server";
import { withSession, json, error } from "@/lib/api";
import { appendAudit, getTenant } from "@/lib/control";
import { activeRunnerJob, createRunnerJob } from "@/lib/jobs";
import type { SeedRequest } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// scale 1.0 is the whole drive (~2,445 files); 0.1 (~110 files) is enough for a
// data-rich UI. The ceiling keeps one caller from asking for a corpus that
// outlives the tenant's TTL and fills the shared bucket.
const MAX_SCALE = 2;
const DEPARTMENTS_RE = /^[A-Za-z0-9,_ -]+$/;

export const POST = withSession(async (req: NextRequest, { actor, params }) => {
  const id = params?.id;
  if (!id) return error(400, "missing id");

  const body = (await req.json().catch(() => ({}))) as SeedRequest;

  const scale = body.scale === undefined ? 1 : Number(body.scale);
  if (!Number.isFinite(scale) || scale <= 0 || scale > MAX_SCALE) {
    return error(400, `invalid scale (0 < scale <= ${MAX_SCALE})`);
  }

  const departments =
    typeof body.departments === "string" && body.departments.trim()
      ? body.departments.trim()
      : "all";
  if (!DEPARTMENTS_RE.test(departments)) return error(400, "invalid departments");

  const tenant = await getTenant(id);
  if (!tenant) return error(404, "not found");
  // The loader writes through the tenant's own api-gateway, so there has to be
  // one: seeding a tenant that is still deploying (or draining) would just be a
  // Job crash-looping against a Service that is not there yet.
  if (tenant.status !== "active") {
    return error(409, `tenant '${id}' is ${tenant.status}; seed it once it is active`);
  }

  // Two loaders writing the same drive concurrently is not corruption (the
  // generator is idempotent) but it doubles the upload load on one tenant for
  // no benefit, and the second Job would replace the first one's pod.
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
    scale: String(scale),
    departments,
  });
  return json({ ok: true, job: jobName });
});
