#!/usr/bin/env python3
# storage_cleanup_daily.py - Daily orphaned S3 object cleanup
# Originally Python 2.7, minimally ported to Python 3 in 2021
# Lists S3 objects, compares with DynamoDB metadata, quarantines orphans,
# generates storage savings report
#
# Owner: Jake (data-team@otterworks.dev) -- Jake left mid-2020
# TODO ETL-091: Add S3 lifecycle rules instead of manual cleanup (2019-11-20)
# TODO ETL-156: Parallelize S3 listing for large buckets (deferred Q1 2020)
# TODO ETL-203: Add dry-run mode for testing (never implemented)

import configparser
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3

CONFIG_PATH = os.environ.get("ETL_CONFIG_PATH", "/opt/etl/config.ini")

# file-service writes the S3 object before its DynamoDB metadata, so recently
# written objects may be in-flight uploads rather than orphans.
DEFAULT_ORPHAN_GRACE_HOURS = 24.0


def get_orphan_grace_hours(config):
    value = os.environ.get("ETL_ORPHAN_GRACE_HOURS")
    if value is None:
        value = config.get(
            "storage_cleanup", "orphan_grace_hours", fallback=str(DEFAULT_ORPHAN_GRACE_HOURS)
        )
    hours = float(value)
    if hours < 0:
        raise ValueError("orphan_grace_hours must be >= 0, got %s" % value)
    return hours


def select_orphans(all_objects, referenced_keys, now, grace_hours):
    """Return (orphans, skipped_recent): unreferenced objects older than the grace period,
    and unreferenced objects still inside it."""
    cutoff = now - timedelta(hours=grace_hours)
    orphans = []
    skipped_recent = []
    for obj in all_objects:
        if obj["key"] in referenced_keys:
            continue
        if obj["last_modified"] > cutoff:
            skipped_recent.append(obj)
        else:
            orphans.append(obj)
    return orphans, skipped_recent


def main():
    print("[%s] storage_cleanup_daily.py starting..." % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ---- Load config ----
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)

    aws_access_key = config.get("aws", "access_key")
    aws_secret_key = config.get("aws", "secret_key")
    aws_region = config.get("aws", "region")

    file_storage_bucket = config.get("s3", "file_storage_bucket")
    quarantine_bucket = config.get("s3", "quarantine_bucket")
    data_lake_bucket = config.get("s3", "data_lake_bucket")

    files_prefix = "files/"
    quarantine_prefix = "quarantined"
    dynamodb_table_name = "otterworks-file-metadata"
    grace_hours = get_orphan_grace_hours(config)

    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # ---- List all S3 objects ----
    print("[%s] Listing objects in s3://%s/%s" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), file_storage_bucket, files_prefix
    ))

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
    )

    all_objects = []
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=file_storage_bucket, Prefix=files_prefix):
        for obj in page.get("Contents", []):
            all_objects.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"],
            })

    total_objects = len(all_objects)
    total_size_bytes = sum(o["size"] for o in all_objects)

    print("[%s] Found %d objects in S3 (%d bytes total)" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), total_objects, total_size_bytes
    ))

    # ---- List metadata references from DynamoDB ----
    print("[%s] Scanning DynamoDB table %s for metadata references..." % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), dynamodb_table_name
    ))

    dynamodb = boto3.resource(
        "dynamodb",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
    )
    table = dynamodb.Table(dynamodb_table_name)

    referenced_keys = set()
    scan_kwargs = {
        "ProjectionExpression": "s3_key",
        "ConsistentRead": True,
    }

    while True:
        response = table.scan(**scan_kwargs)
        for item in response.get("Items", []):
            s3_key = item.get("s3_key", "")
            if s3_key:
                referenced_keys.add(s3_key)

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    print("[%s] Found %d S3 keys referenced in metadata" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(referenced_keys)
    ))

    # ---- Find orphaned objects ----
    orphaned, skipped_recent = select_orphans(
        all_objects, referenced_keys, datetime.now(tz=timezone.utc), grace_hours
    )
    orphaned_bytes = sum(o["size"] for o in orphaned)
    orphaned_count = len(orphaned)

    print("[%s] Skipped %d unreferenced objects modified within the last %g hours" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(skipped_recent), grace_hours
    ))

    print("[%s] Found %d orphaned objects (%.2f MB)" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        orphaned_count,
        orphaned_bytes / (1024 * 1024),
    ))

    if orphaned_count == 0:
        print("[%s] No orphaned objects to quarantine" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        # Still generate report even with 0 orphans
    else:
        # ---- Move orphaned objects to quarantine ----
        print("[%s] Moving %d orphaned objects to quarantine..." % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), orphaned_count
        ))

    moved_count = 0
    moved_bytes = 0
    failed_count = 0

    for obj in orphaned:
        source_key = obj["key"]
        dest_key = "%s/%s/%s" % (quarantine_prefix, ds, source_key)

        try:
            s3_client.copy_object(
                Bucket=quarantine_bucket,
                Key=dest_key,
                CopySource={"Bucket": file_storage_bucket, "Key": source_key},
                MetadataDirective="COPY",
            )
            s3_client.delete_object(Bucket=file_storage_bucket, Key=source_key)
            moved_count += 1
            moved_bytes += obj["size"]
        except Exception as e:
            print("[%s] WARNING: Failed to quarantine %s: %s" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source_key, str(e)
            ))
            failed_count += 1

    if orphaned_count > 0:
        print("[%s] Quarantined %d objects (%d failed) to s3://%s/%s/%s/" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            moved_count, failed_count,
            quarantine_bucket, quarantine_prefix, ds,
        ))

    # ---- Generate storage cleanup report ----
    orphaned_gb = orphaned_bytes / (1024 ** 3)
    savings_gb = moved_bytes / (1024 ** 3)
    estimated_monthly_savings = round(savings_gb * 0.023, 4)

    report = {
        "report_type": "storage_cleanup",
        "report_date": ds,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "inventory": {
            "total_objects": total_objects,
            "total_size_bytes": total_size_bytes,
            "total_size_gb": round(total_size_bytes / (1024 ** 3), 4),
        },
        "orphans": {
            "orphaned_objects": orphaned_count,
            "orphaned_bytes": orphaned_bytes,
            "orphaned_size_gb": round(orphaned_gb, 4),
            "orphan_percentage": round(
                (orphaned_count / total_objects * 100) if total_objects else 0, 2
            ),
            "grace_period_hours": grace_hours,
            "skipped_recent_objects": len(skipped_recent),
        },
        "cleanup": {
            "objects_quarantined": moved_count,
            "bytes_quarantined": moved_bytes,
            "objects_failed": failed_count,
            "quarantine_bucket": quarantine_bucket,
        },
        "savings": {
            "storage_freed_gb": round(savings_gb, 4),
            "estimated_monthly_savings_usd": estimated_monthly_savings,
        },
    }

    report_key = "reports/storage-cleanup/%s/report.json" % ds
    s3_client_report = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
    )
    s3_client_report.put_object(
        Bucket=data_lake_bucket,
        Key=report_key,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )

    print("[%s] Storage cleanup report: %d orphans quarantined, %.4f GB freed, ~$%.4f/month saved" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        moved_count, savings_gb, estimated_monthly_savings,
    ))
    if failed_count > 0:
        print("[%s] ERROR: storage_cleanup_daily.py completed with %d failed quarantines" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), failed_count
        ))
        return 1

    print("[%s] storage_cleanup_daily.py completed successfully" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as e:
        print("[%s] FATAL: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(e)))
        sys.exit(1)
    sys.exit(exit_code)
