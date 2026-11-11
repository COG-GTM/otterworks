#!/usr/bin/env bash
# Sets the password of the Flyway-seeded admin (admin@otterworks.dev) to ADMIN_PASSWORD
# from the gitignored .env, so no admin credential is committed to the repo.
# Waits for auth-service's migrations to create the account.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env}"
ADMIN_EMAIL="admin@otterworks.dev"
PG_CONTAINER="${PG_CONTAINER:-otterworks-postgres}"

"$REPO_ROOT/scripts/ensure-local-env.sh"
if [ -z "${ADMIN_PASSWORD:-}" ]; then
  ADMIN_PASSWORD="$(grep -E '^ADMIN_PASSWORD=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
fi

psql() { docker exec -i "$PG_CONTAINER" psql -U otterworks -d otterworks -v ON_ERROR_STOP=1 -qtA "$@"; }

for _ in $(seq 1 90); do
  if [ "$(psql -c "SELECT count(*) FROM users WHERE email = '$ADMIN_EMAIL'" 2>/dev/null)" = "1" ]; then
    # The password travels on stdin as a psql variable, never on a command line.
    pw="${ADMIN_PASSWORD//\\/\\\\}"
    pw="${pw//\'/\\\'}"
    matches="$(printf '%s\n' "\\set pw '$pw'" \
      "SET client_min_messages = warning;" "CREATE EXTENSION IF NOT EXISTS pgcrypto;" \
      "UPDATE users SET password_hash = crypt(:'pw', gen_salt('bf', 10)), updated_at = NOW() WHERE email = '$ADMIN_EMAIL';" \
      "SELECT password_hash = crypt(:'pw', password_hash) FROM users WHERE email = '$ADMIN_EMAIL';" \
      | psql)"
    if [ "$matches" != "t" ]; then
      echo "Failed to set the $ADMIN_EMAIL password" >&2
      exit 1
    fi
    echo "Set the $ADMIN_EMAIL password to ADMIN_PASSWORD from ${ENV_FILE#"$REPO_ROOT"/}"
    exit 0
  fi
  sleep 2
done
echo "Timed out waiting for auth-service to create $ADMIN_EMAIL" >&2
exit 1
