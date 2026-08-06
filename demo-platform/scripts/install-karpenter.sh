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
# Idempotent: safe to re-run, including to upgrade the Karpenter version. The one
# exception is a run that changes the EC2NodeClass's kubelet settings on a cluster
# with live nodes -- Karpenter reads that as drift and recycles the fleet -- which
# this asks about before applying.
#
# Usage:
#   demo-platform/scripts/install-karpenter.sh
#   KARPENTER_VERSION=1.13.0 EKS_CLUSTER=otterworks-dev ... install-karpenter.sh
#   ACCEPT_NODE_RECYCLE=1 ... install-karpenter.sh   # unattended, recycle allowed
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
# Answers the drift prompt below for unattended runs (CI, a runner Job).
ACCEPT_NODE_RECYCLE="${ACCEPT_NODE_RECYCLE:-}"
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

# Checked before anything is installed, not between the controller upgrade and the
# NodePool this exists to apply: the gate below can refuse, and refusing halfway
# leaves a cluster carrying a new controller against old node settings, which is
# a state nobody asked for and the log does not name. Everything it reads is
# pre-existing -- the CRD and controller upgrades do not touch EC2NodeClass
# objects or nodes -- so it answers the same question either way.
# The value this run is about to apply, read from the manifest rather than
# repeated in the two places below that compare against it: a literal drifts
# from the file silently, and with the two out of step a cluster already
# carrying the new value is told it is about to change -- an unattended run then
# refuses, the recycle gate firing hardest on the run with nothing to do.
#
# Only kubelet.maxPods is compared. It is the field this change introduces and
# the one whose absence guarantees a full recycle, but Karpenter hashes the
# whole EC2NodeClass spec, so any other future edit to that file drifts the
# fleet without passing through the gate.
#
# Scraped rather than parsed: the alternative is a YAML parser this script does
# not otherwise need. Trailing comments and quoting are tolerated; anything else
# (a templated value, the field moved into a second kubelet block) leaves this
# empty and the run stops below rather than comparing against a guess.
NODEPOOL_FILE="${REPO_ROOT}/demo-platform/k8s/karpenter/nodepool.yaml"
desired_max_pods="$(awk '
  /^[[:space:]]*maxPods:[[:space:]]*/ {
    v = $0
    sub(/^[^:]*:[[:space:]]*/, "", v)   # value only
    sub(/[[:space:]]*#.*$/, "", v)      # drop a trailing comment
    gsub(/["'"'"']/, "", v)             # drop quotes
    sub(/[[:space:]]+$/, "", v)
    if (v ~ /^[0-9]+$/) { print v; exit }
  }' "${NODEPOOL_FILE}" 2>/dev/null || true)"
[ -n "${desired_max_pods}" ] || fail "could not read kubelet.maxPods from ${NODEPOOL_FILE}; that file is applied below, so this run cannot proceed"

# nodepool.yaml pins kubelet.maxPods, which only has addresses behind it
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
  log "         The NodePool about to be applied advertises maxPods: ${desired_max_pods},"
  log "         which only prefix delegation can back. Apply platform/terraform, or run"
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
# Same distinction the node count makes below, for the same reason and with the
# opposite consequence: '' is both "the field is unset" and "this read failed",
# and here the two argue in different directions. A field genuinely unset is the
# recycle this gate exists for; a read that failed on a cluster already at the
# desired value is a re-run with nothing to do, and treating it as drift makes an unattended
# re-install refuse -- the idempotence a runner Job depends on, lost to one
# throttled GET. Neither guess is free, so say which one is being made.
nodeclass_read_rc=0
nodeclass_max_pods="$(kubectl get ec2nodeclass default -o jsonpath='{.spec.kubelet.maxPods}' 2>/dev/null)" || nodeclass_read_rc=$?
if [ "${nodeclass_read_rc}" -ne 0 ]; then
  # Still fail-closed: a NotFound here is a first install (no EC2NodeClass at
  # all), which has no nodes to lose and is filtered by the node count anyway,
  # and any other failure leaves the current value unknown. Recycling the fleet
  # on that is the one outcome worth refusing.
  nodeclass_desc="unreadable"
else
  nodeclass_desc="${nodeclass_max_pods:-unset}"
fi
# Two answers are wanted from one command and they must not be confused: how many
# nodes are at stake, and whether that number is a measurement at all. Counting
# through a pipe collapses them -- awk prints 0 for an empty list and 0 again for
# an RBAC denial, an expired token or an unreachable API server, so a cluster this
# could not read looks exactly like a cluster with nothing to lose, and the gate
# below is skipped on the run that most needs it. Capture the output on its own,
# keep the exit status, and count afterwards. The status is caught rather than
# allowed to propagate because the failure has to reach the branch: under set -e an
# unguarded substitution would end the install here, before anything is installed
# and printing nothing about why.
node_read_rc=0
node_list="$(kubectl get nodes -l karpenter.sh/nodepool --no-headers 2>/dev/null)" || node_read_rc=$?
if [ "${node_read_rc}" -ne 0 ]; then
  nodes_at_risk=true; nodes_desc="an unknown number of"
  log "WARNING: could not read the node list; assuming this cluster has nodes to lose."
else
  karpenter_nodes="$(printf '%s' "${node_list}" | grep -c . || true)"
  [ "${karpenter_nodes}" -gt 0 ] && nodes_at_risk=true || nodes_at_risk=false
  nodes_desc="${karpenter_nodes}"
fi
if [ "${nodeclass_max_pods}" != "${desired_max_pods}" ] && [ "${nodes_at_risk}" = true ]; then
  log "WARNING: kubelet.maxPods on EC2NodeClass/default changes (${nodeclass_desc} -> ${desired_max_pods})."
  log "         Karpenter reads that as drift and will replace all ${nodes_desc} node(s) it"
  log "         owns, restarting every tenant that is awake (Redis and MeiliSearch are"
  log "         in-cluster and not persisted)."
  if [ "${nodeclass_desc}" = "unreadable" ]; then
    log "         (the current value could not be read: on a cluster already at ${desired_max_pods} there"
    log "          is no drift and nothing to replace, so this gate may be asking for"
    log "          nothing. Fix the read rather than answering it blind.)"
  fi
  # A warning followed immediately by the apply is not a decision anybody gets to
  # make, so this is a gate. Only reached when the field actually changes and there
  # are nodes to lose: a first install, or a re-run of an unchanged file, never asks.
  if [ -n "${ACCEPT_NODE_RECYCLE}" ]; then
    log "         ACCEPT_NODE_RECYCLE is set; continuing."
  elif [ -t 0 ]; then
    read -r -p "[karpenter] Replace ${nodes_desc} node(s) now? [y/N] " reply
    case "${reply}" in
      [yY]|[yY][eE][sS]) ;;
      *) fail "aborted; re-run in a quiet window, or with ACCEPT_NODE_RECYCLE=1" ;;
    esac
  else
    # Unattended and unacknowledged: refuse rather than guess. Nothing has been
    # installed at this point, so the cluster is exactly as the run found it and
    # the re-run with the variable set costs nothing.
    fail "refusing to recycle ${nodes_desc} node(s) unattended; re-run with ACCEPT_NODE_RECYCLE=1"
  fi
fi

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
log "Applying EC2NodeClass + NodePool..."
sed -e "s#__CLUSTER__#${EKS_CLUSTER}#g" \
    -e "s#__INSTANCE_PROFILE__#${KARPENTER_INSTANCE_PROFILE}#g" \
    "${REPO_ROOT}/demo-platform/k8s/karpenter/nodepool.yaml" | kubectl apply -f -

kubectl -n "${KARPENTER_NAMESPACE}" rollout status deploy/karpenter --timeout=5m

log "Ready. Nodes Karpenter owns:"
kubectl get nodes -l karpenter.sh/nodepool --no-headers 2>/dev/null || true
log "Watch decisions with: kubectl -n ${KARPENTER_NAMESPACE} logs -l app.kubernetes.io/name=karpenter -f"
