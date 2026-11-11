#!/usr/bin/env bash
# Writes the secrets docker-compose.yml / docker-compose.infra.yml require into the
# repo's gitignored .env, generating a random value for each one that is missing.
# Existing values (in .env or the shell) are kept, so tokens stay valid across runs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"

# name:bytes of randomness (hex-encoded)
REQUIRED=(JWT_SECRET:32 SECRET_KEY_BASE:64 ALERT_WEBHOOK_SECRET:24 CHAOS_SECRET:24 GRAFANA_ADMIN_PASSWORD:16)

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

added=()
for entry in "${REQUIRED[@]}"; do
  name="${entry%%:*}"
  bytes="${entry##*:}"
  if grep -Eq "^${name}=.+" "$ENV_FILE" || [ -n "${!name:-}" ]; then
    continue
  fi
  printf '%s=%s\n' "$name" "$(openssl rand -hex "$bytes")" >>"$ENV_FILE"
  added+=("$name")
done

if [ "${#added[@]}" -gt 0 ]; then
  echo "Generated ${added[*]} in ${ENV_FILE#"$REPO_ROOT"/}"
fi
