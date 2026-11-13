#!/usr/bin/env python3
# analytics_daily.py - Daily analytics aggregation pipeline
# Originally Python 2.7, minimally ported to Python 3 in 2021
# Pulls events from SQS + DynamoDB, aggregates, loads to S3 and PostgreSQL
#
# Owner: Jake (data-team@otterworks.dev) -- Jake left mid-2020
# TODO ETL-078: Refactor this into proper modules (deferred Q4 2019)
# TODO ETL-142: Move credentials to secrets manager (deferred Q3 2020)
# TODO ETL-201: Add unit tests (never prioritized)

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
from botocore.exceptions import BotoCoreError, ClientError

# TODO ETL-089: Make queue URL configurable per environment (2019-11-15)
SQS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/otterworks-analytics"
SQS_MAX_MESSAGES = 10000  # hardcoded limit
SQS_BATCH_SIZE = 10
SQS_MAX_CONSECUTIVE_ERRORS = 3
DYNAMODB_TABLE_NAME = "otterworks-analytics-events"
USER_ID_COLUMNS = ["ownerId", "editedBy", "authorId", "deletedBy", "userId"]

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


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config(path="/opt/etl/config.ini"):
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


def aws_kwargs(cfg):
    return {
        "aws_access_key_id": cfg["aws_access_key"],
        "aws_secret_access_key": cfg["aws_secret_key"],
        "region_name": cfg["aws_region"],
    }


# ---- Extract from SQS ----

def parse_sqs_messages(messages):
    events = []
    entries_to_delete = []
    for msg in messages:
        try:
            event = json.loads(msg["Body"])
            events.append(event)
            entries_to_delete.append({"Id": msg["MessageId"], "ReceiptHandle": msg["ReceiptHandle"]})
        except (KeyError, TypeError, ValueError):
            # TODO ETL-103: Add dead-letter queue for malformed messages (2020-01-08)
            continue
    return events, entries_to_delete


def receive_sqs_batch(sqs_client):
    return sqs_client.receive_message(
        QueueUrl=SQS_QUEUE_URL,
        MaxNumberOfMessages=SQS_BATCH_SIZE,
        WaitTimeSeconds=5,
        AttributeNames=["All"],
        MessageAttributeNames=["All"],
    )


def extract_sqs_events(sqs_client):
    all_sqs_events = []
    messages_processed = 0
    consecutive_errors = 0

    print("[%s] Polling SQS queue: %s" % (now_str(), SQS_QUEUE_URL))

    while messages_processed < SQS_MAX_MESSAGES:
        try:
            response = receive_sqs_batch(sqs_client)
            consecutive_errors = 0
        except (BotoCoreError, ClientError):
            # TODO ETL-103: Add dead-letter queue for failed SQS calls (2020-01-08)
            consecutive_errors += 1
            print("[%s] WARNING: SQS receive failed (%d consecutive)" % (now_str(), consecutive_errors))
            if consecutive_errors >= SQS_MAX_CONSECUTIVE_ERRORS:
                print("[%s] ERROR: Too many SQS failures, giving up" % now_str())
                break
            continue

        messages = response.get("Messages", [])
        if not messages:
            print("[%s] No more messages after %d processed" % (now_str(), messages_processed))
            break

        events, entries_to_delete = parse_sqs_messages(messages)
        all_sqs_events.extend(events)
        if entries_to_delete:
            sqs_client.delete_message_batch(QueueUrl=SQS_QUEUE_URL, Entries=entries_to_delete)

        messages_processed += len(messages)

    print("[%s] Extracted %d events from SQS" % (now_str(), len(all_sqs_events)))
    return all_sqs_events


# ---- Extract from DynamoDB ----

def normalize_decimals(item):
    # convert Decimals to native types for json serialization later
    for k, v in item.items():
        if isinstance(v, Decimal):
            item[k] = int(v) if v == int(v) else float(v)
    return item


def extract_dynamo_events(table, ds):
    all_dynamo_events = []
    scan_kwargs = {
        "FilterExpression": "begins_with(event_date, :ds)",
        "ExpressionAttributeValues": {":ds": ds},
    }

    while True:
        response = table.scan(**scan_kwargs)
        all_dynamo_events.extend(normalize_decimals(item) for item in response.get("Items", []))

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    print("[%s] Extracted %d events from DynamoDB for %s" % (now_str(), len(all_dynamo_events), ds))
    return all_dynamo_events


# ---- Transform ----

def parse_hour(ts):
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return "00"
        return "%02d" % dt.hour
    return "00"


def build_dataframe(all_events):
    # TODO ETL-155: This pandas approach is slow for large datasets, consider PySpark (2020-03-22)
    df = pd.DataFrame(all_events)

    # Normalize event type field name
    if "event_type" in df.columns and "eventType" not in df.columns:
        df["eventType"] = df["event_type"]
    if "eventType" not in df.columns:
        df["eventType"] = "unknown"

    # Resolve user ID from whichever field is populated
    df["resolved_user_id"] = "unknown"
    for col in USER_ID_COLUMNS:
        if col in df.columns:
            mask = (df["resolved_user_id"] == "unknown") & df[col].notna() & (df[col] != "")
            df.loc[mask, "resolved_user_id"] = df.loc[mask, col]

    # Parse timestamps for hourly bucketing
    df["hour"] = "00"
    if "timestamp" in df.columns:
        df["hour"] = df["timestamp"].apply(parse_hour)

    return df


# ---- Aggregate ----

def count_nested(df, outer_key, outer_col):
    counts = {}
    for _, row in df.iterrows():
        outer = row.get(outer_col, outer_key)
        etype = row.get("eventType", "unknown")
        bucket = counts.setdefault(outer, {})
        bucket[etype] = bucket.get(etype, 0) + 1
    return counts


def top_user_summaries(df, limit=100):
    user_action_counts = count_nested(df, "unknown", "resolved_user_id")
    user_summaries = [
        {"user_id": uid, "actions": actions, "total": sum(actions.values())}
        for uid, actions in user_action_counts.items()
    ]
    user_summaries.sort(key=lambda x: x["total"], reverse=True)
    return user_summaries[:limit]


def events_of_type(df, event_type):
    return df[df["eventType"] == event_type]


def unique_ids(df, events, column):
    if column in df.columns:
        return set(events[column].dropna().unique())
    return set()


def document_metrics(df):
    doc_created = events_of_type(df, "document_created")
    doc_edited = events_of_type(df, "document_edited")
    active_documents = unique_ids(df, doc_created, "documentId") | unique_ids(df, doc_edited, "documentId")
    metrics = {
        "created": len(doc_created),
        "edited": len(doc_edited),
        "comments": len(events_of_type(df, "comment_added")),
    }
    return metrics, active_documents


def file_metrics(df):
    uploaded = events_of_type(df, "file_uploaded")
    shared = events_of_type(df, "file_shared")
    deleted = events_of_type(df, "file_deleted")

    bytes_uploaded = 0
    if "sizeBytes" in df.columns:
        bytes_uploaded = int(uploaded["sizeBytes"].fillna(0).sum())

    active_files = set()
    for events in (uploaded, shared, deleted):
        active_files |= unique_ids(df, events, "fileId")

    metrics = {
        "uploaded": len(uploaded),
        "shared": len(shared),
        "deleted": len(deleted),
        "bytes_uploaded": bytes_uploaded,
    }
    return metrics, active_files


def hourly_breakdown(df):
    return dict(sorted(count_nested(df, "00", "hour").items()))


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

    print("[%s] Aggregation complete: %d events, %d active users, %d documents, %d files" % (
        now_str(),
        total_events,
        len(active_users),
        len(active_documents),
        len(active_files),
    ))

    return {
        "summary": summary,
        "document_metrics": doc_metrics,
        "file_metrics": f_metrics,
        "hourly_breakdown": hourly_breakdown(df),
        "user_summaries": top_user_summaries(df),
    }


# ---- Load ----

def load_to_s3(s3_client, bucket, analytics_prefix, ds, result):
    partition_key = "%s/year=%s/month=%s/day=%s" % (analytics_prefix, ds[:4], ds[5:7], ds[8:10])

    summary_key = "%s/summary.json.gz" % partition_key
    summary_bytes = gzip.compress(json.dumps(result["summary"], indent=2).encode("utf-8"))
    s3_client.put_object(Bucket=bucket, Key=summary_key, Body=summary_bytes)
    print("[%s] Uploaded summary to s3://%s/%s" % (now_str(), bucket, summary_key))

    hourly_key = "%s/hourly_breakdown.json.gz" % partition_key
    hourly_bytes = gzip.compress(json.dumps(result["hourly_breakdown"], indent=2).encode("utf-8"))
    s3_client.put_object(Bucket=bucket, Key=hourly_key, Body=hourly_bytes)

    users_key = "%s/top_users.jsonl.gz" % partition_key
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for user in result["user_summaries"]:
            gz.write(json.dumps(user).encode("utf-8"))
            gz.write(b"\n")
    s3_client.put_object(Bucket=bucket, Key=users_key, Body=buf.getvalue())

    print("[%s] Loaded analytics data to s3://%s/%s" % (now_str(), bucket, partition_key))


def upsert_postgres(cfg, ds, summary):
    print("[%s] Connecting to PostgreSQL at %s:%d/%s" % (now_str(), cfg["db_host"], cfg["db_port"], cfg["db_name"]))

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
        cursor.execute(UPSERT_SQL, (ds,) + tuple(summary[col] for col in SUMMARY_COLUMNS))
        conn.commit()
        print("[%s] Updated PostgreSQL daily aggregates for %s" % (now_str(), ds))
    except psycopg2.Error as e:
        print("[%s] ERROR: PostgreSQL update failed: %s" % (now_str(), str(e)))
        if conn:
            conn.rollback()
        # don't exit -- still try to generate report
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def build_report(ds, result):
    hourly = result["hourly_breakdown"]
    peak_hour = None
    if hourly:
        peak = max(hourly.items(), key=lambda x: sum(x[1].values()))
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


def write_report(s3_client, bucket, ds, report):
    report_key = "reports/analytics/daily/%s/report.json" % ds
    s3_client.put_object(
        Bucket=bucket,
        Key=report_key,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )
    print("[%s] Generated daily analytics report: %d events, %d active users" % (
        now_str(),
        report["summary"]["total_events"],
        report["summary"]["active_users"],
    ))


def main():
    print("[%s] analytics_daily.py starting..." % now_str())

    cfg = load_config()
    creds = aws_kwargs(cfg)

    # today's date for partitioning
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    print("[%s] Processing analytics for date: %s" % (now_str(), ds))

    all_sqs_events = extract_sqs_events(boto3.client("sqs", **creds))
    table = boto3.resource("dynamodb", **creds).Table(DYNAMODB_TABLE_NAME)
    all_dynamo_events = extract_dynamo_events(table, ds)

    all_events = all_sqs_events + all_dynamo_events
    print("[%s] Total events to process: %d" % (now_str(), len(all_events)))

    if len(all_events) == 0:
        print("[%s] WARNING: No events found, exiting" % now_str())
        sys.exit(0)

    result = aggregate(build_dataframe(all_events), len(all_events))

    bucket = cfg["data_lake_bucket"]
    load_to_s3(boto3.client("s3", **creds), bucket, cfg["analytics_prefix"], ds, result)
    upsert_postgres(cfg, ds, result["summary"])
    write_report(boto3.client("s3", **creds), bucket, ds, build_report(ds, result))

    print("[%s] analytics_daily.py completed successfully" % now_str())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[%s] FATAL: %s" % (now_str(), str(e)))
        sys.exit(1)
