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

function computeLive(pods: k8s.V1Pod[]): TenantLiveState {
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
  const nsList = await core().listNamespace({ labelSelector: TENANT_LABEL });
  for (const ns of nsList.items) {
    const name = ns.metadata?.name;
    if (!name) continue;
    const pods = await core().listNamespacedPod({ namespace: name });
    byNamespace.set(name, pods.items);
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
    const pods = await core().listNamespacedPod({ namespace: ns });
    return computeLive(pods.items);
  } catch {
    return null;
  }
}

export async function podsForNamespace(ns: string): Promise<PodInfo[]> {
  try {
    const pods = await core().listNamespacedPod({ namespace: ns });
    return pods.items.map(toPodInfo);
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
 * Stream (read) the latest logs from the newest pod of a Job whose name
 * matches the given prefix in the platform namespace. Best-effort; returns
 * undefined when nothing is found or the cluster is unreachable.
 */
export async function latestJobLogs(
  platformNamespace: string,
  jobNamePrefix: string,
  tailLines = 200,
): Promise<string | undefined> {
  try {
    const jobList = await batch().listNamespacedJob({ namespace: platformNamespace });
    const jobs = jobList.items
      .filter((j) => (j.metadata?.name ?? "").startsWith(jobNamePrefix))
      .sort(
        (a, b) =>
          new Date(b.metadata?.creationTimestamp ?? 0).getTime() -
          new Date(a.metadata?.creationTimestamp ?? 0).getTime(),
      );
    const job = jobs[0];
    if (!job?.metadata?.name) return undefined;

    const sel = `job-name=${job.metadata.name}`;
    const pods = await core().listNamespacedPod({
      namespace: platformNamespace,
      labelSelector: sel,
    });
    const pod = pods.items[0];
    if (!pod?.metadata?.name) return undefined;

    return await core().readNamespacedPodLog({
      name: pod.metadata.name,
      namespace: platformNamespace,
      tailLines,
    });
  } catch {
    return undefined;
  }
}
