// Centralised, typed access to runtime configuration. Nothing here reads a
// secret's value into logs; callers only ever compare/sign with them.

export const env = {
  get dashboardPasscode(): string | undefined {
    return process.env.DASHBOARD_PASSCODE;
  },
  get sessionSecret(): string | undefined {
    return process.env.SESSION_SECRET;
  },
  get controlTable(): string {
    return process.env.CONTROL_TABLE || "otterworks-demo-control";
  },
  get awsRegion(): string {
    return process.env.AWS_REGION || "us-east-1";
  },
  get eksCluster(): string {
    return process.env.EKS_CLUSTER || "otterworks-dev";
  },
  get platformNamespace(): string {
    return process.env.PLATFORM_NAMESPACE || "otterworks-platform";
  },
  get runnerImage(): string | undefined {
    return process.env.RUNNER_IMAGE;
  },
  get serviceAccount(): string {
    return process.env.DASHBOARD_SERVICE_ACCOUNT || "demo-ops-dashboard";
  },
  // Secret (K8s) that the runner Job references via env valueFrom — never
  // passed on argv. Its keys hold DB_PASSWORD / AWS creds etc.
  get runnerSecretName(): string {
    return process.env.RUNNER_SECRET_NAME || "demo-ops-dashboard";
  },
  get hostSuffix(): string {
    return process.env.HOST_SUFFIX || "demo.otterworks.app";
  },
  // HTTPS clone URL passed to runner Jobs so they can fetch participant branches
  // (workshop-<id>) with GITHUB_TOKEN. Empty -> runner uses the image's bundled
  // tree (golden app) and code-level variants rely on --image-tag instead.
  get repoHttpsUrl(): string {
    return process.env.REPO_HTTPS_URL || "";
  },
  // Services that are crash-looping BY DESIGN on the golden app (planted
  // workshop bugs, e.g. admin-service's Rails logger bug). A tenant whose only
  // unhealthy pods are these is still "active" — otherwise every tenant would
  // perpetually read "error". Override with a comma-separated EXPECTED_DEGRADED_SERVICES.
  get expectedDegradedServices(): Set<string> {
    const raw = process.env.EXPECTED_DEGRADED_SERVICES;
    const list = (raw ?? "admin-service")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    return new Set(list);
  },
  get sessionTtlSeconds(): number {
    const raw = process.env.SESSION_TTL_SECONDS;
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) && n > 0 ? n : 8 * 60 * 60; // ~8h
  },
} as const;

export const TENANT_LABEL = "demo/tenant";
// What the reaper's namespace sweep enumerates (sweep_orphan_namespaces in
// demo-platform/reaper/reaper.sh). deploy-tenant.sh sets this alongside
// demo/tenant, so the two select the same namespaces today -- but the orphan
// preview answers "what would the sweep delete", and an answer to that question
// has to be drawn from the sweep's own selector, or the page is authoritative
// about a set it does not read.
export const SWEEP_LABEL = "app.kubernetes.io/managed-by=otterworks-tenant";
// ...and what that sweep then refuses to consider, whatever it is labelled
// (the `case` at the top of its loop). The selector is only half the set the
// sweep walks; a preview that applies one and not the other can list a
// platform namespace as a delete candidate, which is the same class of wrong
// as reading the other label.
export const SWEEP_EXCLUDED_NAMESPACES: ReadonlySet<string> = new Set([
  "otterworks-platform",
  "otterworks-system",
  "otterworks",
]);
export const TTL_LABEL = "demo/expires-at";
