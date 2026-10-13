"""user_activity_daily: Postgres daily summaries + S3 top-users -> activity report."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from otterworks_etl import s3io, settings
from otterworks_etl.json_logging import log_event
from otterworks_etl.transforms import analytics as A
from otterworks_etl.transforms import user_activity as T

logger = logging.getLogger(__name__)

SUMMARY_COLUMNS = ("report_date",) + A.SUMMARY_COLUMNS
SUMMARY_SQL = (f"SELECT {', '.join(SUMMARY_COLUMNS)} FROM analytics_daily_summary "
               "WHERE report_date BETWEEN %s AND %s ORDER BY report_date")


def _s3():
    from airflow.providers.amazon.aws.hooks.s3 import S3Hook

    return S3Hook(aws_conn_id=settings.AWS_CONN_ID)


def _staging(cfg: dict, ds: str, name: str) -> str:
    return f"{cfg['staging_prefix']}/user-activity/ds={ds}/{name}.json"


def extract_daily_summaries(ds: str, cfg: dict) -> int:
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    lookback = int(cfg["user_activity_lookback_days"])
    start = (date.fromisoformat(ds) - timedelta(days=lookback - 1)).isoformat()
    rows = PostgresHook(postgres_conn_id=settings.POSTGRES_CONN_ID).get_records(
        SUMMARY_SQL, parameters=(start, ds))
    summaries = [dict(zip(SUMMARY_COLUMNS, r)) for r in rows]
    s3io.put_json(_s3(), cfg["data_lake_bucket"], _staging(cfg, ds, "daily_summaries"), summaries)
    log_event(logger, "daily_summaries_extracted", rows=len(summaries), start=start, end=ds)
    return len(summaries)


def extract_top_users(ds: str, cfg: dict) -> dict:
    s3, bucket = _s3(), cfg["data_lake_bucket"]
    daily, missing = [], []
    for day in T.window_dates(ds, int(cfg["user_activity_lookback_days"])):
        key = f"{A.partition_key(cfg['analytics_prefix'], day)}/top_users.jsonl.gz"
        data = s3io.get_bytes(s3, bucket, key)
        if data is None:
            missing.append(day)
            continue
        daily.append(list(s3io.iter_jsonl(data)))
    if missing:
        log_event(logger, "top_users_days_missing", logging.WARNING, days=len(missing),
                  newest_missing=missing[0])
    s3io.put_json(s3, bucket, _staging(cfg, ds, "top_users_daily"), daily)
    return {"days_found": len(daily), "missing_days": missing}


def build_and_load_report(ds: str, cfg: dict, missing_days: list[str], generated_at: str) -> str:
    s3, bucket, prefix = _s3(), cfg["data_lake_bucket"], cfg["user_activity_reports_prefix"]
    summaries = s3io.get_json(s3, bucket, _staging(cfg, ds, "daily_summaries")) or []
    users = T.merge_top_users(s3io.get_json(s3, bucket, _staging(cfg, ds, "top_users_daily")) or [])
    report = T.build_report(ds, generated_at, int(cfg["user_activity_lookback_days"]),
                            summaries, users, missing_days)
    report_key = f"{prefix}/{ds}/activity_report.json"
    s3io.put_json(s3, bucket, report_key, report)
    if users:
        s3io.put_bytes(s3, bucket, f"{prefix}/{ds}/user_summaries.jsonl",
                       "".join(s3io.dumps(u) + "\n" for u in users).encode())
    latest_key = f"{prefix}/latest/activity_report.json"
    existing = s3io.get_json(s3, bucket, latest_key) or {}
    if T.should_replace_latest(existing.get("report_date"), ds):
        s3io.put_json(s3, bucket, latest_key, report)
    else:
        log_event(logger, "latest_pointer_kept", latest=existing.get("report_date"), backfill=ds)
    log_event(logger, "user_activity_report_written", key=report_key, users=len(users),
              **report["trends"])
    return report_key
