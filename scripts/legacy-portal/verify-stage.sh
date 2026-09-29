#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Verify one stage of the legacy-portal decomposition locally (nothing is deployed).
#
#   1. Build and test the Maven reactor (services/portal-parent, JDK 17): portal-common and
#      services/{announcements,preferences,feedback}-service.
#   2. For each profile and run, start a fresh target, replay tests/parity/legacy_portal against
#      it with every context at its own service (ANNOUNCEMENTS_URL / PREFERENCES_URL /
#      FEEDBACK_URL), then tear it down:
#        h2        the three JARs on the host, embedded H2
#        postgres  the three JARs on the host against the root compose postgres, each connected
#                  as its own role (<context> / <CONTEXT>_DB_PASSWORD)
#        compose   the three service images from docker-compose.yml with docker-compose.infra.yml
#                  postgres, started with `up --wait` (all healthy) and checked for role/schema
#                  ownership
#      The PostgreSQL profiles run in an isolated compose project (own containers, network,
#      volume and host ports), recreated with `down -v`, so the developer stack is not touched.
#   3. Print a summary usable as commit trailers and as the ticket status note.
#
# Usage:
#   scripts/legacy-portal/verify-stage.sh [--profile h2|postgres|compose|all|<a>,<b>] [--runs N]
#                                         [--skip-build] [--skip-module-tests]
#                                         [--skip-image-build]
#   --skip-image-build  compose profile uses the already built otterworks-<service> images
#                       (e.g. from `make portal-build`) instead of building them
# Env:
#   JDK17_HOME                JDK location (auto-detected under /usr/lib/jvm otherwise)
#   PARITY_PG_PORT            host port for the parity PostgreSQL (default 55495)
#   ANNOUNCEMENTS_PORT / PREFERENCES_PORT / FEEDBACK_PORT
#                             host ports of the services (default 8096 / 8097 / 8098)
#   ANNOUNCEMENTS_DB_PASSWORD / PREFERENCES_DB_PASSWORD / FEEDBACK_DB_PASSWORD
#                             PostgreSQL passwords of the per-service roles (default: role name)
# ------------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REACTOR_DIR="${REPO_ROOT}/services/portal-parent"
REACTOR_JDK=17
PARITY_DIR="${REPO_ROOT}/tests/parity/legacy_portal"
PG_PORT="${PARITY_PG_PORT:-55495}"
PROJECT=otterworks-portal-verify
DB_NAME=otterworks

PROFILE=all
RUNS=2
SKIP_BUILD=0
SKIP_MODULE_TESTS=0
SKIP_IMAGE_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --runs) RUNS="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-module-tests) SKIP_MODULE_TESTS=1; shift ;;
    --skip-image-build) SKIP_IMAGE_BUILD=1; shift ;;
    -h|--help) sed -n '2,35p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "${PROFILE}" == all ]] && PROFILE=h2,postgres,compose
IFS=',' read -r -a PROFILES <<<"${PROFILE}"
for profile in "${PROFILES[@]}"; do
  case "${profile}" in
    h2|postgres|compose) ;;
    *) echo "--profile must be h2, postgres, compose, all or a comma-separated list" >&2; exit 2 ;;
  esac
done
[[ "${RUNS}" =~ ^[1-9][0-9]*$ ]] || { echo "--runs must be a positive integer" >&2; exit 2; }

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/legacy-portal-verify.XXXXXX")"
PIDS=()
STACK_STARTED=0
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

# name|dir|host port|container port|context url var|db role|schema
MODULES=()
for ctx in announcements preferences feedback; do
  upper="$(echo "${ctx}" | tr '[:lower:]' '[:upper:]')"
  port_var="${upper}_PORT"
  case "${ctx}" in
    announcements) default_port=8096; schema=announcements ;;
    preferences) default_port=8097; schema=user_preferences ;;
    *) default_port=8098; schema=feedback ;;
  esac
  MODULES+=("${ctx}-service|${REPO_ROOT}/services/${ctx}-service|${!port_var:-${default_port}}|${default_port}|${upper}_URL|${ctx}|${schema}")
done

# Password of a per-service PostgreSQL role: <ROLE>_DB_PASSWORD, defaulting to the role name.
db_password() {
  local var
  var="$(echo "$1" | tr '[:lower:]' '[:upper:]')_DB_PASSWORD"
  echo "${!var:-$1}"
}

# The root compose stack in its own project: containers, network, volume and host ports differ
# from the developer stack, and images are shared with it (otterworks-<service>).
write_override() {
  local entry name port container_port role upper
  cat >"${WORK_DIR}/compose.verify.yml" <<YAML
services:
  postgres:
    container_name: !reset null
    ports: !override
      - "127.0.0.1:${PG_PORT}:5432"
  portal-db-init:
    container_name: !reset null
    environment:
YAML
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r _ _ _ _ _ role _ <<<"${entry}"
    upper="$(echo "${role}" | tr '[:lower:]' '[:upper:]')"
    echo "      ${upper}_DB_PASSWORD: \"$(db_password "${role}")\"" >>"${WORK_DIR}/compose.verify.yml"
  done
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name _ port container_port _ role _ <<<"${entry}"
    upper="$(echo "${role}" | tr '[:lower:]' '[:upper:]')"
    cat >>"${WORK_DIR}/compose.verify.yml" <<YAML
  ${name}:
    image: otterworks-${name}
    container_name: !reset null
    ports: !override
      - "127.0.0.1:${port}:${container_port}"
    environment:
      SPRING_DATASOURCE_PASSWORD: "$(db_password "${role}")"
YAML
  done
  cat >>"${WORK_DIR}/compose.verify.yml" <<YAML
networks:
  default:
    name: ${PROJECT}-network
YAML
}

compose() {
  docker compose -p "${PROJECT}" -f "${REPO_ROOT}/docker-compose.infra.yml" \
    -f "${REPO_ROOT}/docker-compose.yml" -f "${WORK_DIR}/compose.verify.yml" "$@"
}

service_names() {
  local entry name
  for entry in "${MODULES[@]}"; do IFS='|' read -r name _ <<<"${entry}"; echo "${name}"; done
}

stop_processes() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    [[ -n "${pid}" ]] || continue
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  done
  PIDS=()
}

stop_stack() {
  if [[ "${STACK_STARTED}" == "1" ]]; then
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    STACK_STARTED=0
  fi
}

cleanup() {
  stop_processes
  stop_stack
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

record() {
  SUMMARY+=("$1")
  log "$1"
}

# Module directories listed in the reactor POM, in declaration order.
reactor_modules() {
  sed -n 's:.*<module>\(.*\)</module>.*:\1:p' "${REACTOR_DIR}/pom.xml" | while read -r rel; do
    (cd "${REACTOR_DIR}/${rel}" && pwd)
  done
}

# "Tests run: N, Failures: F, Errors: E, Skipped: S" summed over a module's surefire
# (unit) and failsafe (*IT integration) reports.
module_tests() {
  local -a reports=()
  local kind
  for kind in surefire failsafe; do
    compgen -G "$1/target/${kind}-reports/TEST-*.xml" >/dev/null && reports+=("$1/target/${kind}-reports"/TEST-*.xml)
  done
  [[ ${#reports[@]} -gt 0 ]] || return 0
  sed -n 's/.*<testsuite [^>]*>.*/&/p' "${reports[@]}" | awk '
    { for (i = 1; i <= NF; i++) if (match($i, /^(tests|failures|errors|skipped)="[0-9]+"/)) {
        split($i, kv, "\""); sub(/=.*/, "", kv[1]); n[kv[1]] += kv[2] } }
    END { printf "Tests run: %d, Failures: %d, Errors: %d, Skipped: %d", n["tests"], n["failures"], n["errors"], n["skipped"] }'
}

build_modules() {
  local goal dir name tests
  goal="clean verify"
  [[ "${SKIP_MODULE_TESTS}" == "1" ]] && goal="clean package -DskipTests"
  local cmd="cd ${REACTOR_DIR#"${REPO_ROOT}/"} && ./mvnw -B ${goal} (JDK ${REACTOR_JDK})"
  log "building reactor: ${cmd}"
  # shellcheck disable=SC2086
  if (cd "${REACTOR_DIR}" && JAVA_HOME="$(jdk_home "${REACTOR_JDK}")" ./mvnw -B ${goal} >"${WORK_DIR}/reactor-build.log" 2>&1); then
    while read -r dir; do
      name="$(basename "${dir}")"
      tests="$(module_tests "${dir}")"
      record "PASS module ${name}: ${cmd}${tests:+ - ${name}: ${tests}}"
    done < <(reactor_modules)
  else
    tail -60 "${WORK_DIR}/reactor-build.log" >&2
    record "FAIL reactor: ${cmd}"
    FAILED=1
  fi
}

build_images() {
  local cmd
  cmd="docker compose -f docker-compose.infra.yml -f docker-compose.yml build $(service_names | tr '\n' ' ')"
  cmd="${cmd% }"
  # shellcheck disable=SC2046
  if compose build $(service_names) >"${WORK_DIR}/image-build.log" 2>&1; then
    record "PASS images: ${cmd} - built $(service_names | sed 's/^/otterworks-/' | tr '\n' ' ' | sed 's/ $//')"
  else
    tail -60 "${WORK_DIR}/image-build.log" >&2
    record "FAIL images: ${cmd}"
    FAILED=1
  fi
}

start_postgres() {
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  STACK_STARTED=1
  { compose up -d --wait postgres && compose run --rm portal-db-init; } >"${WORK_DIR}/compose.log" 2>&1 \
    || { cat "${WORK_DIR}/compose.log" >&2; return 1; }
}

start_compose_services() {
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  STACK_STARTED=1
  # shellcheck disable=SC2046
  compose up -d --no-build --wait --wait-timeout 300 $(service_names) >"${WORK_DIR}/compose.log" 2>&1 \
    || { cat "${WORK_DIR}/compose.log" >&2; compose logs --tail 60 >&2 || true; return 1; }
}

psql_query() {
  compose exec -T postgres psql -U otterworks -d "${DB_NAME}" -Atc "$1"
}

# Each schema exists, is owned by its service role, and (compose) the service is connected as it.
check_ownership() {
  local profile="$1" entry name role schema owner connected
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name _ _ _ _ role schema <<<"${entry}"
    owner="$(psql_query "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '${schema}'")"
    if [[ "${owner}" != "${role}" ]]; then
      log "schema ${schema} owned by '${owner}', expected ${role}"
      return 1
    fi
    connected="$(psql_query "SELECT count(*) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND usename = '${role}'")"
    if [[ "${connected}" == 0 ]]; then
      log "${name} has no connection as role ${role}"
      return 1
    fi
  done
  [[ "${profile}" == compose ]] || return 0
  local health
  for name in $(service_names); do
    health="$(docker inspect -f '{{.State.Health.Status}}' "$(compose ps -q "${name}")")"
    [[ "${health}" == healthy ]] || { log "${name} is ${health}, expected healthy"; return 1; }
  done
}

start_module() {
  local profile="$1" name="$2" dir="$3" port="$4" run="$5" role="$6"
  local jar
  jar="$(find "${dir}/target" -maxdepth 1 -name '*.jar' ! -name '*-plain.jar' ! -name '*.original' | head -1)"
  [[ -n "${jar}" ]] || { log "no jar under ${dir}/target"; return 1; }
  local -a env_args=("SERVER_PORT=${port}")
  if [[ "${profile}" == "postgres" ]]; then
    env_args+=(
      "SPRING_PROFILES_ACTIVE=postgres"
      "SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:${PG_PORT}/${DB_NAME}"
      "SPRING_DATASOURCE_USERNAME=${role}"
      "SPRING_DATASOURCE_PASSWORD=$(db_password "${role}")"
    )
  fi
  env "${env_args[@]}" "$(jdk_home "${REACTOR_JDK}")/bin/java" -jar "${jar}" \
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
  local profile="$1" run="$2" entry name dir port url_var role
  local -a url_env=()
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name _ port _ _ _ _ <<<"${entry}"
    if lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      log "port ${port} (${name}) is already in use; stop it first (e.g. make portal-down)"
      return 1
    fi
  done
  case "${profile}" in
    postgres) start_postgres || return 1 ;;
    compose) start_compose_services || { PARITY_RESULT="compose services not healthy"; return 1; } ;;
  esac
  for entry in "${MODULES[@]}"; do
    IFS='|' read -r name dir port _ url_var role _ <<<"${entry}"
    url_env+=("${url_var}=http://localhost:${port}")
    [[ "${profile}" == compose ]] && continue
    start_module "${profile}" "${name}" "${dir}" "${port}" "${run}" "${role}" || return 1
  done
  if [[ "${profile}" != compose ]]; then
    for entry in "${MODULES[@]}"; do
      IFS='|' read -r name _ port _ _ _ _ <<<"${entry}"
      wait_ready "${name}" "${port}" "${WORK_DIR}/${name}-${profile}-${run}.log" || return 1
    done
  fi
  if [[ "${profile}" != h2 ]]; then
    check_ownership "${profile}" || { PARITY_RESULT="role/schema/health check failed"; return 1; }
  fi
  local out="${WORK_DIR}/parity-${profile}-${run}.log"
  local rc=0
  (cd "${REPO_ROOT}" && env "${url_env[@]}" \
    uv run --quiet --no-project --with-requirements "${PARITY_DIR}/requirements.txt" \
    python -m pytest -c "${PARITY_DIR}/pytest.ini" "${PARITY_DIR}" -q) >"${out}" 2>&1 || rc=$?
  PARITY_RESULT="$(grep -E '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' "${out}" | tail -1 | tr -d '=' | sed -E 's/^ +| +$//g; s/ in [0-9.]+s$//')"
  [[ ${rc} -eq 0 ]] || cat "${out}" >&2
  return ${rc}
}

write_override

if [[ "${SKIP_BUILD}" == "1" ]]; then
  log "skipping module build/test"
else
  build_modules
fi
if [[ " ${PROFILES[*]} " == *" compose "* ]]; then
  if [[ "${SKIP_IMAGE_BUILD}" == "1" ]]; then
    log "skipping image build; using existing otterworks-<service> images"
  else
    build_images
  fi
fi

GOLDEN_BEFORE="$(cd "${PARITY_DIR}/golden" && sha256sum ./*.json | sha256sum | cut -c1-12)"
for profile in "${PROFILES[@]}"; do
  for run in $(seq 1 "${RUNS}"); do
    PARITY_RESULT=""
    log "parity ${profile} run ${run}/${RUNS}"
    detail=""
    [[ "${profile}" == compose ]] && detail="; 3/3 healthy, schemas owned by and connected as their service role"
    [[ "${profile}" == postgres ]] && detail="; schemas owned by and connected as their service role"
    if run_parity "${profile}" "${run}"; then
      record "PASS parity ${profile} run ${run}/${RUNS}: make parity-legacy-portal (${profile}, run ${run}/${RUNS}) - ${PARITY_RESULT}${detail}"
    else
      record "FAIL parity ${profile} run ${run}/${RUNS}: make parity-legacy-portal (${profile}, run ${run}/${RUNS}) - ${PARITY_RESULT:-did not run}"
      FAILED=1
    fi
    stop_processes
    stop_stack
  done
done
GOLDEN_AFTER="$(cd "${PARITY_DIR}/golden" && sha256sum ./*.json | sha256sum | cut -c1-12)"
[[ "${GOLDEN_BEFORE}" == "${GOLDEN_AFTER}" ]] || { record "FAIL golden transcripts changed during verification"; FAILED=1; }

targets="$(for entry in "${MODULES[@]}"; do IFS='|' read -r name _ port _ <<<"${entry}"; printf '%s:%s ' "${name}" "${port}"; done)"
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
