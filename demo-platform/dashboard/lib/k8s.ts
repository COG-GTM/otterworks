import * as k8s from "@kubernetes/client-node";
import { TENANT_LABEL } from "@/lib/env";
import type { PodInfo, ServiceLiveState, TenantLiveState } from "@/lib/types";

let _core: k8s.CoreV1Api | null = null;
let _batch: k8s.BatchV1Api | null = null;
let _log: k8s.Log | null = null;
let _kc: k8s.KubeConfig | null = null;

function kubeConfig(): k8s.KubeConfig {
  if (_kc) return _kc;
  const kc = new k8s.KubeConfig();
  try {
    // In-cluster (service account token) is the production path.
    kc.loadFromCluster();
  } catch {
    // Local dev fallback: KUBECONFIG / ~/.kube/config.
    kc.loadFromDefault();
  }
  _kc = kc;
  return kc;
}

function core(): k8s.CoreV1Api {
  if (!_core) _core = kubeConfig().makeApiClient(k8s.CoreV1Api);
  return _core;
}

export function batch(): k8s.BatchV1Api {
  if (!_batch) _batch = kubeConfig().makeApiClient(k8s.BatchV1Api);
  return _batch;
}

function podReady(pod: k8s.V1Pod): boolean {
  const conds = pod.status?.conditions ?? [];
  return conds.some((c) => c.type === "Ready" && c.status === "True");
}

function podRestarts(pod: k8s.V1Pod): number {
  return (pod.status?.containerStatuses ?? []).reduce((sum, cs) => sum + (cs.restartCount ?? 0), 0);
}

function serviceName(pod: k8s.V1Pod): string {
  const labels = pod.metadata?.labels ?? {};
  return (
    labels["app.kubernetes.io/name"] ||
    labels["app"] ||
    labels["app.kubernetes.io/instance"] ||
    pod.metadata?.name ||
    "unknown"
  );
}

function toPodInfo(pod: k8s.V1Pod): PodInfo {
  const containers = (pod.status?.containerStatuses ?? []).map((cs) => ({
    name: cs.name,
    ready: Boolean(cs.ready),
    restarts: cs.restartCount ?? 0,
  }));
  return {
    name: pod.metadata?.name ?? "unknown",
    phase: pod.status?.phase ?? "Unknown",
    ready: podReady(pod),
    restarts: podRestarts(pod),
    containers,
  };
}

// A Job pod is a task, not one of the tenant's services: the retail-drive seed
// loader is unready while it builds its venv and then lingers Succeeded for
// `ttlSecondsAfterFinished`. Counting it would read as Degraded and would stop
// reconcileStatus() promoting the tenant back to `active` for as long as it is
// around. podsForNamespace() is unfiltered, so the loader is still visible to
// anyone looking at the namespace's pods.
function isJobPod(pod: k8s.V1Pod): boolean {
  return (pod.metadata?.ownerReferences ?? []).some((o) => o.kind === "Job");
}

function computeLive(allPods: k8s.V1Pod[]): TenantLiveState {
  const pods = allPods.filter((p) => !isJobPod(p));
  const totalPods = pods.length;
  const readyPods = pods.filter(podReady).length;
  const services: ServiceLiveState[] = pods.map((p) => ({
    name: serviceName(p),
    ready: podReady(p),
    restarts: podRestarts(p),
  }));
  // Namespace phase: Ready if all pods ready, Degraded if some, Pending if none.
  let phase = "Pending";
  if (totalPods > 0 && readyPods === totalPods) phase = "Ready";
  else if (readyPods > 0) phase = "Degraded";
  return { phase, readyPods, totalPods, services };
}

// Cache namespace -> pods for ~5s to keep list calls cheap.
const CACHE_TTL_MS = 5000;
interface LiveCache {
  at: number;
  byNamespace: Map<string, k8s.V1Pod[]>;
}
let _cache: LiveCache | null = null;

async function loadTenantPods(): Promise<Map<string, k8s.V1Pod[]>> {
  if (_cache && Date.now() - _cache.at < CACHE_TTL_MS) return _cache.byNamespace;

  const byNamespace = new Map<string, k8s.V1Pod[]>();
  // Namespaces labeled demo/tenant are the ephemeral tenant slices.
  const nsRes = await core().listNamespace(
    undefined,
    undefined,
    undefined,
    undefined,
    TENANT_LABEL,
  );
  for (const ns of nsRes.body.items) {
    const name = ns.metadata?.name;
    if (!name) continue;
    const podsRes = await core().listNamespacedPod(name);
    byNamespace.set(name, podsRes.body.items);
  }
  _cache = { at: Date.now(), byNamespace };
  return byNamespace;
}

/** Live state keyed by namespace, for joining against the control table. */
export async function liveStateByNamespace(): Promise<Map<string, TenantLiveState>> {
  const byNamespace = await loadTenantPods();
  const out = new Map<string, TenantLiveState>();
  for (const [ns, pods] of byNamespace) out.set(ns, computeLive(pods));
  return out;
}

export async function liveStateForNamespace(ns: string): Promise<TenantLiveState | null> {
  try {
    const podsRes = await core().listNamespacedPod(ns);
    return computeLive(podsRes.body.items);
  } catch {
    return null;
  }
}

/**
 * Is a named Job in a TENANT namespace still running? The seed loader outlives
 * the runner Job that created it by minutes to hours, so it is the loader --
 * not the runner Job in the platform namespace -- that says whether a seed is
 * in flight.
 *
 * "Running" is the absence of a Complete/Failed condition, the same test the
 * runner makes: a Job with `backoffLimit: 3` reads `{active: 0, failed: 1}`
 * between a failed pod and its retry, and it has not finished.
 *
 * Only a 404 counts as "not running": callers act on a `false` by replacing the
 * Job, so a throttled or unreachable API server must raise rather than read as
 * an absent Job.
 */
export async function jobIsActive(ns: string, name: string): Promise<boolean> {
  try {
    const conditions = (await batch().readNamespacedJob(name, ns)).body.status?.conditions ?? [];
    return !conditions.some(
      (c) => (c.type === "Complete" || c.type === "Failed") && c.status === "True",
    );
  } catch (err) {
    if (err instanceof k8s.HttpError && err.statusCode === 404) return false;
    throw err;
  }
}

/**
 * Does a tenant namespace still exist? A pod LIST against a namespace that is
 * gone answers 200 with nothing in it -- indistinguishable from a tenant scaled
 * to zero -- so telling those two apart takes a read of the namespace itself.
 * Only for the diagnosis: an error is not evidence either way, so it is `true`.
 */
export async function namespaceExists(ns: string): Promise<boolean> {
  try {
    await core().readNamespace(ns);
    return true;
  } catch (err) {
    return !(err instanceof k8s.HttpError && err.statusCode === 404);
  }
}

export async function podsForNamespace(ns: string): Promise<PodInfo[]> {
  try {
    const podsRes = await core().listNamespacedPod(ns);
    return podsRes.body.items.map(toPodInfo);
  } catch {
    return [];
  }
}

/** Namespaces labeled demo/tenant that currently exist in the cluster. */
export async function listTenantNamespaces(): Promise<string[]> {
  const byNamespace = await loadTenantPods();
  return Array.from(byNamespace.keys());
}

/**
 * Stream (read) the latest logs from the newest pod of a runner Job for one
 * tenant. Selected on the `demo/tenant-id` label rather than the Job's name
 * prefix, which is ambiguous when one tenant id is a prefix of another
 * (`seed-a-` also matches tenant `a-b`'s Jobs), and covers every action, so a
 * failed seed is not hidden behind the deploy that preceded it.
 *
 * Strictly the newest Job, whatever its action or outcome: preferring a failed
 * one keeps a stale failure on screen for the hour its Job survives, including
 * over the seed the operator just dispatched. So a failure is visible until
 * something newer happens, and no longer. Best-effort; returns undefined when
 * nothing is found or the cluster is unreachable.
 */
export async function latestJobLogs(
  platformNamespace: string,
  tenantId: string,
  tailLines = 200,
): Promise<string | undefined> {
  try {
    const jobsRes = await batch().listNamespacedJob(
      platformNamespace,
      undefined,
      undefined,
      undefined,
      undefined,
      `demo/tenant-id=${tenantId}`,
    );
    const jobs = jobsRes.body.items
      .slice()
      .sort(
        (a, b) =>
          new Date(b.metadata?.creationTimestamp ?? 0).getTime() -
          new Date(a.metadata?.creationTimestamp ?? 0).getTime(),
      );
    const job = jobs[0];
    if (!job?.metadata?.name) return undefined;

    const sel = `job-name=${job.metadata.name}`;
    const podsRes = await core().listNamespacedPod(
      platformNamespace,
      undefined,
      undefined,
      undefined,
      undefined,
      sel,
    );
    // Newest attempt, not the API server's (name-sorted) list order: a Job with
    // backoffLimit > 0 that failed once has two pods, and the older one's logs
    // are the ones the operator has already seen fail.
    const pod = podsRes.body.items
      .slice()
      .sort(
        (a, b) =>
          new Date(b.metadata?.creationTimestamp ?? 0).getTime() -
          new Date(a.metadata?.creationTimestamp ?? 0).getTime(),
      )[0];
    if (!pod?.metadata?.name) return undefined;

    const logsRes = await core().readNamespacedPodLog(
      pod.metadata.name,
      platformNamespace,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      tailLines,
    );
    return logsRes.body;
  } catch {
    return undefined;
  }
}
