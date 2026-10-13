# Shared, cluster-wide platform add-ons as pinned helm_releases. Everything is
# OFF by default (enable_* = false), and this module is not wired into the root
# platform/terraform configuration: adding it there is an explicit, reviewed
# change (see docs/GITOPS.md). Versions and values come from the same files the
# install scripts use, so the script path and the Terraform path cannot drift:
#   demo-platform/k8s/platform-addons.versions.env
#   demo-platform/k8s/{ingress-nginx,cert-manager,argocd}/values.yaml

locals {
  addons_dir = "${path.module}/../../../../demo-platform/k8s"
  versions = {
    for line in split("\n", file("${local.addons_dir}/platform-addons.versions.env")) :
    regex("^([A-Z0-9_]+)=\"([^\"]*)\"", line)[0] => regex("^([A-Z0-9_]+)=\"([^\"]*)\"", line)[1]
    if can(regex("^([A-Z0-9_]+)=\"([^\"]*)\"", line))
  }
}

resource "helm_release" "ingress_nginx" {
  count            = var.enable_ingress_nginx ? 1 : 0
  name             = "ingress-nginx"
  namespace        = "ingress-nginx"
  create_namespace = true
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  version          = local.versions["INGRESS_NGINX_CHART_VERSION"]
  values           = [file("${local.addons_dir}/ingress-nginx/values.yaml")]
}

resource "helm_release" "cert_manager" {
  count            = var.enable_cert_manager ? 1 : 0
  name             = "cert-manager"
  namespace        = "cert-manager"
  create_namespace = true
  repository       = "https://charts.jetstack.io"
  chart            = "cert-manager"
  version          = local.versions["CERT_MANAGER_CHART_VERSION"]
  values = concat(
    [file("${local.addons_dir}/cert-manager/values.yaml")],
    var.cert_manager_role_arn == "" ? [] : [yamlencode({
      serviceAccount = { annotations = { "eks.amazonaws.com/role-arn" = var.cert_manager_role_arn } }
    })],
  )
}

# Chart equivalent of demo-platform/k8s/dns-tls/external-dns.yaml (same app
# version and flags). Use one or the other on a cluster, not both.
resource "helm_release" "external_dns" {
  count            = var.enable_external_dns ? 1 : 0
  name             = "external-dns"
  namespace        = "external-dns"
  create_namespace = true
  repository       = "https://kubernetes-sigs.github.io/external-dns/"
  chart            = "external-dns"
  version          = local.versions["EXTERNAL_DNS_CHART_VERSION"]
  values = [yamlencode({
    image          = { tag = local.versions["EXTERNAL_DNS_VERSION"] }
    provider       = { name = "aws" }
    sources        = ["ingress"]
    domainFilters  = var.external_dns_domain_filters
    policy         = "sync"
    registry       = "txt"
    txtOwnerId     = var.external_dns_txt_owner_id
    extraArgs      = ["--aws-zone-type=public", "--aws-zone-match-parent"]
    serviceAccount = { annotations = { "eks.amazonaws.com/role-arn" = var.external_dns_role_arn } }
  })]

  lifecycle {
    precondition {
      condition     = var.external_dns_role_arn != "" && length(var.external_dns_domain_filters) > 0
      error_message = "enable_external_dns requires external_dns_role_arn and external_dns_domain_filters."
    }
  }
}

resource "helm_release" "argocd" {
  count            = var.enable_argocd ? 1 : 0
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = local.versions["ARGOCD_CHART_VERSION"]
  values           = [file("${local.addons_dir}/argocd/values.yaml")]
}
