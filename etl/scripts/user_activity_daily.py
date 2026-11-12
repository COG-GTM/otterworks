#!/usr/bin/env python3
# user_activity_daily.py - Daily user activity report generation
# Originally Python 2.7, minimally ported to Python 3 in 2021
# Queries PostgreSQL aggregates, reads per-user S3 data, generates
# activity reports, stores to S3 for admin-service consumption
#
# Owner: Jake (data-team@otterworks.dev) -- Jake left mid-2020
# TODO ETL-098: Optimize S3 reads with range requests (2019-12-01)
# TODO ETL-160: Cache PostgreSQL connection across runs (deferred Q2 2020)
# TODO ETL-210: Add email notification for report generation (never done)

import configparser
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone

import boto3
import psycopg2


CONFIG_PATH = "/opt/etl/config.ini"
LOOKBACK_DAYS = 30
S3_REPORTS_PREFIX = "reports/user-activity"

SUMMARY_COLUMNS = [
    "report_date",
    "active_users",
    "active_documents",
    "active_files",
    "total_events",
    "documents_created",
    "documents_edited",
    "comments_added",
    "files_uploaded",
    "files_shared",
    "files_deleted",
    "bytes_uploaded",
]

SUMMARY_SQL = """
            SELECT
                report_date,
                active_users,
                active_documents,
                active_files,
                total_events,
                documents_created,
                documents_edited,
                comments_added,
                files_uploaded,
                files_shared,
                files_deleted,
                bytes_uploaded
            FROM analytics_daily_summary
            WHERE report_date BETWEEN %s::date - interval '%s days' AND %s::date
            ORDER BY report_date;
        """


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config(path=CONFIG_PATH):
    config = configparser.ConfigParser()
    config.read(path)
    return {
        "aws_access_key": config.get("aws", "access_key"),
        "aws_secret_key": config.get("aws", "secret_key"),
        "aws_region": config.get("aws", "region"),
        "db_host": config.get("database", "host"),
        "db_port": config.getint("database", "port"),
        "db_name": config.get("database", "database"),
        "db_user": config.get("database", "user"),
        "db_password": config.get("database", "password"),
        "data_lake_bucket": config.get("s3", "data_lake_bucket"),
    }


def _row_to_record(row):
    record = {}
    for i, col in enumerate(SUMMARY_COLUMNS):
        val = row[i]
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        record[col] = val
    return record


def fetch_daily_summaries(cfg, ds, lookback_days):
    print("[%s] Querying PostgreSQL for analytics aggregates (lookback: %d days)..." % (
        _now(), lookback_days
    ))

    conn = None
    cursor = None
    daily_summaries = []

    try:
        conn = psycopg2.connect(
            host=cfg["db_host"],
            port=cfg["db_port"],
            dbname=cfg["db_name"],
            user=cfg["db_user"],
            password=cfg["db_password"],
        )
        cursor = conn.cursor()
        cursor.execute(SUMMARY_SQL, (ds, lookback_days, ds))
        daily_summaries.extend(_row_to_record(row) for row in cursor.fetchall())

        print("[%s] Retrieved %d daily summary records" % (_now(), len(daily_summaries)))
    except Exception as e:
        print("[%s] ERROR: PostgreSQL query failed: %s" % (_now(), str(e)))
        sys.exit(1)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return daily_summaries


def _s3_client(cfg):
    return boto3.client(
        "s3",
        aws_access_key_id=cfg["aws_access_key"],
        aws_secret_access_key=cfg["aws_secret_key"],
        region_name=cfg["aws_region"],
    )


def _top_users_key(check_date):
    return "analytics/daily/year=%s/month=%s/day=%s/top_users.jsonl.gz" % (
        check_date.strftime("%Y"), check_date.strftime("%m"), check_date.strftime("%d")
    )


def _accumulate_user(user_totals, user_data):
    uid = user_data.get("user_id", "unknown")
    entry = user_totals.setdefault(uid, {
        "user_id": uid,
        "total_actions": 0,
        "active_days": 0,
        "actions_by_type": {},
    })
    entry["total_actions"] += user_data.get("total", 0)
    entry["active_days"] += 1

    actions_by_type = entry["actions_by_type"]
    for action_type, count in user_data.get("actions", {}).items():
        actions_by_type[action_type] = actions_by_type.get(action_type, 0) + count


def _accumulate_day(s3_client, bucket, key, user_totals):
    response = s3_client.get_object(Bucket=bucket, Key=key)
    decompressed = gzip.decompress(response["Body"].read()).decode("utf-8")
    for line in decompressed.strip().split("\n"):
        if line:
            _accumulate_user(user_totals, json.loads(line))


def aggregate_user_activity(s3_client, bucket, ds, lookback_days):
    print("[%s] Reading per-user activity data from S3 (lookback: %d days)..." % (
        _now(), lookback_days
    ))

    user_totals = {}
    execution_date = datetime.strptime(ds, "%Y-%m-%d")

    for day_offset in range(lookback_days):
        key = _top_users_key(execution_date - timedelta(days=day_offset))
        try:
            _accumulate_day(s3_client, bucket, key, user_totals)
        except:
            # S3 key might not exist for every day -- silently skip
            # TODO ETL-098: Log missing days for debugging
            pass

    user_list = sorted(user_totals.values(), key=lambda x: x["total_actions"], reverse=True)
    print("[%s] Aggregated activity for %d users over %d days" % (
        _now(), len(user_list), lookback_days
    ))
    return user_list


def build_report(ds, lookback_days, daily_summaries, user_list):
    total_events = sum(d.get("total_events", 0) for d in daily_summaries)
    total_users = max((d.get("active_users", 0) for d in daily_summaries), default=0)
    avg_daily_events = total_events / len(daily_summaries) if daily_summaries else 0

    return {
        "report_type": "user_activity",
        "report_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "lookback_days": lookback_days,
        "trends": {
            "total_events": total_events,
            "peak_active_users": total_users,
            "avg_daily_events": round(avg_daily_events, 2),
            "reporting_days": len(daily_summaries),
        },
        "daily_summaries": daily_summaries,
        "user_summaries": user_list[:500],
        "top_users": user_list[:20],
    }


def store_report(s3_client, bucket, ds, report):
    print("[%s] Storing reports to S3..." % _now())

    report_body = json.dumps(report, indent=2, default=str).encode("utf-8")

    # Store full report
    report_key = "%s/%s/activity_report.json" % (S3_REPORTS_PREFIX, ds)
    s3_client.put_object(Bucket=bucket, Key=report_key, Body=report_body)

    # Store latest pointer for admin-service
    latest_key = "%s/latest/activity_report.json" % S3_REPORTS_PREFIX
    s3_client.put_object(Bucket=bucket, Key=latest_key, Body=report_body)

    # Store per-user summaries as JSONL for individual user lookups
    user_summaries = report.get("user_summaries", [])
    if user_summaries:
        users_key = "%s/%s/user_summaries.jsonl" % (S3_REPORTS_PREFIX, ds)
        lines = [json.dumps(u, default=str) for u in user_summaries]
        s3_client.put_object(
            Bucket=bucket,
            Key=users_key,
            Body=("\n".join(lines) + "\n").encode("utf-8"),
        )

    print("[%s] Stored activity report: %d user summaries at s3://%s/%s" % (
        _now(), len(user_summaries), bucket, report_key
    ))


def main():
    print("[%s] user_activity_daily.py starting..." % _now())

    cfg = load_config()
    bucket = cfg["data_lake_bucket"]
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    daily_summaries = fetch_daily_summaries(cfg, ds, LOOKBACK_DAYS)
    user_list = aggregate_user_activity(_s3_client(cfg), bucket, ds, LOOKBACK_DAYS)
    report = build_report(ds, LOOKBACK_DAYS, daily_summaries, user_list)
    store_report(_s3_client(cfg), bucket, ds, report)

    print("[%s] user_activity_daily.py completed successfully" % _now())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[%s] FATAL: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(e)))
        sys.exit(1)
