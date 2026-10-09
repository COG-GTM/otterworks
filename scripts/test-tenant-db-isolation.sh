#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Tests for per-tenant Postgres credentials.
#
# Each tenant's services must log in as their own role, which can open only
# that tenant's database -- never the RDS master, which can open every
# tenant's database and the golden one. Two parts:
#
#   1. Wiring (runs anywhere): build_helm_args hands SQL-backed services the
#      tenant role, and no service sees the master user or password.
#   2. Grants (needs docker; skipped otherwise): the provisioning and drop SQL
#      run against a real Postgres whose "master" is a non-superuser with
#      CREATEDB/CREATEROLE, as on RDS. PG_IMAGE overrides the image.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else nope "$1 (expected '$3', got '$2')"; fi; }

# shellcheck source=lib/tenant-common.sh
. "${SCRIPT_DIR}/lib/tenant-common.sh"
log()  { :; }
warn() { :; }

echo "# naming"
check "role derives from the tenant database" "$(tenant_db_role Alice-1)" "otterworks_alice_1_app"
check "role derives from a database name" "$(tenant_db_role_for_db otterworks_bob)" "otterworks_bob_app"

echo "# helm wiring"
MASTER_USER="otterworks_admin"; MASTER_PW="master-$(openssl rand -hex 8)"
TENANT_PW="tenant-$(openssl rand -hex 8)"
DB_USER="${MASTER_USER}"; DB_PASSWORD="${MASTER_PW}"
# shellcheck disable=SC2034
{
  T_DB_NAME="otterworks_alice"; T_DB_USER="otterworks_alice_app"; T_DB_PASSWORD="${TENANT_PW}"
  T_REDIS_HOST="redis"; T_MEILI_URL="http://meilisearch:7700"; T_WIRE_EVENTING=false
  DB_ENDPOINT_HOST="pgbouncer"; DB_ENDPOINT_PORT=6432; DB_SESSION_PORT=6433
  JWT_SECRET="jwt"; SECRET_KEY_BASE="skb"; AWS_REGION="us-east-1"
}
for svc in api-gateway auth-service file-service document-service collab-service notification-service \
           search-service analytics-service admin-service audit-service report-service web-app admin-dashboard; do
  set +u; build_helm_args "${svc}"; set -u
  all="${EXTRA_ARGS[*]-} ${SECRET_KV[*]-}"
  case "${all}" in *"${MASTER_PW}"*) nope "${svc}: master password not exposed" ;; *) ok "${svc}: master password not exposed" ;; esac
  case "${all}" in *"=${MASTER_USER}"*|*"//${MASTER_USER}:"*) nope "${svc}: master user not exposed" ;; *) ok "${svc}: master user not exposed" ;; esac
  case "${svc}" in
    auth-service|document-service|analytics-service|admin-service|report-service)
      case "${all}" in *"${TENANT_PW}"*) ok "${svc}: gets the tenant password" ;; *) nope "${svc}: gets the tenant password" ;; esac
      case "${all}" in *"${T_DB_USER}"*) ok "${svc}: gets the tenant role" ;; *) nope "${svc}: gets the tenant role" ;; esac ;;
  esac
done

echo "# drop job"
# shellcheck disable=SC2034
RDS_HOST="localhost"; RDS_PORT=5432
RENDERED="$(mktemp)"; trap 'rm -f "${RENDERED}"' EXIT
kubectl() { case "$*" in *"apply -n"*) cat > "${RENDERED}" ;; *apply*) cat >/dev/null ;; *wait*) return 0 ;; esac; }
drop_tenant_db otterworks_alice otterworks-platform >/dev/null
unset -f kubectl
DROP_SCRIPT="$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"]["template"]["spec"]["containers"][0]["args"][0])' "${RENDERED}")"
case "${DROP_SCRIPT}" in *'DROP ROLE IF EXISTS :"role"'*) ok "drop job drops the role" ;; *) nope "drop job drops the role" ;; esac
case "$(cat "${RENDERED}")" in *"${MASTER_PW}"*) nope "drop job spec holds no password" ;; *) ok "drop job spec holds no password" ;; esac

# ------------------------------------------------------------------------------
PG_IMAGE="${PG_IMAGE:-postgres:16-alpine}"
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  echo "# grants: SKIPPED (docker unavailable)"
else
  echo "# grants (${PG_IMAGE})"
  PG="tenant-db-test-$$"; PG_LOG="$(mktemp)"
  trap 'rm -f "${RENDERED}" "${PG_LOG}"; docker rm -f "${PG}" >/dev/null 2>&1' EXIT
  docker run -d --name "${PG}" -e POSTGRES_PASSWORD=super -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
    -e POSTGRES_INITDB_ARGS=--auth=scram-sha-256 "${PG_IMAGE}" >/dev/null
  for _ in $(seq 60); do docker exec "${PG}" pg_isready -U postgres -h localhost >/dev/null 2>&1 && break; sleep 1; done
  sleep 1
  # RDS-like master: not a superuser. It owns the golden DB and a tenant DB
  # created before per-tenant roles existed.
  docker exec -i -e PGPASSWORD=super "${PG}" psql -q -U postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
CREATE ROLE ${MASTER_USER} LOGIN CREATEDB CREATEROLE PASSWORD '${MASTER_PW}';
CREATE DATABASE otterworks OWNER ${MASTER_USER};
CREATE DATABASE otterworks_legacy OWNER ${MASTER_USER};
SQL
  as() {  # as <user> <password> <db> <sql>
    docker exec -e PGPASSWORD="$2" "${PG}" psql -X -qtA -h localhost -U "$1" -d "$3" -v ON_ERROR_STOP=1 -c "$4" 2>&1
  }
  as "${MASTER_USER}" "${MASTER_PW}" otterworks "CREATE TABLE users(id int, password_hash text); INSERT INTO users VALUES (1,'h')" >/dev/null
  as "${MASTER_USER}" "${MASTER_PW}" otterworks_legacy "CREATE TABLE docs(id serial primary key)" >/dev/null
  provision() {  # provision <db> <password>
    tenant_db_provision_sql | docker exec -i -e PGPASSWORD="${MASTER_PW}" -e TENANT_DB_PASSWORD="$2" "${PG}" \
      psql -X -q -h localhost -U "${MASTER_USER}" -d otterworks -v db="$1" -v role="$(tenant_db_role_for_db "$1")" \
      -v conn_limit=20 > "${PG_LOG}" 2>&1
    local rc=$?
    [ "${rc}" -eq 0 ] || grep -iE 'error|fatal' "${PG_LOG}" | head -3 | sed 's/^/    | /'
    return "${rc}"
  }
  A_PW="a-$(openssl rand -hex 12)"; B_PW="b-$(openssl rand -hex 12)"; L_PW="l-$(openssl rand -hex 12)"
  provision otterworks_alice "${A_PW}"; check "provision tenant alice" "$?" 0
  provision otterworks_bob "${B_PW}";   check "provision tenant bob" "$?" 0
  provision otterworks_alice "${A_PW}"; check "re-provision is idempotent" "$?" 0
  provision otterworks_carol "";        [ $? -ne 0 ] && ok "empty role password is refused" || nope "empty role password is refused"

  A=otterworks_alice_app
  check "tenant role works in its own DB" "$(as ${A} "${A_PW}" otterworks_alice "CREATE TABLE t(x int); INSERT INTO t VALUES (7); SELECT x FROM t")" 7
  for db in otterworks otterworks_bob otterworks_legacy; do
    out="$(as ${A} "${A_PW}" "${db}" "SELECT 1")"
    case "${out}" in *"permission denied"*) ok "tenant role cannot connect to ${db}" ;; *) nope "tenant role cannot connect to ${db} (${out})" ;; esac
  done
  check "tenant role has no elevated attributes" \
    "$(as ${A} "${A_PW}" otterworks_alice "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolreplication FROM pg_roles WHERE rolname=current_user")" f
  out="$(as ${A} "${B_PW}" otterworks_alice "SELECT 1")"
  case "${out}" in *"authentication failed"*) ok "another tenant's password is rejected" ;; *) nope "another tenant's password is rejected (${out})" ;; esac
  check "master still opens the golden DB" "$(as "${MASTER_USER}" "${MASTER_PW}" otterworks "SELECT count(*) FROM users")" 1
  check "pooler credential stored for the role" \
    "$(as "${MASTER_USER}" "${MASTER_PW}" otterworks "SELECT passwd = '${A_PW}' FROM pgbouncer.tenant_credentials WHERE usename='${A}'")" t

  A2_PW="a2-$(openssl rand -hex 12)"
  provision otterworks_alice "${A2_PW}"
  check "rotation keeps data" "$(as ${A} "${A2_PW}" otterworks_alice "SELECT x FROM t")" 7
  case "$(as ${A} "${A_PW}" otterworks_alice "SELECT 1")" in *"authentication failed"*) ok "rotation retires the old password" ;; *) nope "rotation retires the old password" ;; esac

  provision otterworks_legacy "${L_PW}"; check "provision a pre-existing tenant DB" "$?" 0
  check "pre-existing tables handed to the tenant role" \
    "$(as otterworks_legacy_app "${L_PW}" otterworks_legacy "ALTER TABLE docs ADD COLUMN title text; INSERT INTO docs(title) VALUES ('x') RETURNING id")" 1

  drop() { docker exec -i -e PGPASSWORD="${MASTER_PW}" "${PG}" sh -c "${DROP_SCRIPT}" >/dev/null 2>&1; }
  drop; check "drop job succeeds" "$?" 0
  drop; check "drop job is idempotent" "$?" 0
  check "drop removes the database" "$(as "${MASTER_USER}" "${MASTER_PW}" otterworks "SELECT count(*) FROM pg_database WHERE datname='otterworks_alice'")" 0
  check "drop removes the role" "$(as "${MASTER_USER}" "${MASTER_PW}" otterworks "SELECT count(*) FROM pg_roles WHERE rolname='${A}'")" 0
  check "drop removes the pooler credential" "$(as "${MASTER_USER}" "${MASTER_PW}" otterworks "SELECT count(*) FROM pgbouncer.tenant_credentials WHERE usename='${A}'")" 0
  check "other tenants survive the drop" "$(as otterworks_bob_app "${B_PW}" otterworks_bob "SELECT 1")" 1
fi

echo
echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
