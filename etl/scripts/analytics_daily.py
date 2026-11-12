#!/usr/bin/env python3
# analytics_daily.py - Daily analytics aggregation pipeline
# Originally Python 2.7, minimally ported to Python 3 in 2021
# Pulls events from SQS + DynamoDB, aggregates, loads to S3 and PostgreSQL
#
# Owner: Jake (data-team@otterworks.dev) -- Jake left mid-2020
# TODO ETL-142: Move credentials to secrets manager (deferred Q3 2020)

import configparser
import gzip
import io
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import pandas as pd
import psycopg2

CONFIG_PATH = "/opt/etl/config.ini"

# TODO ETL-089: Make queue URL configurable per environment (2019-11-15)
SQS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/otterworks-analytics"
SQS_MAX_MESSAGES = 10000
SQS_BATCH_SIZE = 10
SQS_MAX_CONSECUTIVE_ERRORS = 3

DYNAMODB_TABLE_NAME = "otterworks-analytics-events"

USER_ID_FIELDS = ["ownerId", "editedBy", "authorId", "deletedBy", "userId"]
TOP_USERS_LIMIT = 100

UPSERT_SQL = """
    INSERT INTO analytics_daily_summary (
        report_date, active_users, active_documents, active_files,
        total_events, documents_created, documents_edited,
        comments_added, files_uploaded, files_shared,
        files_deleted, bytes_uploaded, updated_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
    )
    ON CONFLICT (report_date) DO UPDATE SET
        active_users = EXCLUDED.active_users,
        active_documents = EXCLUDED.active_documents,
        active_files = EXCLUDED.active_files,
        total_events = EXCLUDED.total_events,
        documents_created = EXCLUDED.documents_created,
        documents_edited = EXCLUDED.documents_edited,
        comments_added = EXCLUDED.comments_added,
        files_uploaded = EXCLUDED.files_uploaded,
        files_shared = EXCLUDED.files_shared,
        files_deleted = EXCLUDED.files_deleted,
        bytes_uploaded = EXCLUDED.bytes_uploaded,
        updated_at = NOW();
"""

SUMMARY_COLUMNS = [
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


def log(message):
    print("[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))


# ---- Config ----

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
        "analytics_prefix": config.get("s3", "analytics_prefix"),
    }


def _aws_kwargs(cfg):
    return {
        "aws_access_key_id": cfg["aws_access_key"],
        "aws_secret_access_key": cfg["aws_secret_key"],
        "region_name": cfg["aws_region"],
    }


# ---- Extract ----

def _parse_sqs_messages(messages):
    events = []
    entries_to_delete = []
    for msg in messages:
        try:
            event = json.loads(msg["Body"])
            events.append(event)
            entries_to_delete.append({"Id": msg["MessageId"], "ReceiptHandle": msg["ReceiptHandle"]})
        except Exception:
            # TODO ETL-103: Add dead-letter queue for malformed messages (2020-01-08)
            pass
    return events, entries_to_delete


def _receive_sqs_batch(sqs_client, queue_url):
    return sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=SQS_BATCH_SIZE,
        WaitTimeSeconds=5,
        AttributeNames=["All"],
        MessageAttributeNames=["All"],
    )


def extract_sqs_events(sqs_client, queue_url=SQS_QUEUE_URL, max_messages=SQS_MAX_MESSAGES):
    all_events = []
    messages_processed = 0
    consecutive_errors = 0

    log("Polling SQS queue: %s" % queue_url)

    while messages_processed < max_messages:
        try:
            response = _receive_sqs_batch(sqs_client, queue_url)
        except Exception:
            # TODO ETL-103: Add dead-letter queue for failed SQS calls (2020-01-08)
            consecutive_errors += 1
            log("WARNING: SQS receive failed (%d consecutive)" % consecutive_errors)
            if consecutive_errors >= SQS_MAX_CONSECUTIVE_ERRORS:
                log("ERROR: Too many SQS failures, giving up")
                break
            continue
        consecutive_errors = 0

        messages = response.get("Messages", [])
        if not messages:
            log("No more messages after %d processed" % messages_processed)
            break

        events, entries_to_delete = _parse_sqs_messages(messages)
        all_events.extend(events)
        if entries_to_delete:
            sqs_client.delete_message_batch(QueueUrl=queue_url, Entries=entries_to_delete)

        messages_processed += len(messages)

    log("Extracted %d events from SQS" % len(all_events))
    return all_events


def _decimal_to_native(value):
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    return value


def extract_dynamo_events(table, ds):
    all_events = []
    scan_kwargs = {
        "FilterExpression": "begins_with(event_date, :ds)",
        "ExpressionAttributeValues": {":ds": ds},
    }

    while True:
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        # convert Decimals to native types for json serialization later
        for item in items:
            for k, v in item.items():
                item[k] = _decimal_to_native(v)
        all_events.extend(items)

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    log("Extracted %d events from DynamoDB for %s" % (len(all_events), ds))
    return all_events


# ---- Transform ----

def parse_hour(ts):
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return "%02d" % dt.hour
    except Exception:
        pass
    return "00"


def _resolve_user_ids(df):
    df["resolved_user_id"] = "unknown"
    for col in USER_ID_FIELDS:
        if col in df.columns:
            mask = (df["resolved_user_id"] == "unknown") & df[col].notna() & (df[col] != "")
            df.loc[mask, "resolved_user_id"] = df.loc[mask, col]


def build_events_frame(events):
    # TODO ETL-155: This pandas approach is slow for large datasets, consider PySpark (2020-03-22)
    df = pd.DataFrame(events)

    # Normalize event type field name
    if "event_type" in df.columns and "eventType" not in df.columns:
        df["eventType"] = df["event_type"]
    if "eventType" not in df.columns:
        df["eventType"] = "unknown"

    _resolve_user_ids(df)

    # Parse timestamps for hourly bucketing
    df["hour"] = "00"
    if "timestamp" in df.columns:
        df["hour"] = df["timestamp"].apply(parse_hour)
    return df


def count_event_types_by(df, key_col):
    counts = {}
    for _, row in df.iterrows():
        per_key = counts.setdefault(row[key_col], {})
        etype = row["eventType"]
        per_key[etype] = per_key.get(etype, 0) + 1
    return counts


def top_users(df, limit=TOP_USERS_LIMIT):
    user_summaries = [
        {"user_id": uid, "actions": actions, "total": sum(actions.values())}
        for uid, actions in count_event_types_by(df, "resolved_user_id").items()
    ]
    user_summaries.sort(key=lambda x: x["total"], reverse=True)
    return user_summaries[:limit]


def _events_of_type(df, event_type):
    return df[df["eventType"] == event_type]


def _collect_ids(rows, id_col, target):
    if id_col in rows.columns:
        target.update(rows[id_col].dropna().unique())


def document_metrics(df):
    active_documents = set()
    created = _events_of_type(df, "document_created")
    edited = _events_of_type(df, "document_edited")
    _collect_ids(created, "documentId", active_documents)
    _collect_ids(edited, "documentId", active_documents)
    metrics = {
        "created": len(created),
        "edited": len(edited),
        "comments": len(_events_of_type(df, "comment_added")),
    }
    return metrics, active_documents


def file_metrics(df):
    active_files = set()
    uploaded = _events_of_type(df, "file_uploaded")
    shared = _events_of_type(df, "file_shared")
    deleted = _events_of_type(df, "file_deleted")
    for rows in (uploaded, shared, deleted):
        _collect_ids(rows, "fileId", active_files)

    bytes_uploaded = 0
    if "sizeBytes" in uploaded.columns:
        bytes_uploaded = int(uploaded["sizeBytes"].fillna(0).sum())

    metrics = {
        "uploaded": len(uploaded),
        "shared": len(shared),
        "deleted": len(deleted),
        "bytes_uploaded": bytes_uploaded,
    }
    return metrics, active_files


def aggregate(df, total_events):
    active_users = set(df["resolved_user_id"].unique()) - {"unknown"}
    doc_metrics, active_documents = document_metrics(df)
    f_metrics, active_files = file_metrics(df)
    summary = {
        "active_users": len(active_users),
        "active_documents": len(active_documents),
        "active_files": len(active_files),
        "total_events": total_events,
        "documents_created": doc_metrics["created"],
        "documents_edited": doc_metrics["edited"],
        "comments_added": doc_metrics["comments"],
        "files_uploaded": f_metrics["uploaded"],
        "files_shared": f_metrics["shared"],
        "files_deleted": f_metrics["deleted"],
        "bytes_uploaded": f_metrics["bytes_uploaded"],
    }
    return {
        "summary": summary,
        "user_summaries": top_users(df),
        "hourly_breakdown": dict(sorted(count_event_types_by(df, "hour").items())),
        "document_metrics": doc_metrics,
        "file_metrics": f_metrics,
    }


# ---- Load ----

def _gzip_jsonl(records):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for record in records:
            gz.write(json.dumps(record).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def load_to_data_lake(s3_client, bucket, analytics_prefix, ds, result):
    partition_key = "%s/year=%s/month=%s/day=%s" % (analytics_prefix, ds[:4], ds[5:7], ds[8:10])

    summary_key = "%s/summary.json.gz" % partition_key
    s3_client.put_object(
        Bucket=bucket,
        Key=summary_key,
        Body=gzip.compress(json.dumps(result["summary"], indent=2).encode("utf-8")),
    )
    log("Uploaded summary to s3://%s/%s" % (bucket, summary_key))

    s3_client.put_object(
        Bucket=bucket,
        Key="%s/hourly_breakdown.json.gz" % partition_key,
        Body=gzip.compress(json.dumps(result["hourly_breakdown"], indent=2).encode("utf-8")),
    )

    s3_client.put_object(
        Bucket=bucket,
        Key="%s/top_users.jsonl.gz" % partition_key,
        Body=_gzip_jsonl(result["user_summaries"]),
    )

    log("Loaded analytics data to s3://%s/%s" % (bucket, partition_key))


def upsert_daily_summary(cfg, ds, summary):
    log("Connecting to PostgreSQL at %s:%d/%s" % (cfg["db_host"], cfg["db_port"], cfg["db_name"]))

    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            host=cfg["db_host"],
            port=cfg["db_port"],
            dbname=cfg["db_name"],
            user=cfg["db_user"],
            password=cfg["db_password"],
        )
        cursor = conn.cursor()
        cursor.execute(UPSERT_SQL, (ds, *(summary[col] for col in SUMMARY_COLUMNS)))
        conn.commit()
        log("Updated PostgreSQL daily aggregates for %s" % ds)
    except Exception as e:
        log("ERROR: PostgreSQL update failed: %s" % str(e))
        if conn:
            conn.rollback()
        # don't exit -- still try to generate report
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def build_report(ds, result):
    hourly_breakdown = result["hourly_breakdown"]
    peak_hour = None
    if hourly_breakdown:
        peak = max(hourly_breakdown.items(), key=lambda x: sum(x[1].values()))
        peak_hour = {"hour": peak[0], "event_count": sum(peak[1].values())}

    return {
        "report_type": "daily_analytics",
        "report_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": result["summary"],
        "highlights": {
            "peak_hour": peak_hour,
            "most_active_users": [u["user_id"] for u in result["user_summaries"][:5]],
        },
        "document_metrics": result["document_metrics"],
        "file_metrics": result["file_metrics"],
    }


def publish_report(s3_client, bucket, ds, report):
    s3_client.put_object(
        Bucket=bucket,
        Key="reports/analytics/daily/%s/report.json" % ds,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )


# ---- Pipeline ----

def main(config_path=CONFIG_PATH):
    log("analytics_daily.py starting...")

    cfg = load_config(config_path)
    aws_kwargs = _aws_kwargs(cfg)
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    log("Processing analytics for date: %s" % ds)

    sqs_events = extract_sqs_events(boto3.client("sqs", **aws_kwargs))
    table = boto3.resource("dynamodb", **aws_kwargs).Table(DYNAMODB_TABLE_NAME)
    all_events = sqs_events + extract_dynamo_events(table, ds)
    log("Total events to process: %d" % len(all_events))

    if not all_events:
        log("WARNING: No events found, exiting")
        sys.exit(0)

    result = aggregate(build_events_frame(all_events), len(all_events))
    summary = result["summary"]
    log("Aggregation complete: %d events, %d active users, %d documents, %d files" % (
        summary["total_events"],
        summary["active_users"],
        summary["active_documents"],
        summary["active_files"],
    ))

    s3_client = boto3.client("s3", **aws_kwargs)
    load_to_data_lake(s3_client, cfg["data_lake_bucket"], cfg["analytics_prefix"], ds, result)
    upsert_daily_summary(cfg, ds, summary)
    publish_report(s3_client, cfg["data_lake_bucket"], ds, build_report(ds, result))

    log("Generated daily analytics report: %d events, %d active users" % (
        summary["total_events"],
        summary["active_users"],
    ))
    log("analytics_daily.py completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL: %s" % str(e))
        sys.exit(1)
