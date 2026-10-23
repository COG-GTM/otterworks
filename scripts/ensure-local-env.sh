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

env_file_lines() {
  # Every assignment of $1 in .env (optionally `export`ed), name and `=` stripped.
  [ -f "$ENV_FILE" ] || return 0
  sed -nE "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE"
}

env_file_value() {
  # Last assignment wins, as in compose. Quoted values keep everything inside
  # the quotes; unquoted values drop a trailing ` # comment` and whitespace.
  local raw
  raw="$(env_file_lines "$1" | tail -n 1)"
  case "$raw" in
    \"*) raw="${raw#\"}"; printf '%s' "${raw%%\"*}" ;;
    \'*) raw="${raw#\'}"; printf '%s' "${raw%%\'*}" ;;
    *) printf '%s' "$raw" | sed -E 's/(^|[[:space:]]+)#.*$//; s/[[:space:]]+$//' ;;
  esac
}

mentions_public_default() {
  # Any assignment of $1 in .env that contains a public default, however it is
  # quoted or commented: refuse rather than guess how compose will parse it.
  local line known
  while IFS= read -r line; do
    for known in "${PUBLIC_DEFAULTS[@]}"; do
      case "$line" in *"$known"*) return 0 ;; esac
    done
  done < <(env_file_lines "$1")
  return 1
}

is_public_default() {
  local candidate="$1" known
  for known in "${PUBLIC_DEFAULTS[@]}"; do
    [ "$candidate" = "$known" ] && return 0
  done
  return 1
}

refuse() {
  echo "ensure-local-env: $1 in $2 is a public default that was committed to this repo." >&2
  echo "  Remove it (unset $1 / delete the line) and re-run 'make env' to generate a random one." >&2
  exit 1
}

umask 077
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

generated=()
for entry in "${REQUIRED[@]}"; do
  name="${entry%%:*}"
  bytes="${entry##*:}"
  shell_value="${!name:-}"
  if [ -n "${!name+set}" ] && [ -z "$shell_value" ]; then
    # Compose prefers the (empty) shell value over .env and would refuse to start.
    echo "ensure-local-env: $name is exported but empty, which overrides .env for compose." >&2
    echo "  Run 'unset $name' (or export a real value) and try again." >&2
    exit 1
  fi
  if [ -n "$shell_value" ] && is_public_default "$shell_value"; then
    refuse "$name" "your environment"
  fi
  # Checked even when the shell overrides it: the next compose run without
  # that export would fall back to .env.
  if mentions_public_default "$name"; then
    refuse "$name" "$ENV_FILE"
  fi

  if [ -n "$shell_value" ] || [ -n "$(env_file_value "$name")" ]; then
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
