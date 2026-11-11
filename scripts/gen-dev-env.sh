#!/usr/bin/env bash
# Generate per-checkout random secrets for the docker compose stack into .env.
# Idempotent: values already in the file (or exported in the shell) are kept, so
# tokens issued earlier stay valid across restarts. docker-compose.yml has no
# secret defaults and refuses to start without these.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"

umask 077
touch "$ENV_FILE"

ensure() {
  local name="$1" bytes="$2"
  if grep -q "^${name}=" "$ENV_FILE" || [ -n "${!name:-}" ]; then
    return
  fi
  echo "${name}=$(openssl rand -hex "$bytes")" >>"$ENV_FILE"
  echo "Generated ${name} in ${ENV_FILE}"
}

ensure JWT_SECRET 32
ensure SECRET_KEY_BASE 64
ensure ALERT_WEBHOOK_SECRET 32
# Chaos injection requires the X-Chaos-Secret header. Set CHAOS_SECRET= (empty)
# in .env to leave it open, e.g. for the admin dashboard's chaos panel.
ensure CHAOS_SECRET 32
