variable "enable_ingress_nginx" {
  description = "Install the shared ingress-nginx controller (the only permitted LoadBalancer Service)."
  type        = bool
  default     = false
}

variable "enable_cert_manager" {
  description = "Install cert-manager."
  type        = bool
  default     = false
}

variable "enable_external_dns" {
  description = "Install external-dns from its Helm chart (alternative to demo-platform/k8s/dns-tls/external-dns.yaml)."
  type        = bool
  default     = false
}

variable "enable_argocd" {
  description = "Install Argo CD (GitOps for the long-lived environments, see docs/GITOPS.md)."
  type        = bool
  default     = false
}

variable "cert_manager_role_arn" {
  description = "IRSA role for the cert-manager DNS-01 Route53 solver (dns_role_arn output of demo-platform/infra/terraform). Empty = no annotation."
  type        = string
  default     = ""
}

variable "external_dns_role_arn" {
  description = "IRSA role for external-dns (dns_role_arn output of demo-platform/infra/terraform)."
  type        = string
  default     = ""
}

variable "external_dns_domain_filters" {
  description = "Route53 domains external-dns may manage, e.g. [\"otterworks.app\", \"demo.otterworks.app\"]."
  type        = list(string)
  default     = []
}

variable "external_dns_txt_owner_id" {
  description = "TXT registry owner id; must match the static manifest's --txt-owner-id when migrating between the two."
  type        = string
  default     = "otterworks-dev"
}
