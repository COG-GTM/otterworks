#!/usr/bin/env bash
# Writes random local-only values for secrets that docker-compose refuses to
# default (see `${VAR:?}` in docker-compose*.yml) into the repo-root .env,
# which is gitignored and read automatically by `docker compose`.
# Existing .env entries and exported shell variables are left untouched, except
# retired public defaults, which are replaced.
set -euo pipefail

ENV_FILE="${1:-$(cd "$(dirname "$0")/.." && pwd)/.env}"
REQUIRED_SECRETS=(ALERT_WEBHOOK_SECRET)

RETIRED_DEFAULTS=(ALERT_WEBHOOK_SECRET=demo-alert-secret)

touch "$ENV_FILE"
for entry in "${RETIRED_DEFAULTS[@]}"; do
  if grep -qxF "$entry" "$ENV_FILE"; then
    grep -vxF "$entry" "$ENV_FILE" > "$ENV_FILE.tmp" || true
    mv "$ENV_FILE.tmp" "$ENV_FILE"
    echo "Removed retired public default ${entry%%=*} from ${ENV_FILE}" >&2
  fi
done

for name in "${REQUIRED_SECRETS[@]}"; do
  [ -n "${!name:-}" ] && continue
  grep -qE "^${name}=.+" "$ENV_FILE" && continue
  printf '%s=%s\n' "$name" "$(openssl rand -hex 32)" >> "$ENV_FILE"
  echo "Generated ${name} in ${ENV_FILE}" >&2
done
