import { NextRequest } from "next/server";
import { json, error, translateError } from "@/lib/api";
import { appendAudit, checkout, getTenant } from "@/lib/control";
import { redeployTenant } from "@/lib/deploy";
import { createRunnerJob } from "@/lib/jobs";
import { env } from "@/lib/env";
import {
  createJwksKeyResolver,
  OidcRejectedError,
  verifyGithubActionsToken,
  type VerifiedCdIdentity,
} from "@/lib/github-oidc";
import { isValidId, isValidImageTag, tenantIdForBranch, ttlToSeconds } from "@/lib/util";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const resolveKey = createJwksKeyResolver();

/**
 * CD entry point for GitHub Actions: make the environment for the pushing
 * branch match that branch, creating it if absent.
 *
 * Authenticated by the workflow's GitHub OIDC token, not the facilitator
 * passcode, and scoped by it: the repository and branch come from the signed
 * token, never from the request, so a branch can only create or redeploy the
 * one tenant its own name maps to.
 */
export async function POST(req: NextRequest) {
  const m = /^Bearer\s+(\S+)$/i.exec(req.headers.get("authorization") ?? "");
  if (!m?.[1]) return error(401, "missing bearer token");

  let identity: VerifiedCdIdentity;
  try {
    identity = await verifyGithubActionsToken(m[1], {
      audience: env.cdOidcAudience,
      trustedRefs: env.cdTrustedRepos,
      getKey: resolveKey,
    });
  } catch (err) {
    if (err instanceof OidcRejectedError) return error(err.status, err.message);
    return error(503, "cannot verify token: GitHub signing keys unavailable");
  }

  try {
    return await sync(req, identity);
  } catch (err) {
    return translateError(err);
  }
}

async function sync(req: NextRequest, { repository, branch, claims }: VerifiedCdIdentity) {
  const body = (await req.json().catch(() => ({}))) as { image_tag?: unknown };
  let imageTag: string | undefined;
  if (typeof body.image_tag === "string" && body.image_tag.trim()) {
    imageTag = body.image_tag.trim();
    if (!isValidImageTag(imageTag)) return error(400, "invalid image_tag");
  }

  const id = tenantIdForBranch(branch, env.cdTenantPrefixes[repository]);
  if (!isValidId(id)) return error(400, `cannot derive a tenant id from branch '${branch}'`);

  const actor = `github:${repository}@${branch}`;
  // Binds CD-created tenants to the repository that created them, so a fork's
  // branch with the same name cannot redeploy another repository's tenant.
  const ciOwner = `ci:${repository}`;
  const run = claims.run_id ? ` run=${claims.run_id}` : "";

  const tenant = await getTenant(id);

  if (!tenant || tenant.status === "free") {
    // A perpetual tenant is a standing cost decision an operator makes; a push
    // never creates one.
    if (env.perpetualTenantIds.has(id)) {
      return error(409, `the perpetual tenant '${id}' does not exist; an operator must create it`);
    }
    const ttlStr = env.cdTtl;
    const ttlSeconds = ttlToSeconds(ttlStr);
    if (ttlSeconds === null) return error(500, "CD_TTL is invalid");

    const created = await checkout({
      id,
      owner: ciOwner,
      branch,
      tier: "A",
      imageTag,
      ttlSeconds,
      hostSuffix: env.hostSuffix,
      persistent: false,
    });
    await appendAudit({
      tenantId: id,
      action: "checkout",
      actor,
      detail: `branch=${branch} tier=A ttl=${ttlStr}${run}`,
    });

    try {
      await createRunnerJob({
        action: "deploy",
        tenantId: id,
        branch,
        tier: "A",
        imageTag,
        ttl: ttlStr,
        hostSuffix: env.hostSuffix,
      });
    } catch (err) {
      await appendAudit({
        tenantId: id,
        action: "deploy_fail",
        actor,
        detail: err instanceof Error ? err.message : "job create failed",
      });
      return json({ tenant: created, warning: "deploy job not enqueued (runner not configured)" }, 202);
    }
    return json({ ok: true, created: true, tenant: created }, 201);
  }

  if (tenant.status === "draining") {
    return error(409, `tenant '${id}' is draining; push again once it is torn down`);
  }
  if (tenant.branch !== branch) {
    return error(409, `tenant '${id}' is deployed from '${tenant.branch ?? "(none)"}', not '${branch}'`);
  }
  if (tenant.owner?.startsWith("ci:") && tenant.owner !== ciOwner) {
    return error(409, `tenant '${id}' is owned by ${tenant.owner.slice(3)}, not ${repository}`);
  }

  const result = await redeployTenant(tenant, imageTag, `${actor}${run}`);
  if ("conflict" in result) return error(409, result.conflict);
  return json({ ok: true, created: false, job: result.job, branch, imageTag, ttl: result.ttl });
}
