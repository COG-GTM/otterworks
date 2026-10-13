#!/usr/bin/env bash
# Derive a single-platform OCI layout from a multi-platform one written by
# `docker buildx build --output type=oci,dest=<dir>,tar=false`.
#
#   oci-select-platform.sh <oci-layout-dir> <os/arch> <out-dir>
#
# Scanners that read OCI layouts (trivy --input, syft oci-dir:) take the first
# image they find and ignore --platform, so scanning a multi-arch layout
# silently scans one architecture twice. The derived layout hardlinks the
# shared blobs and points index.json straight at the requested platform's
# image manifest, so the scanner cannot pick the wrong one.
set -euo pipefail

layout="${1:?usage: oci-select-platform.sh <oci-layout-dir> <os/arch> <out-dir>}"
platform="${2:?platform, e.g. linux/arm64}"
out="${3:?output directory}"
os="${platform%%/*}"
arch="${platform#*/}"

index_digest="$(jq -r '.manifests[0].digest' "${layout}/index.json")"
index="${layout}/blobs/${index_digest/://}"
descriptor="$(jq -c --arg os "${os}" --arg arch "${arch}" '
  [.manifests[] | select(.platform.os == $os and .platform.architecture == $arch)][0] // empty
' "${index}")"
[ -n "${descriptor}" ] || { echo "oci-select-platform: no ${platform} manifest in ${layout}" >&2; exit 1; }

rm -rf "${out}"
mkdir -p "${out}"
cp -al "${layout}/blobs" "${out}/blobs" 2>/dev/null || cp -a "${layout}/blobs" "${out}/blobs"
cp "${layout}/oci-layout" "${out}/oci-layout"
jq -n --argjson d "${descriptor}" '{schemaVersion: 2, mediaType: "application/vnd.oci.image.index.v1+json", manifests: [$d]}' \
  > "${out}/index.json"
jq -r '.digest' <<< "${descriptor}"
