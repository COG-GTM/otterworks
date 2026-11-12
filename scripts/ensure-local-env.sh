#!/usr/bin/env bash
# Make sure the local docker-compose stack has a Postgres password that is not committed
# to the repo. docker-compose*.yml require POSTGRES_PASSWORD (`${POSTGRES_PASSWORD:?}`);
# this script writes a random one to the repo-root .env (git-ignored, read by compose)
# the first time, and refuses the old public default `otterworks_dev`.
# With --print it writes the resolved password to stdout for host-side tools (psql, seed).
#
# A Postgres volume created with another password keeps it: either reset the volume
# (`make down` + `docker volume rm otterworks_postgres_data`) or rotate the role in place:
#   docker exec otterworks-postgres psql -U otterworks -c "ALTER ROLE otterworks PASSWORD '<new>'"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
PUBLIC_DEFAULT="otterworks_dev"
# Embedded verbatim in DSNs (postgresql://user:pass@host), so keep it URL-safe.
SAFE_RE='^[A-Za-z0-9._~-]{16,}$'
PRINT=0
[ "${1:-}" = "--print" ] && PRINT=1

done_with() {
  [ "$PRINT" = 1 ] && printf '%s\n' "$1"
  exit 0
}

check() {
  local value="$1" source="$2"
  if [ "$value" = "$PUBLIC_DEFAULT" ]; then
    echo "POSTGRES_PASSWORD in $source is the old public default '$PUBLIC_DEFAULT'; set a new value (see $0)." >&2
    exit 1
  fi
  if ! [[ "$value" =~ $SAFE_RE ]]; then
    echo "POSTGRES_PASSWORD in $source must be at least 16 URL-safe characters [A-Za-z0-9._~-]." >&2
    exit 1
  fi
}

# An exported value wins over .env in docker compose, so validate it first.
if [ -n "${POSTGRES_PASSWORD+x}" ]; then
  check "$POSTGRES_PASSWORD" "the environment"
  done_with "$POSTGRES_PASSWORD"
fi

current=""
if [ -f "$ENV_FILE" ]; then
  current="$(sed -n 's/^[[:space:]]*POSTGRES_PASSWORD=//p' "$ENV_FILE" | tail -n1 | tr -d '"'"'"'\r')"
fi

if [ -n "$current" ]; then
  check "$current" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  done_with "$current"
fi

password="$(openssl rand -hex 24 2>/dev/null || od -An -tx1 -N24 /dev/urandom | tr -d ' \n')"
umask 077
if [ -f "$ENV_FILE" ]; then
  sed -i.bak '/^[[:space:]]*POSTGRES_PASSWORD=/d' "$ENV_FILE" && rm -f "$ENV_FILE.bak"
  [ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ] && echo >> "$ENV_FILE"
fi
echo "POSTGRES_PASSWORD=$password" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "Wrote a random POSTGRES_PASSWORD to $ENV_FILE" >&2
done_with "$password"
