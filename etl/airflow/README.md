# OtterWorks ETL — Airflow + PySpark

Orchestrated replacement for the cron-driven scripts in `etl/scripts/` (which stay untouched as the
frozen "before" state). One DAG per legacy job, same schedule (UTC):

| DAG | Schedule | Legacy script | Shape |
|---|---|---|---|
| `analytics_daily` | `0 2 * * *` | `analytics_daily.py` | SQS + DynamoDB → raw zone → **PySpark** aggregate → curated Parquet, data-lake partition, Postgres upsert, report |
| `storage_cleanup_daily` | `30 2 * * *` | `storage_cleanup_daily.py` | S3 inventory + metadata refs → orphans (grace period + ratio guard) → quarantine → report |
| `audit_archive_weekly` | `0 3 * * 0` | `audit_archive_weekly.py` | scan past retention → content-addressed Glacier object → verified delete → compliance report |
| `search_reindex_weekly` | `0 4 * * 0` | `search_reindex_weekly.py` | per index: rebuild `<index>_staging` → validate count → atomic swap (blue/green) |
| `user_activity_daily` | `0 5 * * *` | `user_activity_daily.py` | Postgres summaries + S3 top users → report (+ `latest` pointer that backfills never regress) |

## Layout

```
etl/airflow/
├── dags/                      # DAG files + the otterworks_etl package (mounted as the dags folder)
│   └── otterworks_etl/
│       ├── settings.py        # connection ids, Variable defaults, spark mode
│       ├── common.py          # default_args: retries w/ exponential backoff, SLA, callbacks
│       ├── alerting.py        # Slack / email failure + SLA-miss callbacks (no-op if unconfigured)
│       ├── json_logging.py    # JSON formatter + log_event()
│       ├── transforms/        # pure functions (unit-tested, no I/O)
│       ├── tasks/             # task callables using S3Hook/SqsHook/DynamoDBHook/PostgresHook/HttpHook
│       └── sql/
├── config/log_config.py       # Airflow logging config with JSON formatters
├── tests/                     # DAG integrity, transforms, moto-backed task tests, alerting
├── scripts/seed_local.py      # provision + seed LocalStack (refuses non-local endpoints)
├── Dockerfile                 # apache/airflow:2.10.5 + JRE + spark provider + pyspark
├── docker-compose.yml         # local runner (LocalExecutor) joined to otterworks-network
├── .env.example               # connection/variable placeholders
└── airflow_settings.yaml      # same inventory in Astro CLI format
etl/spark/
├── jobs/analytics_daily_aggregate.py   # self-contained PySpark job (local[*] or EMR step)
└── tests/                              # local-mode parity tests vs the pure-Python reference
```

## Connections and Variables

No credentials live in the repo; `etl/config.ini` is not read. Ids (see `settings.py`):

| Id | Type | Used for |
|---|---|---|
| `aws_default` | aws | S3, SQS, DynamoDB, EMR (override id with `OTTERWORKS_AWS_CONN_ID`) |
| `otterworks_postgres` | postgres | `analytics_daily_summary` upsert / read |
| `otterworks_meilisearch` | http | MeiliSearch admin API (password = API key) |
| `otterworks_document_service`, `otterworks_file_service` | http | reindex sources |
| `spark_default` | spark | `spark-submit` master (`local[*]` locally) |
| `otterworks_slack_webhook` | http | optional failure alerts (password = webhook path) |

Non-secret config is the JSON Variable `otterworks_etl`, merged over `settings.DEFAULTS`
(bucket/table/queue names, retention days, cleanup guard, `alert_emails`, `emr_cluster_id`, ...).

## Idempotency and backfills

Every task is keyed by the run's `ds` / `data_interval_end`, never wall-clock "yesterday":
raw objects are named by content digest or overwritten per `ds`, curated/report outputs are
overwritten per `ds`, Postgres uses `INSERT ... ON CONFLICT (report_date) DO UPDATE`, the audit
archive object key is a digest of the archived key set and source rows are only deleted after
the archive object is confirmed, and the reindex never touches the live index until the swap.
`catchup=False` and `max_active_runs=1`; backfill explicitly with
`airflow dags backfill -s 2026-10-01 -e 2026-10-07 analytics_daily`.

### Late-arriving analytics events

`extract_from_sqs` writes an event under its own event date, even when that day's run has
already finished, and logs a `sqs_late_events` warning (also returned as `late_partitions`).
Those days are **not** recomputed automatically. To fold late events into a past day, rerun it
manually; every task is idempotent, so a rerun overwrites that day's outputs:

```bash
airflow tasks clear -y analytics_daily -s 2026-10-11 -e 2026-10-11   # existing run
airflow dags backfill -s 2026-10-11 -e 2026-10-11 analytics_daily     # or a backfill run
```
Rerun `user_activity_daily` for later dates as well if their reports should reflect the change.

## Spark

`OTTERWORKS_SPARK_MODE=local` (default): `SparkSubmitOperator` runs the job with `local[*]` inside
the worker. `OTTERWORKS_SPARK_MODE=emr`: the DAG swaps in `EmrAddStepsOperator` + `EmrStepSensor`
and reads/writes S3 directly (set `emr_cluster_id` and `spark_jobs_s3_prefix` in the Variable).
Downstream tasks read the same `curated/analytics/ds=<ds>/aggregates` output in both modes.

## Run locally

```bash
# repo root
docker compose -f docker-compose.infra.yml up -d postgres localstack meilisearch
python etl/airflow/scripts/seed_local.py --ds 2026-10-12      # needs boto3
cp etl/airflow/.env.example etl/airflow/.env                    # fill in __SET_ME__
docker compose -f etl/airflow/docker-compose.yml up -d --build  # UI: http://localhost:8088
docker compose -f etl/airflow/docker-compose.yml exec airflow-scheduler \
  bash -c 'airflow dags unpause analytics_daily && airflow dags trigger analytics_daily -e 2026-10-12T02:00:00+00:00'
```

## Test

```bash
pip install -r etl/airflow/requirements-dev.txt \
  -c https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.11.txt
cd etl && pytest        # needs a JRE for the PySpark tests
```
CI: `.github/workflows/etl.yml` (runs only on `etl/**` changes).
