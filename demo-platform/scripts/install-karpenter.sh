#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Install Karpenter on the shared workshop cluster.
#
# The managed node group is a fixed pool: nothing watches for Pending pods, so
# tenant capacity past its desired size never arrives, and nothing gives nodes
# back, so a tenant scaled to zero by the reaper keeps costing what it did while
# it was awake. Karpenter provides both halves.
#
# The AWS side (controller role, node instance profile, interruption queue,
# discovery tags) is Terraform's -- see platform/terraform/modules/eks/karpenter.tf.
# This script installs the controller and the NodePool that consumes them.
#
# Idempotent: safe to re-run, including to upgrade the Karpenter version.
#
# Usage:
#   demo-platform/scripts/install-karpenter.sh
#   KARPENTER_VERSION=1.13.0 EKS_CLUSTER=otterworks-dev ... install-karpenter.sh
# ------------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER="${EKS_CLUSTER:-otterworks-dev}"
KARPENTER_NAMESPACE="${KARPENTER_NAMESPACE:-kube-system}"
# Pinned rather than floating: an unattended jump to a new minor version of the
# component that creates and deletes nodes is not something a workshop cluster
# should do on its own. Karpenter >= 1.6 is required for Kubernetes 1.34.
KARPENTER_VERSION="${KARPENTER_VERSION:-1.13.0}"
# One replica, matching the single-node system pool. The chart defaults to two
# with required anti-affinity on hostname, so on a one-node pool the second is
# unschedulable forever. Leader election means only one is ever reconciling
# anyway; the second only shortens failover, which is HA this environment has
# deliberately given up. Raise it if the system pool ever grows.
KARPENTER_REPLICAS="${KARPENTER_REPLICAS:-1}"
TF_DIR="${TF_DIR:-${REPO_ROOT}/platform/terraform}"

log()  { echo "[karpenter] $*"; }
fail() { echo "[karpenter] ERROR: $*" >&2; exit 1; }

for bin in aws kubectl helm; do
  command -v "${bin}" >/dev/null 2>&1 || fail "${bin} is required"
done

# Terraform is the source of truth for the three AWS identifiers below, but the
# state lives in S3 and reading it needs an init; allow them to be passed in so
# this can run without Terraform access.
tf_output() {
  terraform -chdir="${TF_DIR}" output -raw "$1" 2>/dev/null || true
}

KARPENTER_ROLE_ARN="${KARPENTER_ROLE_ARN:-$(tf_output karpenter_controller_role_arn)}"
KARPENTER_INSTANCE_PROFILE="${KARPENTER_INSTANCE_PROFILE:-$(tf_output karpenter_node_instance_profile)}"
KARPENTER_QUEUE="${KARPENTER_QUEUE:-$(tf_output karpenter_interruption_queue)}"

for var in KARPENTER_ROLE_ARN KARPENTER_INSTANCE_PROFILE KARPENTER_QUEUE; do
  value="${!var}"
  if [ -z "${value}" ] || [ "${value}" = "null" ]; then
    fail "${var} is empty -- run 'terraform apply' in ${TF_DIR} (enable_karpenter=true) or set ${var} in the environment"
  fi
done

log "cluster=${EKS_CLUSTER} version=${KARPENTER_VERSION}"
log "role=${KARPENTER_ROLE_ARN}"
log "instance profile=${KARPENTER_INSTANCE_PROFILE} queue=${KARPENTER_QUEUE}"

aws eks update-kubeconfig --name "${EKS_CLUSTER}" --region "${AWS_REGION}" --alias "${EKS_CLUSTER}" >/dev/null

# CRDs are installed as their own release. Helm never upgrades CRDs that came
# from a chart's crds/ directory, so bundling them would silently leave the API
# behind the controller on the next version bump.
log "Installing CRDs..."
helm upgrade --install karpenter-crd "oci://public.ecr.aws/karpenter/karpenter-crd" \
  --version "${KARPENTER_VERSION}" \
  --namespace "${KARPENTER_NAMESPACE}" --create-namespace \
  --wait --timeout 5m

log "Installing controller..."
helm upgrade --install karpenter "oci://public.ecr.aws/karpenter/karpenter" \
  --version "${KARPENTER_VERSION}" \
  --namespace "${KARPENTER_NAMESPACE}" \
  --skip-crds \
  --set "settings.clusterName=${EKS_CLUSTER}" \
  --set "settings.interruptionQueue=${KARPENTER_QUEUE}" \
  --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=${KARPENTER_ROLE_ARN}" \
  --set replicas="${KARPENTER_REPLICAS}" \
  --set controller.resources.requests.cpu=200m \
  --set controller.resources.requests.memory=512Mi \
  --set controller.resources.limits.cpu=1 \
  --set controller.resources.limits.memory=1Gi \
  --wait --timeout 10m

# The chart's default affinity keeps the controller off Karpenter's own nodes,
# so it always has somewhere to run: the managed node group stays as the system
# pool for exactly this reason.
# nodepool.yaml pins kubelet.maxPods: 110, which only has addresses behind it
# while the CNI runs in prefix-delegation mode (Terraform sets it on the addon;
# see platform/terraform/modules/eks/main.tf). Against an addon without it an
# m6a.2xlarge tops out near 58, and the surplus pods wedge in ContainerCreating
# with IP-assignment errors -- a failure that looks like anything but this. Warn
# rather than fail: an unreadable daemonset should not block the install.
# Selected by container name: aws-node is index 0 today, but the CNI ships the
# aws-eks-nodeagent sidecar alongside it and an ordering change would turn this
# into a warning about a cluster that is configured correctly.
prefix_delegation="$(kubectl -n kube-system get ds aws-node \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="aws-node")].env[?(@.name=="ENABLE_PREFIX_DELEGATION")].value}' \
  2>/dev/null || true)"
if [ "${prefix_delegation}" != "true" ]; then
  log "WARNING: aws-node does not report ENABLE_PREFIX_DELEGATION=true."
  log "         The NodePool about to be applied advertises maxPods: 110, which"
  log "         only prefix delegation can back. Apply platform/terraform, or run"
  log "         demo-platform/scripts/enable-prefix-delegation.sh, before using it."
fi

# kubelet.maxPods is part of what Karpenter hashes to detect drift, so on a cluster
# whose EC2NodeClass does not already carry it, applying this file marks every
# NodeClaim drifted: each node is cordoned, drained and replaced, 20% at a time per
# the NodePool's disruption budget. Tenant services run replicas=1 with in-cluster,
# non-persistent Redis and MeiliSearch, so an awake tenant loses its sessions, its
# search index and any injected chaos flag as its node goes. The script is
# idempotent, but the run that first introduces the field is a rolling recycle of
# the whole fleet and belongs in a quiet window.
nodeclass_max_pods="$(kubectl get ec2nodeclass default -o jsonpath='{.spec.kubelet.maxPods}' 2>/dev/null || true)"
karpenter_nodes="$(kubectl get nodes -l karpenter.sh/nodepool --no-headers 2>/dev/null | awk 'END { print NR + 0 }')"
if [ "${nodeclass_max_pods}" != "110" ] && [ "${karpenter_nodes:-0}" -gt 0 ]; then
  log "WARNING: kubelet.maxPods on EC2NodeClass/default changes (${nodeclass_max_pods:-unset} -> 110)."
  log "         Karpenter reads that as drift and will replace all ${karpenter_nodes} node(s) it"
  log "         owns, restarting every tenant that is awake (Redis and MeiliSearch are"
  log "         in-cluster and not persisted). Ctrl-C and come back in a quiet window if"
  log "         somebody is using the cluster."
fi

log "Applying EC2NodeClass + NodePool..."
sed -e "s#__CLUSTER__#${EKS_CLUSTER}#g" \
    -e "s#__INSTANCE_PROFILE__#${KARPENTER_INSTANCE_PROFILE}#g" \
    "${REPO_ROOT}/demo-platform/k8s/karpenter/nodepool.yaml" | kubectl apply -f -

kubectl -n "${KARPENTER_NAMESPACE}" rollout status deploy/karpenter --timeout=5m

log "Ready. Nodes Karpenter owns:"
kubectl get nodes -l karpenter.sh/nodepool --no-headers 2>/dev/null || true
log "Watch decisions with: kubectl -n ${KARPENTER_NAMESPACE} logs -l app.kubernetes.io/name=karpenter -f"
