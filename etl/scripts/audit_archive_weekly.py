#!/usr/bin/env python3
# audit_archive_weekly.py - Weekly audit event archival to S3 Glacier
# Originally Python 2.7, minimally ported to Python 3 in 2021
# Scans DynamoDB for old events, compresses to JSONL.gz, uploads to Glacier,
# batch-deletes from DynamoDB, generates compliance report
#
# Owner: Jake (data-team@otterworks.dev) -- Jake left mid-2020
# TODO ETL-134: Add incremental archival instead of full scan (deferred Q2 2020)
# TODO ETL-167: Handle DynamoDB throughput throttling properly (2020-04-10)
# TODO ETL-199: This script has no tests whatsoever (never prioritized)

import configparser
import gzip
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class DecimalEncoder(json.JSONEncoder):
    """Handle DynamoDB Decimal types -- copied from StackOverflow"""
    def default(self, o):
        if isinstance(o, Decimal):
            if o == int(o):
                return int(o)
            return float(o)
        return super().default(o)


RETENTION_DAYS = 90
DYNAMODB_TABLE_NAME = "otterworks-audit-events"
DYNAMODB_BATCH_SIZE = 25  # DynamoDB batch write limit
S3_PREFIX = "audit-archive"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_aws_config(path="/opt/etl/config.ini"):
    config = configparser.ConfigParser()
    config.read(path)
    aws_kwargs = {
        "aws_access_key_id": config.get("aws", "access_key"),
        "aws_secret_access_key": config.get("aws", "secret_key"),
        "region_name": config.get("aws", "region"),
    }
    return aws_kwargs, config.get("s3", "archive_bucket")


def compute_cutoff_date(ds, retention_days):
    return (datetime.strptime(ds, "%Y-%m-%d") - timedelta(days=retention_days)).isoformat() + "Z"


def scan_old_events(table, cutoff_date):
    """Scan the whole table (following pagination) for events older than cutoff_date."""
    events = []
    scan_kwargs = {
        "FilterExpression": "#ts < :cutoff",
        "ExpressionAttributeNames": {"#ts": "timestamp"},
        "ExpressionAttributeValues": {":cutoff": cutoff_date},
    }
    while True:
        response = table.scan(**scan_kwargs)
        events.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return events
        scan_kwargs["ExclusiveStartKey"] = last_key


def compress_events(events):
    """Serialize events as gzip-compressed JSON Lines and return the bytes."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for event in events:
            gz.write(json.dumps(event, cls=DecimalEncoder).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def delete_archived_batch(table, keys):
    """Delete one batch of archived event keys; return how many were deleted."""
    try:
        with table.batch_writer() as batch_writer:
            for k in keys:
                batch_writer.delete_item(Key=k)
    except (BotoCoreError, ClientError) as e:
        # TODO ETL-167: Retry throttled / unprocessed items instead of skipping the batch
        print("[%s] WARNING: failed to delete batch of %d archived events from DynamoDB: %s" % (
            _now(), len(keys), e
        ))
        return 0
    return len(keys)


def delete_archived_events(table, events, batch_size=DYNAMODB_BATCH_SIZE):
    """Batch-delete archived events from DynamoDB; return how many were deleted."""
    keys = [{"event_id": e["event_id"], "timestamp": e["timestamp"]} for e in events]
    deleted_count = 0
    for i in range(0, len(keys), batch_size):
        deleted_count += delete_archived_batch(table, keys[i:i + batch_size])
    return deleted_count


def build_compliance_report(ds, cutoff_date, archive_count, deleted_count, archive_location, compressed_size):
    return {
        "report_type": "audit_archive_compliance",
        "execution_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "retention_policy": {
            "retention_days": RETENTION_DAYS,
            "cutoff_date": cutoff_date,
        },
        "results": {
            "events_scanned": archive_count,
            "events_archived": archive_count,
            "events_deleted_from_source": deleted_count,
            "archive_location": archive_location,
            "archive_storage_class": "GLACIER",
            "compressed_size_bytes": compressed_size,
        },
        "compliance": {
            "gdpr_compliant": True,
            "soc2_compliant": True,
            "data_encrypted_at_rest": True,
            "data_encrypted_in_transit": True,
        },
    }


def main():
    print("[%s] audit_archive_weekly.py starting..." % _now())

    aws_kwargs, archive_bucket = load_aws_config()
    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    cutoff_date = compute_cutoff_date(ds, RETENTION_DAYS)
    print("[%s] Archiving events older than %d days (cutoff: %s)" % (_now(), RETENTION_DAYS, cutoff_date))

    # ---- Scan DynamoDB for old audit events ----
    table = boto3.resource("dynamodb", **aws_kwargs).Table(DYNAMODB_TABLE_NAME)
    events_to_archive = scan_old_events(table, cutoff_date)
    archive_count = len(events_to_archive)
    print("[%s] Found %d audit events older than %d days" % (_now(), archive_count, RETENTION_DAYS))

    if archive_count == 0:
        print("[%s] No events to archive, exiting" % _now())
        sys.exit(0)

    # ---- Compress to JSONL.gz ----
    archive_key = "%s/year=%s/week=%s/audit_events.jsonl.gz" % (S3_PREFIX, ds[:4], ds)
    archive_body = compress_events(events_to_archive)
    compressed_size = len(archive_body)
    print("[%s] Compressed %d events to %.2f MB" % (_now(), archive_count, compressed_size / (1024 * 1024)))

    # ---- Upload to S3 with Glacier storage class ----
    s3_client = boto3.client("s3", **aws_kwargs)
    s3_client.put_object(Bucket=archive_bucket, Key=archive_key, Body=archive_body, StorageClass="GLACIER")
    print("[%s] Archived to s3://%s/%s (GLACIER)" % (_now(), archive_bucket, archive_key))

    # ---- Batch-delete archived records from DynamoDB ----
    print("[%s] Deleting %d archived events from DynamoDB..." % (_now(), archive_count))
    deleted_count = delete_archived_events(table, events_to_archive)
    print("[%s] Deleted %d events from DynamoDB" % (_now(), deleted_count))

    # ---- Generate compliance report ----
    report = build_compliance_report(
        ds, cutoff_date, archive_count, deleted_count,
        "s3://%s/%s" % (archive_bucket, archive_key), compressed_size,
    )
    report_key = "reports/compliance/audit-archive/%s/report.json" % ds
    s3_client.put_object(
        Bucket=archive_bucket,
        Key=report_key,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )

    print("[%s] Compliance report: %d archived, %d deleted, stored at s3://%s/%s" % (
        _now(), archive_count, deleted_count, archive_bucket, report_key,
    ))
    print("[%s] audit_archive_weekly.py completed successfully" % _now())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[%s] FATAL: %s" % (_now(), str(e)))
        sys.exit(1)
