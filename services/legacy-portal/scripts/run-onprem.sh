#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Run legacy-portal directly on a VM / on-prem host (no containers, no Kubernetes).
#
# This mirrors how the component is deployed today: a plain Spring Boot fat JAR run
# on a host, typically under systemd (see ../deploy/legacy-portal.service). By default
# it uses the embedded H2 database so it runs self-contained on a single VM; point it at
# a real PostgreSQL by exporting SPRING_PROFILES_ACTIVE=postgres and SPRING_DATASOURCE_*.
# JWT_SECRET (auth-service's JWT signing secret) is required: every /api/** route needs a
# bearer access token issued by auth-service.
#
# Usage:
#   JWT_SECRET=... ./scripts/run-onprem.sh   # build (if needed) + run with embedded H2
#   SKIP_BUILD=1 ./scripts/run-onprem.sh
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
JAR="${APP_DIR}/target/legacy-portal.jar"

cd "${APP_DIR}"

if [[ "${SKIP_BUILD:-0}" != "1" || ! -f "${JAR}" ]]; then
  echo "[run-onprem] Building legacy-portal fat JAR..."
  if [[ -x ./mvnw ]]; then
    ./mvnw -B -DskipTests package
  else
    mvn -B -DskipTests package
  fi
fi

if [[ -z "${JWT_SECRET:-}" ]]; then
  echo "[run-onprem] JWT_SECRET must be set to auth-service's JWT signing secret." >&2
  exit 1
fi

echo "[run-onprem] Starting legacy-portal on port ${SERVER_PORT:-8095}..."
exec java -jar "${JAR}"
