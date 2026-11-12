#!/usr/bin/env bash
# Ensure the gitignored .env next to the compose files holds a random local
# Postgres password. docker compose reads .env automatically, and both compose
# files refuse to start without OTTERWORKS_DB_PASSWORD, so no database password
# is ever committed. Idempotent: an existing value is kept.
set -euo pipefail

ENV_FILE="${1:-$(cd "$(dirname "$0")/.." && pwd)/.env}"
KEY=OTTERWORKS_DB_PASSWORD
# The password that used to be committed to docker-compose*.yml.
PUBLIC_DEFAULT=otterworks_dev

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
[ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ] && echo >> "$ENV_FILE"

current="$(sed -n "s/^${KEY}=//p" "$ENV_FILE" | tail -n1)"
current="${current%\"}"; current="${current#\"}"
current="${current%\'}"; current="${current#\'}"

if [ "$current" = "$PUBLIC_DEFAULT" ]; then
  echo "$ENV_FILE sets $KEY to the old public default '$PUBLIC_DEFAULT'; remove that line and rerun 'make env'." >&2
  exit 1
fi

if [ -z "$current" ]; then
  # Portable in-place delete (BSD sed on macOS has a different -i syntax).
  tmp="$(mktemp "$ENV_FILE.XXXXXX")"
  grep -v "^${KEY}=" "$ENV_FILE" > "$tmp" || true
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  if command -v openssl >/dev/null 2>&1; then
    password="$(openssl rand -hex 24)"
  else
    password="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  fi
  # Hex only: the value is interpolated unescaped into DATABASE_URL-style URLs.
  echo "${KEY}=${password}" >> "$ENV_FILE"
  echo "Generated a random $KEY in $ENV_FILE." >&2
  echo "An existing postgres_data volume keeps its old password: run 'make db-password-sync' (or 'make down' + 'docker volume rm otterworks_postgres_data')." >&2
fi
