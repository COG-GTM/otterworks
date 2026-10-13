#!/usr/bin/env bash
# Extract the SPDX SBOM that `docker buildx build --sbom=true` attached to one
# platform of an image, from an OCI layout directory
# (`--output type=oci,dest=<dir>,tar=false`).
#
#   extract-sbom.sh <oci-layout-dir> <os/arch> <out.spdx.json>
#
# BuildKit stores the SBOM as an in-toto statement in an "attestation manifest"
# that sits next to the platform manifest in the image index and points back at
# it via the vnd.docker.reference.digest annotation. The same attestation is
# pushed to the registry with the image, so this file and the registry copy are
# byte-identical predicates.
set -euo pipefail

layout="${1:?usage: extract-sbom.sh <oci-layout-dir> <os/arch> <out.spdx.json>}"
platform="${2:?platform, e.g. linux/amd64}"
out="${3:?output path}"
os="${platform%%/*}"
arch="${platform#*/}"

blob() { printf '%s/blobs/%s\n' "${layout}" "${1/://}"; }

# The layout's top-level index.json references the image index buildx wrote.
index_digest="$(jq -r '.manifests[0].digest' "${layout}/index.json")"
index="$(blob "${index_digest}")"
[ "$(jq -r '.mediaType' "${index}")" = "application/vnd.oci.image.index.v1+json" ] || {
  echo "extract-sbom: ${index_digest} is not an image index (was the build run with --sbom=true?)" >&2
  exit 1
}

image_digest="$(jq -r --arg os "${os}" --arg arch "${arch}" '
  [.manifests[] | select(.platform.os == $os and .platform.architecture == $arch)][0].digest // empty
' "${index}")"
[ -n "${image_digest}" ] || { echo "extract-sbom: no ${platform} manifest in ${layout}" >&2; exit 1; }

att_digest="$(jq -r --arg d "${image_digest}" '
  [.manifests[] | select(.annotations["vnd.docker.reference.type"] == "attestation-manifest"
                         and .annotations["vnd.docker.reference.digest"] == $d)][0].digest // empty
' "${index}")"
[ -n "${att_digest}" ] || { echo "extract-sbom: no attestation manifest for ${platform} (${image_digest})" >&2; exit 1; }

sbom_layer="$(jq -r '
  [.layers[] | select(.annotations["in-toto.io/predicate-type"] == "https://spdx.dev/Document")][0].digest // empty
' "$(blob "${att_digest}")")"
[ -n "${sbom_layer}" ] || { echo "extract-sbom: attestation for ${platform} carries no SPDX SBOM" >&2; exit 1; }

mkdir -p "$(dirname "${out}")"
jq '.predicate' "$(blob "${sbom_layer}")" > "${out}"
printf '%s\t%s\t%s packages\t%s\n' "${platform}" "${image_digest}" \
  "$(jq '.packages | length' "${out}")" "${out}"
