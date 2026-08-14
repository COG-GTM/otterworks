---
name: legacy-etl-demo
description: How to run and verify the legacy polyglot batch estate under etl/legacy-extra/ (CUSTBILL chain) for the Databricks migration demo.
---

# Legacy ETL batch estate (etl/legacy-extra/)

CLI-only demo estate; no web UI. Requires `ksh` (`sudo apt-get install -y ksh`) and, for the SFTP fixture, docker + `sshpass`.

## Run the chain
- `export OTTERWORKS_LEGACY_ROOT=/tmp/otterworks-legacy-<something>` for an isolated run root (default /tmp/otterworks-legacy). Dirs: sftp-drop/upload, incoming, archive, parsed, reports.
- `make legacy-etl-list` — list jobs.
- `make legacy-etl-gen-data NS=dev` — deterministic generator (same NS ⇒ byte-identical files; case-insensitive: dev==DEV; anagram-safe: ved differs). Extra args via `perl etl/legacy-extra/tools/gen_sample_data.pl <NS> <NFILES> <ROWS>`.
- `make legacy-etl-run JOB=sftp_ingest_poll|parse_custbill_fixedwidth|finance_excel_report|run_all` in that order. run_all uses `RUN_ALL_SLEEP` (Makefile defaults it to 0; the script alone defaults 600s).

## Verify
- parsed/*.psv: 6 pipe fields, ISO dates, 2-decimal amounts, ccy USD/EUR/GBP, rt 01/02.
- reports/finance_billing_YYYYMMDD.csv (and byte-identical .xls): recompute with
  `cat parsed/*.psv | awk -F'|' '{k=$5","(($6=="01")?"INVOICE":"CREDIT"); c[k]++; t[k]+=$4} END{for(k in c) printf "%s,%d,%.2f\n",k,c[k],t[k]}'` and compare.
- Fresh empty root: finance_excel_report must still exit 0 with header-only report.

## SFTP fixture
- `make legacy-sftp-up` (passes LEGACY_SFTP_UID=$(id -u) so the bind-mounted drop dir is writable by both host and container), then
  `sshpass -p mvsprod sftp -P 52222 -o StrictHostKeyChecking=no mainframe@127.0.0.1` and `put <file> upload/`.
- Ingest must both stage the file to incoming/ AND delete it from the drop dir (proves uid mapping works). `make legacy-sftp-down` to clean up.

## Gotchas
- Intentional legacy quirks (do NOT flag as bugs): /tmp/*.lock files never removed ("lock file present ... continuing anyway" messages are expected), 2>/dev/null||true suppression, hardcoded prod/uat hostname branches, plaintext mvsprod credential, /tmp/cb_body.$$ temp file.
- mawk (default awk) does not support `{n}` regex intervals — use grep -E for field validation, not awk regexes.
