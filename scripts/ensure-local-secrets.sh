#!/usr/bin/env bash
# Writes random local-only values for secrets that docker-compose refuses to
# default (see `${VAR:?}` in docker-compose*.yml) into the repo-root .env,
# which is gitignored and read automatically by `docker compose`.
# Existing .env entries and exported shell variables are left untouched.
set -euo pipefail

ENV_FILE="${1:-$(cd "$(dirname "$0")/.." && pwd)/.env}"
REQUIRED_SECRETS=(ALERT_WEBHOOK_SECRET)

touch "$ENV_FILE"
for name in "${REQUIRED_SECRETS[@]}"; do
  [ -n "${!name:-}" ] && continue
  grep -qE "^${name}=.+" "$ENV_FILE" && continue
  printf '%s=%s\n' "$name" "$(openssl rand -hex 32)" >> "$ENV_FILE"
  echo "Generated ${name} in ${ENV_FILE}" >&2
done
