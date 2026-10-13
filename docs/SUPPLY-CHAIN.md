# Container supply chain

How OtterWorks images are built, scanned, described (SBOM), and signed, and how
to check a published image yourself. It covers the 13 deployable images: the 11
backend services in `services/*` (not `services/legacy-*`) and the two
frontends, `web-app` (`frontend/client-app`) and `admin-dashboard`.

| Control | Where | Runs on |
|---|---|---|
| Multi-arch build (`linux/amd64` + `linux/arm64`) | `supply-chain.yml` (build only), `docker-build.yml` (release push) | PR, `main`, weekly, release |
| Trivy scan of the **built** image, CRITICAL/HIGH gate | `supply-chain.yml` | PR (gating), `main` + weekly (report) |
| SPDX SBOM per image and platform | BuildKit `--sbom`; workflow artifacts in both workflows | PR, `main`, weekly, release |
| SLSA provenance | BuildKit `--provenance=mode=max` | same |
| ECR scan-on-push | `platform/terraform/modules/ecr/main.tf`, asserted by `supply-chain.yml` | PR, `main`, weekly |
| Keyless cosign signature + SBOM attestation | `docker-build.yml` | release |

The tenant CD path (`cd-tenant.yml`, `scripts/deploy-*.sh`) is unchanged: it
still builds and pushes `linux/amd64` only, because the `otterworks-dev` node
group is amd64 and those images are rebuilt on every branch push.

## Multi-arch builds

Every image builds for both platforms with `docker buildx` and QEMU. To keep
the arm64 leg fast, builder stages whose output is architecture-independent
run on the build host (`FROM --platform=$BUILDPLATFORM ...`) and only the
runtime stage is emulated:

| Image | Builder output | Cross-build |
|---|---|---|
| `api-gateway` | static Go binary | `GOARCH=$TARGETARCH` |
| `web-app`, `admin-dashboard` | static JS/CSS bundle | — |
| `auth-service`, `notification-service`, `analytics-service` | JVM fat jar | — |
| `audit-service` | portable .NET assembly (`UseAppHost=false`) | — |
| `file-service` | native Rust binary | `cargo --target <arch>-unknown-linux-gnu` with the Debian cross gcc (same-arch builds use the native toolchain) |

Compiling `file-service`'s dependency tree under QEMU took over an hour and
hit the 60-minute job timeout. Cross-compiled, it builds both platforms in a
few minutes.

The rest (`document-service`, `collab-service`,
`search-service`, `admin-service`, `report-service`) install native
dependencies in the runtime image and build fully under emulation. With
BuildKit, a single-platform build on an amd64 host (`cd-tenant.yml`,
`deploy-dev.sh`) produces the same image as before.

Locally:

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64   # once
docker buildx create --name multi --use
docker buildx build --platform linux/amd64,linux/arm64 --sbom=true --provenance=mode=max \
  -o type=oci,dest=/tmp/api-gateway,tar=false services/api-gateway
```

## Image scanning

`supply-chain.yml` builds each image into an OCI layout (no registry), then for
each platform:

1. `scripts/supply-chain/oci-select-platform.sh` derives a single-platform
   layout. Trivy and syft ignore `--platform` for OCI layouts and would
   otherwise scan the first architecture twice.
2. `trivy image --input <layout> --scanners vuln --severity CRITICAL,HIGH
   --ignorefile .trivyignore` writes a JSON report, then `trivy convert`
   turns it into SARIF.
3. `scripts/supply-chain/trivy-gate.sh` applies the gate.

The gate follows the same policy as the source scan in `security-scan.yml`:

- **Pull requests** fail on CRITICAL/HIGH findings the PR *introduces*. The job
  also builds the merge-base image (amd64) and only findings absent from it
  gate. A new image, or a merge base that fails to build, gates on every
  finding.
- **`main` and the weekly run** report the whole CRITICAL/HIGH backlog as a
  warning and in the job summary, without failing.
- Anything listed in `.trivyignore` is suppressed by Trivy and never gates. Add
  an entry there, with a justification, to accept a finding.

SARIF goes to GitHub code scanning (category `trivy-image/<image>/<arch>`)
only for merged code (push to `main`, the weekly schedule, manual dispatch),
from a separate `sarif` job. SARIF built from a pull request is untrusted
input, so it never reaches a job holding `security-events: write`. On PRs the
gate above still applies and findings are in the job log. The upload is
best-effort because code scanning may not be enabled on a fork. The JSON
reports, SARIF and SBOMs are always in the
`supply-chain-<image>` artifact.

Run the same scan locally against the layout built above:

```bash
scripts/supply-chain/oci-select-platform.sh /tmp/api-gateway linux/arm64 /tmp/api-gateway-arm64
trivy image --input /tmp/api-gateway-arm64 --scanners vuln --severity CRITICAL,HIGH \
  --ignorefile .trivyignore --format json --output arm64.json
scripts/supply-chain/trivy-gate.sh --head arm64.json
```

## SBOMs and provenance

BuildKit generates an SPDX 2.3 SBOM (syft scanner) and SLSA provenance for every
platform and stores them as attestation manifests in the image index. When an
image is pushed, they travel with it.

- `scripts/supply-chain/extract-sbom.sh <layout> <os/arch> <out>` pulls one
  platform's SBOM out of a local OCI layout. `supply-chain.yml` uploads them as
  `supply-chain-<image>/<image>-<arch>.spdx.json`.
- For a pushed image:
  `docker buildx imagetools inspect <ref> --format '{{ json (index .SBOM "linux/arm64").SPDX }}'`.
  The release workflow uploads these as `sbom-<image>-<version>` and also
  signs them as cosign attestations (below).

## ECR scan-on-push

`platform/terraform/modules/ecr/main.tf` already declares every repository
with `image_scanning_configuration { scan_on_push = true }` (and immutable
tags). `scripts/supply-chain/assert-ecr-scan-on-push.sh` keeps it that way. It
runs checkov `CKV_AWS_163` over the Terraform root, so module `for_each`
expansions are evaluated. It fails on any failing or unparseable repository,
and also when an image in the `docker-build.yml` matrix has no passing
repository, because checkov alone passes vacuously when a repository is
deleted or renamed. The script is static only: no credentials, no plan, no
apply.

## Signing (release images)

`docker-build.yml` pushes `otterworks/<image>:<version>` and `:<sha>` to ECR as
one multi-arch index. It then:

1. `cosign sign` the index digest **keylessly**. The workflow's GitHub OIDC
   token gets a short-lived Fulcio certificate for its identity, and the
   signature is recorded in the public Rekor transparency log. There is no
   private key to store.
2. `cosign attest --type spdxjson` each platform manifest with that platform's
   SBOM.
3. Verifies both in-job before finishing.

The identity that signs is the workflow file on the ref it ran from:

```
issuer:   https://token.actions.githubusercontent.com
identity: https://github.com/<owner>/otterworks/.github/workflows/docker-build.yml@refs/heads/main
```

Verify a release from anywhere with registry read access:

```bash
IMAGE=<account>.dkr.ecr.us-east-1.amazonaws.com/otterworks/api-gateway
aws ecr get-login-password | docker login --username AWS --password-stdin "${IMAGE%%/*}"
DIGEST=$(docker buildx imagetools inspect "$IMAGE:v1.4.0" --format '{{ .Manifest.Digest }}')

cosign verify "$IMAGE@$DIGEST" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "https://github.com/Cognition-Partner-Workshops/otterworks/.github/workflows/docker-build.yml@refs/heads/main"

# SBOM attestation for one platform:
ARM64=$(docker buildx imagetools inspect --raw "$IMAGE@$DIGEST" |
  jq -r '.manifests[] | select(.platform.architecture == "arm64") | .digest')
cosign verify-attestation --type spdxjson "$IMAGE@$ARM64" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity "https://github.com/Cognition-Partner-Workshops/otterworks/.github/workflows/docker-build.yml@refs/heads/main" \
  | jq -r '.payload | @base64d | fromjson | .predicate.packages | length'
```

Use `--certificate-identity-regexp '^https://github.com/COG-GTM/otterworks/'`
to accept any workflow from this fork instead of one exact workflow and ref.

### Where signing does not run

- **Pull requests (including forks)** never push. `supply-chain.yml` needs
  no `id-token`, AWS role or registry, so fork PRs get the same build, SBOM
  and scan results with nothing to degrade.
- **Tenant images** (`cd-tenant.yml`) are not signed: they are per-branch,
  amd64-only and short-lived.
- **Releases from this fork** cannot reach ECR at all: the CD role's OIDC trust
  admits only upstream `main` and this fork's `workshop-*`/`demo-*` refs. The
  release job fails at "Configure AWS credentials", before anything is built
  or signed.

### Operational notes

- ECR tags are `IMMUTABLE`, and cosign stores signatures/attestations under
  `sha256-<digest>.sig` / `.att` tags. Each digest is therefore signed and
  attested exactly once, by the release run that pushed it. Re-running only the
  signing step against an already-signed digest fails with a tag-immutability
  error. That is expected; the existing signature stands.
- The ECR lifecycle policy keeps the last 10 images per repository and counts
  signature and attestation artifacts too. A release now adds roughly six
  entries (index, two attestation manifests, `.sig`, two `.att`) next to the
  two platform images, so the 10-image rule can expire a version tag after one
  or two releases. Changing the policy (keep N tagged releases plus their
  `sha256-*` cosign tags) is a shared-ECR Terraform change and needs sign-off
  before the first signed multi-arch release.
