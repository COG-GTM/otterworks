#!/bin/bash
# Runs the OLTP then OLAP suites under DBMS_PROFILER (line coverage) and
# DBMS_PLSQL_CODE_COVERAGE (basic-block coverage) and prints per-package
# results. Run inside the fixture container, on a freshly initialised fixture:
#   docker exec otterworks-insurance-<NS>-insurance-oracle-1 \
#     bash /opt/oracle/scripts/insurance/tests/run_coverage.sh
# Package bodies are recompiled at PLSQL_OPTIMIZE_LEVEL=${OPT_LEVEL:-1} for the
# run (level 2 merges header/END lines and inflates the uncovered count) and
# restored to level 2 afterwards.
set -euo pipefail

DB=/opt/oracle/scripts/insurance
TESTS_DIR="${TESTS_DIR:-${DB}/tests}"
OPT_LEVEL="${OPT_LEVEL:-1}"
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT
status=0

run_suite() {
  local user="$1" suite="$2" src="$3" pkg="$4"
  local sql="${WORK}/${user}.sql" log="${WORK}/${user}.log"
  local offset
  offset=$(( $(grep -n '^CREATE OR REPLACE PACKAGE BODY' "${src}" | cut -d: -f1) - 1 ))
  {
    cat <<SQL
SET TERMOUT OFF
@?/rdbms/admin/proftab.sql
SET TERMOUT ON
WHENEVER SQLERROR EXIT FAILURE
EXEC DBMS_PLSQL_CODE_COVERAGE.CREATE_COVERAGE_TABLES(force_it => TRUE)
ALTER PACKAGE ${pkg} COMPILE BODY PLSQL_OPTIMIZE_LEVEL = ${OPT_LEVEL};
VARIABLE rc NUMBER
VARIABLE cov_run NUMBER
EXEC :rc := DBMS_PROFILER.START_PROFILER('${suite}')
EXEC :cov_run := DBMS_PLSQL_CODE_COVERAGE.START_COVERAGE('${suite}')
WHENEVER SQLERROR CONTINUE
SQL
    sed -e '/^WHENEVER /d' -e '/^EXIT;$/d' "${TESTS_DIR}/${suite}"
    cat <<SQL
WHENEVER SQLERROR EXIT FAILURE
EXEC DBMS_PLSQL_CODE_COVERAGE.STOP_COVERAGE
EXEC :rc := DBMS_PROFILER.STOP_PROFILER
SET HEADING OFF FEEDBACK OFF PAGESIZE 0 LINESIZE 32767 TRIMSPOOL ON
SELECT 'LINE|' || COUNT(*) || '|' || SUM(CASE WHEN d.total_occur > 0 THEN 1 ELSE 0 END) || '|'
       || LISTAGG(CASE WHEN d.total_occur = 0 THEN d.line# + ${offset} END, ',') WITHIN GROUP (ORDER BY d.line#)
  FROM plsql_profiler_units u
  JOIN plsql_profiler_data d ON d.runid = u.runid AND d.unit_number = u.unit_number
 WHERE u.runid = (SELECT MAX(runid) FROM plsql_profiler_runs)
   AND u.unit_owner = USER AND u.unit_type = 'PACKAGE BODY' AND u.unit_name = '${pkg}';
SELECT 'BLOCK|' || COUNT(*) || '|' || SUM(b.covered) || '|'
       || LISTAGG(CASE WHEN b.covered = 0 THEN b.line + ${offset} END, ',') WITHIN GROUP (ORDER BY b.block)
  FROM dbmspcc_units u
  JOIN dbmspcc_blocks b ON b.run_id = u.run_id AND b.object_id = u.object_id
 WHERE u.run_id = :cov_run AND u.owner = USER AND u.type = 'PACKAGE BODY' AND u.name = '${pkg}';
EXIT
SQL
  } > "${sql}"

  sqlplus -s "${user}/${user}@localhost:1521/FREEPDB1" @"${sql}" > "${log}" 2>&1 || true
  grep -E '^(PASS|FAIL) ' "${log}" || true
  if ! grep -q 'TESTS: ALL PASS' "${log}"; then
    echo "!! ${suite} did not pass"; grep -E 'ORA-|SP2-|TESTS:' "${log}" || true
    status=1
  fi
  local line block
  line=$(grep '^LINE|' "${log}" || echo 'LINE|0|0|')
  block=$(grep '^BLOCK|' "${log}" || echo 'BLOCK|0|0|')
  echo "COV|${pkg}|${src#${DB}/}|${line#LINE|}|${block#BLOCK|}" >> "${WORK}/cov"
}

run_suite commission_pay run_tests.sql      "${DB}/oltp/03_commission_pkg.sql" COMMISSION_PKG
run_suite commission_dw  run_olap_tests.sql "${DB}/olap/02_etl_pkg.sql"        DW_ETL_PKG

echo "----"
awk -F'|' '
  function pct(a, b) { return b ? sprintf("%.1f%%", 100 * a / b) : "n/a" }
  {
    printf "%-15s %-28s lines %s (%d/%d)  blocks %s (%d/%d)\n", $2, $3, pct($5, $4), $5, $4, pct($8, $7), $8, $7
    printf "%-15s   uncovered lines: %s | uncovered blocks start at: %s\n", "", ($6 ? $6 : "-"), ($9 ? $9 : "-")
    lt += $4; lc += $5; bt += $7; bc += $8
  }
  END { printf "TOTAL           line %s (%d/%d)  block %s (%d/%d)\n", pct(lc, lt), lc, lt, pct(bc, bt), bc, bt }
' "${WORK}/cov"
exit "${status}"
