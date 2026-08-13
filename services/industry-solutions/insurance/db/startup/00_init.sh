#!/bin/bash
# This directory (db/startup) is mounted into /opt/oracle/scripts/startup,
# which the Oracle Free image runs on every boot once the database is open.
# (The image ships a prebuilt DB, so /opt/oracle/scripts/setup never fires —
# startup is the reliable hook.) Only this orchestrator lives here: anything
# else in the mounted directory would be auto-executed as SYSDBA in the CDB
# root, which is the wrong container for our schemas.
# Idempotent: skips everything once the COMMISSION_PAY user exists.
#
# The image *sources* startup scripts, so all work happens in a subshell to
# keep `set -e` and any failure from tearing down the container entrypoint.
(
  set -euo pipefail

  SQL_DIR=/opt/oracle/scripts/insurance

  existing=$(sqlplus -s "system/${ORACLE_PWD}@localhost:1521/FREEPDB1" <<'SQL'
SET HEADING OFF FEEDBACK OFF PAGESIZE 0
SELECT COUNT(*) FROM all_users WHERE username = 'COMMISSION_PAY';
EXIT;
SQL
  )

  if [ "$(echo "${existing}" | tr -d '[:space:]')" != "0" ]; then
    echo "== insurance fixture already initialized, skipping"
    exit 0
  fi

  run_sql() {
    local conn="$1" file="$2"
    echo "== ${file} (${conn%%/*})"
    sqlplus -s "${conn}@localhost:1521/FREEPDB1" @"${file}"
  }

  run_sql "system/${ORACLE_PWD}"          "${SQL_DIR}/setup/01_users.sql"
  run_sql "commission_pay/commission_pay" "${SQL_DIR}/oltp/01_tables.sql"
  run_sql "commission_pay/commission_pay" "${SQL_DIR}/oltp/02_seed.sql"
  run_sql "commission_pay/commission_pay" "${SQL_DIR}/oltp/03_commission_pkg.sql"
  run_sql "commission_dw/commission_dw"   "${SQL_DIR}/olap/01_star_schema.sql"
  run_sql "commission_dw/commission_dw"   "${SQL_DIR}/olap/02_etl_pkg.sql"

  echo "== insurance fixture ready"
) || echo "== insurance fixture initialization FAILED (see errors above)"
