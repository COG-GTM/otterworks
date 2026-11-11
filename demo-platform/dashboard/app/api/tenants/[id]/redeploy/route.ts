import { NextRequest } from "next/server";
import { withSession, json, error } from "@/lib/api";
import { getTenant } from "@/lib/control";
import { redeployTenant } from "@/lib/deploy";
import type { RedeployRequest } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Ship the tenant's branch into the environment it already owns.
 *
 * This is the CD entry point, and the deliberate difference from checkout is
 * that it changes nothing about the reservation: same owner, same branch, and
 * the same expiry the tenant already had. A push must never quietly extend an
 * environment's life, or nothing would ever be reaped while anyone was working.
 */
export const POST = withSession(async (req: NextRequest, { actor, params }) => {
  const id = params?.id;
  if (!id) return error(400, "missing id");

  const tenant = await getTenant(id);
  if (!tenant) return error(404, "not found");
  if (tenant.status === "draining" || tenant.status === "free") {
    return error(409, `tenant '${id}' is ${tenant.status}; check it out before redeploying`);
  }

  const body = (await req.json().catch(() => ({}))) as RedeployRequest;
  const imageTag =
    typeof body.image_tag === "string" && body.image_tag.trim() ? body.image_tag.trim() : undefined;
  const requestedBranch =
    typeof body.branch === "string" && body.branch.trim() ? body.branch.trim() : undefined;

  // A tenant belongs to one branch. Both `workshop-derek` and `demo-derek` map
  // to tenant `derek`, so without this the second branch to be pushed would
  // silently overwrite the first branch's environment.
  if (requestedBranch && requestedBranch !== tenant.branch) {
    return error(
      409,
      `tenant '${id}' is deployed from '${tenant.branch ?? "(none)"}', not '${requestedBranch}'`,
    );
  }

  const result = await redeployTenant(tenant, imageTag, actor);
  if ("conflict" in result) return error(409, result.conflict);

  return json({ ok: true, job: result.job, branch: tenant.branch, imageTag, ttl: result.ttl });
});
