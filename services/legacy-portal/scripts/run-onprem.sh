#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Run legacy-portal directly on a VM / on-prem host (no containers, no Kubernetes).
#
# This mirrors how the component is deployed today: a plain Spring Boot fat JAR run
# on a host, typically under systemd (see ../deploy/legacy-portal.service). By default
# it uses the embedded H2 database so it runs self-contained on a single VM; point it at
# a real PostgreSQL by exporting SPRING_PROFILES_ACTIVE=postgres and SPRING_DATASOURCE_*.
#
# Usage:
#   ./scripts/run-onprem.sh            # build (if needed) + run with embedded H2
#   SKIP_BUILD=1 ./scripts/run-onprem.sh
# ------------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REACTOR_DIR="$(cd "${APP_DIR}/../portal-parent" && pwd)"
JAR="${APP_DIR}/target/legacy-portal.jar"

if [[ "${SKIP_BUILD:-0}" != "1" || ! -f "${JAR}" ]]; then
  echo "[run-onprem] Building legacy-portal fat JAR (reactor: services/portal-parent)..."
  if [[ -x "${REACTOR_DIR}/mvnw" ]]; then
    (cd "${REACTOR_DIR}" && ./mvnw -B -DskipTests -pl :legacy-portal -am package)
  else
    (cd "${REACTOR_DIR}" && mvn -B -DskipTests -pl :legacy-portal -am package)
  fi
fi

cd "${APP_DIR}"

echo "[run-onprem] Starting legacy-portal on port ${SERVER_PORT:-8095}..."
exec java -jar "${JAR}"
