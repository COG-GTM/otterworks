#!/usr/bin/env bash
# Ensure the local compose stack has per-checkout signing secrets.
#
# docker-compose.yml refuses to start without JWT_SECRET and SECRET_KEY_BASE, so
# nobody runs on a value committed to the repo. This writes a random value for
# each one that is missing into .env (gitignored, read by docker compose). A
# value that is already there is kept - rotating JWT_SECRET would sign every
# local user out - unless it is one of the defaults this repo used to publish,
# which anyone can sign tokens with.
#
# Usage: scripts/local-env.sh [path/to/.env]   (default: <repo>/.env)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/.env}"
REQUIRED=(JWT_SECRET SECRET_KEY_BASE)

# sha256 of signing secrets that were committed as defaults (compose, auth-service,
# admin-service secrets.yml). Stored hashed so the values are not republished here.
PUBLISHED_SHA256=(
  4756f4c2d74f1d3eea5ace184925098b5faca52cff3022b317ae22525f1a8905
  e153a4620833a85adc90ce51589f25e367dffa657b3af7099f257acff8b5d0f9
  5a52295a6882e4635d78c53e329df25a679f198089b98e07c085f09363ee0751
  3529d432262aa724274e05bdd8b59aeb6f278fa1cd6d41d57f005efb2c47e993
  c279f7638c66a7411d489d889d6f5630b13cea5d15b724bee7b7d0ae4a580ee7
)

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    python3 -c "import secrets, sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"
  fi
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | cut -d' ' -f1
  else
    printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1
  fi
}

is_published() {
  local digest
  digest="$(sha256 "$1")"
  for known in "${PUBLISHED_SHA256[@]}"; do
    [ "${digest}" = "${known}" ] && return 0
  done
  return 1
}

umask 077
touch "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

added=()
replaced=()
for name in "${REQUIRED[@]}"; do
  current="$(grep -E "^${name}=" "${ENV_FILE}" | tail -n1 | cut -d= -f2- || true)"
  if [ -n "${current}" ] && ! is_published "${current}"; then
    continue
  fi
  if [ -n "${current}" ]; then
    replaced+=("${name}")
  else
    added+=("${name}")
  fi
  sed -i.bak "/^${name}=/d" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
  if [ -s "${ENV_FILE}" ] && [ -n "$(tail -c1 "${ENV_FILE}")" ]; then
    echo >> "${ENV_FILE}"
  fi
  echo "${name}=$(random_hex 64)" >> "${ENV_FILE}"
done

if [ "${#added[@]}" -gt 0 ]; then
  echo "Generated ${added[*]} in ${ENV_FILE}"
fi
if [ "${#replaced[@]}" -gt 0 ]; then
  echo "Replaced publicly known ${replaced[*]} in ${ENV_FILE}; previously issued tokens are now invalid"
fi
