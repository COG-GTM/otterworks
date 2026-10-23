#!/usr/bin/env bash
# Make sure the secrets docker-compose.yml requires exist, without committing any.
#
# docker-compose.yml has no defaults for JWT_SECRET, SECRET_KEY_BASE,
# ALERT_WEBHOOK_SECRET or CHAOS_SECRET: a default committed to a public repo
# lets anyone mint admin tokens on every stack that did not override it. This
# script appends a random value to the repo's gitignored .env for each one
# that is set neither in the environment nor in .env, then fixes .env to 0600.
# Compose reads .env automatically; values exported in the shell win over it.
#
# It refuses to continue if a value is one of the public defaults compose used
# to ship, so a stale .env or shell export cannot quietly keep them alive.
#
# Usage: scripts/ensure-local-env.sh [ENV_FILE]   (default: <repo>/.env)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/.env}"

# name:openssl-rand-hex-bytes
REQUIRED=(JWT_SECRET:32 SECRET_KEY_BASE:64 ALERT_WEBHOOK_SECRET:32 CHAOS_SECRET:32)

PUBLIC_DEFAULTS=(
  otterworks-local-dev-jwt-secret-change-me-in-production
  dev-jwt-secret-otterworks-2024-change-in-production
  otterworks-dev-secret
  dev-secret-key-base-otterworks-change-in-production
  demo-alert-secret
)

command -v openssl >/dev/null 2>&1 || { echo "ensure-local-env: openssl is required" >&2; exit 1; }

env_file_value() {
  [ -f "$ENV_FILE" ] || return 0
  # Last assignment wins, as in compose; strip optional quotes and export.
  sed -nE "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" \
    | tail -n 1 | sed -E "s/^['\"](.*)['\"][[:space:]]*$/\1/"
}

is_public_default() {
  local candidate="$1" known
  for known in "${PUBLIC_DEFAULTS[@]}"; do
    [ "$candidate" = "$known" ] && return 0
  done
  return 1
}

umask 077
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

generated=()
for entry in "${REQUIRED[@]}"; do
  name="${entry%%:*}"
  bytes="${entry##*:}"
  value="${!name:-}"
  origin="environment"
  if [ -z "$value" ]; then
    value="$(env_file_value "$name")"
    origin="$ENV_FILE"
  fi

  if [ -n "$value" ]; then
    if is_public_default "$value"; then
      echo "ensure-local-env: $name in $origin is a public default that was committed to this repo." >&2
      echo "  Remove it (unset $name / delete the line) and re-run 'make env' to generate a random one." >&2
      exit 1
    fi
    continue
  fi

  if [ -s "$ENV_FILE" ] && [ -n "$(tail -c 1 "$ENV_FILE")" ]; then
    printf '\n' >>"$ENV_FILE"
  fi
  printf '%s=%s\n' "$name" "$(openssl rand -hex "$bytes")" >>"$ENV_FILE"
  generated+=("$name")
done

if [ "${#generated[@]}" -gt 0 ]; then
  echo "ensure-local-env: generated ${generated[*]} in $ENV_FILE"
fi
