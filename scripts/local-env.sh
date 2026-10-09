#!/usr/bin/env bash
# Ensure the local compose stack has per-checkout signing secrets.
#
# docker-compose.yml refuses to start without JWT_SECRET and SECRET_KEY_BASE, so
# nobody runs on a value committed to the repo. This writes a random value for
# each one that is missing into .env (gitignored, read by docker compose), and
# never touches a value that is already there - rotating JWT_SECRET would sign
# every local user out.
#
# Usage: scripts/local-env.sh [path/to/.env]   (default: <repo>/.env)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/.env}"
REQUIRED=(JWT_SECRET SECRET_KEY_BASE)

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    python3 -c "import secrets, sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"
  fi
}

umask 077
touch "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

added=()
for name in "${REQUIRED[@]}"; do
  if grep -Eq "^${name}=.+" "${ENV_FILE}"; then
    continue
  fi
  # Drop an empty assignment so compose does not read the blank one first.
  sed -i.bak "/^${name}=\$/d" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"
  if [ -s "${ENV_FILE}" ] && [ -n "$(tail -c1 "${ENV_FILE}")" ]; then
    echo >> "${ENV_FILE}"
  fi
  echo "${name}=$(random_hex 64)" >> "${ENV_FILE}"
  added+=("${name}")
done

if [ "${#added[@]}" -gt 0 ]; then
  echo "Generated ${added[*]} in ${ENV_FILE}"
fi
