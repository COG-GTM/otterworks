#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Verify one stage of the legacy-portal decomposition locally (nothing is deployed).
#
#   1. Build and test every available module: services/legacy-portal (JDK 11) and any of
#      services/{announcements,preferences,feedback}-service that exist (JDK 17).
#   2. For each profile and run: start fresh local processes (H2 in-memory, or PostgreSQL
#      from services/legacy-portal/docker-compose.onprem.yml recreated with `down -v`),
#      replay tests/parity/legacy_portal against them, then stop everything.
#   3. Print a summary usable as commit trailers and as the ticket status note.
#
# Contexts served by an extracted service are pointed at it (ANNOUNCEMENTS_URL etc.);
# the rest stay on the monolith at :8095.
#
# Usage:
#   scripts/legacy-portal/verify-stage.sh [--profile h2|postgres|all] [--runs N]
#                                         [--skip-build] [--skip-module-tests]
# Env:
#   JDK11_HOME / JDK17_HOME   JDK locations (auto-detected under /usr/lib/jvm otherwise)
#   PARITY_PG_PORT            host port for the parity PostgreSQL (default 55495)
#   ANNOUNCEMENTS_PORT / PREFERENCES_PORT / FEEDBACK_PORT
#                             ports for extracted services (default 8096 / 8097 / 8098)
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORTAL_DIR="${REPO_ROOT}/services/legacy-portal"
PARITY_DIR="${REPO_ROOT}/tests/parity/legacy_portal"
COMPOSE_FILE="${PORTAL_DIR}/docker-compose.onprem.yml"
MONOLITH_PORT=8095
PG_PORT="${PARITY_PG_PORT:-55495}"
DB_PASSWORD="${DB_PASSWORD:-legacyportal}"

PROFILE=all
RUNS=2
SKIP_BUILD=0
SKIP_MODULE_TESTS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --runs) RUNS="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-module-tests) SKIP_MODULE_TESTS=1; shift ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "${PROFILE}" in
  h2) PROFILES=(h2) ;;
  postgres) PROFILES=(postgres) ;;
  all) PROFILES=(h2 postgres) ;;
  *) echo "--profile must be h2, postgres or all" >&2; exit 2 ;;
esac
[[ "${RUNS}" =~ ^[1-9][0-9]*$ ]] || { echo "--runs must be a positive integer" >&2; exit 2; }

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/legacy-portal-verify.XXXXXX")"
PIDS=()
PG_STARTED=0
SUMMARY=()
FAILED=0

log() { echo "[verify-stage] $*" >&2; }

jdk_home() {
  local major="$1" var="JDK$1_HOME" candidate
  if [[ -n "${!var:-}" ]]; then echo "${!var}"; return; fi
  for candidate in /usr/lib/jvm/java-"${major}"-openjdk* /usr/lib/jvm/temurin-"${major}"* \
                   /usr/lib/jvm/jdk-"${major}"* /usr/lib/jvm/zulu-"${major}"*; do
    if [[ -x "${candidate}/bin/java" ]]; then echo "${candidate}"; return; fi
  done
  if command -v java >/dev/null && java -version 2>&1 | grep -qE "version \"${major}[.\"]"; then
    dirname "$(dirname "$(readlink -f "$(command -v java)")")"
    return
  fi
  echo "no JDK ${major} found; set ${var}" >&2
  return 1
}

# name|dir|jdk|port|context url var ("" = serves every context not claimed by another module)
MODULES=("legacy-portal|${PORTAL_DIR}|11|${MONOLITH_PORT}|")
for ctx in announcements preferences feedback; do
  dir="${REPO_ROOT}/services/${ctx}-service"
  [[ -f "${dir}/pom.xml" ]] || continue
  upper="$(echo "${ctx}" | tr '[:lower:]' '[:upper:]')"
  port_var="${upper}_PORT"
  case "${ctx}" in announcements) default_port=8096 ;; preferences) default_port=8097 ;; *) default_port=8098 ;; esac
  MODULES+=("${ctx}-service|${dir}|17|${!port_var:-${default_port}}|${upper}_URL")
done

stop_processes() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    [[ -n "${pid}" ]] || continue
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  done
  PIDS=()
}

stop_postgres() {
  if [[ "${PG_STARTED}" == "1" ]]; then
    docker compose -f "${COMPOSE_FILE}" -f "${WORK_DIR}/compose.parity.yml" down -v >/dev/null 2>&1 || true
    PG_STARTED=0
  fi
}

cleanup() {
  stop_processes
  stop_postgres
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

record() {
  SUMMARY+=("$1")
  log "$1"
}

build_modules() {
  local entry name dir jdk goal
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name dir jdk _ _ <<<"${entry}"
    goal=verify
    [[ "${SKIP_MODULE_TESTS}" == "1" ]] && goal="-DskipTests package"
    log "building ${name} (JDK ${jdk}): ./mvnw -B ${goal}"
    # shellcheck disable=SC2086
    if (cd "${dir}" && JAVA_HOME="$(jdk_home "${jdk}")" ./mvnw -B ${goal} >"${WORK_DIR}/${name}-build.log" 2>&1); then
      local tests
      tests="$(grep -E '^\[(INFO|WARNING|ERROR)\] Tests run:' "${WORK_DIR}/${name}-build.log" | tail -1 | sed -E 's/^\[[A-Z]+\] //')"
      record "PASS module ${name}: cd ${dir#"${REPO_ROOT}/"} && ./mvnw -B ${goal} (JDK ${jdk})${tests:+ - ${tests}}"
    else
      tail -60 "${WORK_DIR}/${name}-build.log" >&2
      record "FAIL module ${name}: cd ${dir#"${REPO_ROOT}/"} && ./mvnw -B ${goal} (JDK ${jdk})"
      FAILED=1
    fi
  done
}

start_postgres() {
  cat >"${WORK_DIR}/compose.parity.yml" <<YAML
services:
  legacy-portal-db:
    ports:
      - "127.0.0.1:${PG_PORT}:5432"
YAML
  docker compose -f "${COMPOSE_FILE}" -f "${WORK_DIR}/compose.parity.yml" down -v >/dev/null 2>&1 || true
  PG_STARTED=1
  DB_PASSWORD="${DB_PASSWORD}" docker compose -f "${COMPOSE_FILE}" -f "${WORK_DIR}/compose.parity.yml" \
    up -d --wait legacy-portal-db >"${WORK_DIR}/compose.log" 2>&1 || { cat "${WORK_DIR}/compose.log" >&2; return 1; }
}

start_module() {
  local profile="$1" name="$2" dir="$3" jdk="$4" port="$5" run="$6"
  local jar
  jar="$(find "${dir}/target" -maxdepth 1 -name '*.jar' ! -name '*-plain.jar' ! -name '*.original' | head -1)"
  [[ -n "${jar}" ]] || { log "no jar under ${dir}/target"; return 1; }
  local -a env_args=("SERVER_PORT=${port}")
  if [[ "${profile}" == "postgres" ]]; then
    env_args+=(
      "SPRING_PROFILES_ACTIVE=postgres"
      "SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:${PG_PORT}/legacyportal"
      "SPRING_DATASOURCE_USERNAME=legacyportal"
      "SPRING_DATASOURCE_PASSWORD=${DB_PASSWORD}"
    )
  fi
  env "${env_args[@]}" "$(jdk_home "${jdk}")/bin/java" -jar "${jar}" \
    >"${WORK_DIR}/${name}-${profile}-${run}.log" 2>&1 &
  PIDS+=("$!")
}

wait_ready() {
  local name="$1" port="$2" log_file="$3" deadline=$((SECONDS + 180))
  until curl -fsS "http://127.0.0.1:${port}/actuator/health/readiness" >/dev/null 2>&1; do
    if (( SECONDS > deadline )); then
      tail -60 "${log_file}" >&2
      log "${name} not ready on :${port}"
      return 1
    fi
    sleep 1
  done
}

run_parity() {
  local profile="$1" run="$2" entry name dir jdk port url_var
  local -a url_env=()
  if lsof -iTCP:"${MONOLITH_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    log "port ${MONOLITH_PORT} is already in use; stop the running legacy-portal first"
    return 1
  fi
  [[ "${profile}" == "postgres" ]] && { start_postgres || return 1; }
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name dir jdk port url_var <<<"${entry}"
    start_module "${profile}" "${name}" "${dir}" "${jdk}" "${port}" "${run}" || return 1
    [[ -n "${url_var}" ]] && url_env+=("${url_var}=http://localhost:${port}")
  done
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name _ _ port _ <<<"${entry}"
    wait_ready "${name}" "${port}" "${WORK_DIR}/${name}-${profile}-${run}.log" || return 1
  done
  local out="${WORK_DIR}/parity-${profile}-${run}.log"
  local rc=0
  (cd "${REPO_ROOT}" && env ${url_env[@]+"${url_env[@]}"} \
    uv run --quiet --no-project --with-requirements "${PARITY_DIR}/requirements.txt" \
    python -m pytest -c "${PARITY_DIR}/pytest.ini" "${PARITY_DIR}" -q) >"${out}" 2>&1 || rc=$?
  PARITY_RESULT="$(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' "${out}" | tail -1 | tr -d '=' | sed -E 's/^ +| +$//g; s/ in [0-9.]+s$//')"
  [[ ${rc} -eq 0 ]] || cat "${out}" >&2
  return ${rc}
}

if [[ "${SKIP_BUILD}" == "1" ]]; then
  log "skipping module build/test"
else
  build_modules
fi

GOLDEN_BEFORE="$(cd "${PARITY_DIR}/golden" && sha256sum ./*.json | sha256sum | cut -c1-12)"
for profile in "${PROFILES[@]}"; do
  for run in $(seq 1 "${RUNS}"); do
    PARITY_RESULT=""
    log "parity ${profile} run ${run}/${RUNS}"
    if run_parity "${profile}" "${run}"; then
      record "PASS parity ${profile} run ${run}/${RUNS}: make parity-legacy-portal (${profile}, run ${run}/${RUNS}) - ${PARITY_RESULT}"
    else
      record "FAIL parity ${profile} run ${run}/${RUNS}: make parity-legacy-portal (${profile}, run ${run}/${RUNS}) - ${PARITY_RESULT:-did not run}"
      FAILED=1
    fi
    stop_processes
    stop_postgres
  done
done
GOLDEN_AFTER="$(cd "${PARITY_DIR}/golden" && sha256sum ./*.json | sha256sum | cut -c1-12)"
[[ "${GOLDEN_BEFORE}" == "${GOLDEN_AFTER}" ]] || { record "FAIL golden transcripts changed during verification"; FAILED=1; }

targets="$(for entry in "${MODULES[@]}"; do IFS='|' read -r name _ _ port _ <<<"${entry}"; printf '%s:%s ' "${name}" "${port}"; done)"
echo
echo "=== legacy-portal verify-stage summary ==="
echo "commit:  $(git -C "${REPO_ROOT}" rev-parse --short HEAD)$(git -C "${REPO_ROOT}" diff --quiet HEAD -- || echo ' (dirty)')"
echo "targets: ${targets% }"
echo "golden:  $(find "${PARITY_DIR}/golden" -name '*.json' | wc -l | tr -d ' ') transcripts, sha256 ${GOLDEN_AFTER}"
printf '%s\n' "${SUMMARY[@]}"
echo "--- trailers ---"
for line in "${SUMMARY[@]}"; do
  [[ "${line}" == PASS* ]] && echo "Verified-by: ${line#PASS *: }"
done
if [[ "${FAILED}" == "1" ]]; then
  echo "RESULT: FAIL"
  exit 1
fi
echo "RESULT: PASS"
