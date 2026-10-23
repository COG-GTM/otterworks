#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Generate the secrets docker-compose.onprem.yml requires.
#
# Writes a random DB_PASSWORD to services/legacy-portal/.env (gitignored), which Docker
# Compose reads automatically. The compose file has no default password and refuses to
# start without one. An existing .env is left untouched unless --force is given; rotating
# the password of an already-initialised database volume also needs `down -v` (or ALTER ROLE).
#
# Usage:
#   ./scripts/init-onprem-env.sh           # create .env if it does not exist
#   ./scripts/init-onprem-env.sh --force   # overwrite with a new password
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$(cd "${SCRIPT_DIR}/.." && pwd)/.env"

if [[ -f "${ENV_FILE}" && "${1:-}" != "--force" ]]; then
  echo "[init-onprem-env] ${ENV_FILE} already exists; pass --force to regenerate." >&2
  exit 0
fi

if command -v openssl >/dev/null 2>&1; then
  password="$(openssl rand -hex 24)"
else
  password="$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi

umask 077
printf 'DB_PASSWORD=%s\n' "${password}" > "${ENV_FILE}"
echo "[init-onprem-env] Wrote a random DB_PASSWORD to ${ENV_FILE}"
