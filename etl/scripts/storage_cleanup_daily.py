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
import sys
from datetime import datetime, timezone

import boto3

FILES_PREFIX = "files/"
QUARANTINE_PREFIX = "quarantined"
DYNAMODB_TABLE_NAME = "otterworks-file-metadata"
S3_PRICE_PER_GB_MONTH = 0.023


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _aws_kwargs(config):
    return {
        "aws_access_key_id": config.get("aws", "access_key"),
        "aws_secret_access_key": config.get("aws", "secret_key"),
        "region_name": config.get("aws", "region"),
    }


def list_s3_objects(s3_client, bucket, prefix):
    all_objects = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            all_objects.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            })
    return all_objects


def scan_referenced_keys(table):
    referenced_keys = set()
    scan_kwargs = {
        "ProjectionExpression": "s3_key",
    }
    while True:
        response = table.scan(**scan_kwargs)
        referenced_keys.update(
            item.get("s3_key", "") for item in response.get("Items", []) if item.get("s3_key", "")
        )
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return referenced_keys
        scan_kwargs["ExclusiveStartKey"] = last_key


def quarantine_objects(s3_client, orphaned, source_bucket, quarantine_bucket, ds):
    moved_count = 0
    failed_count = 0
    for obj in orphaned:
        source_key = obj["key"]
        dest_key = "%s/%s/%s" % (QUARANTINE_PREFIX, ds, source_key)
        try:
            s3_client.copy_object(
                Bucket=quarantine_bucket,
                Key=dest_key,
                CopySource={"Bucket": source_bucket, "Key": source_key},
                MetadataDirective="COPY",
            )
            s3_client.delete_object(Bucket=source_bucket, Key=source_key)
            moved_count += 1
        except Exception as e:
            print("[%s] WARNING: Failed to quarantine %s: %s" % (_now(), source_key, str(e)))
            failed_count += 1
    return moved_count, failed_count


def build_report(ds, total_objects, total_size_bytes, orphaned_count, orphaned_bytes,
                 moved_count, failed_count, quarantine_bucket):
    savings_gb = orphaned_bytes / (1024 ** 3)
    return {
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
            "orphaned_size_gb": round(savings_gb, 4),
            "orphan_percentage": round(
                (orphaned_count / total_objects * 100) if total_objects else 0, 2
            ),
        },
        "cleanup": {
            "objects_quarantined": moved_count,
            "objects_failed": failed_count,
            "quarantine_bucket": quarantine_bucket,
        },
        "savings": {
            "storage_freed_gb": round(savings_gb, 4),
            "estimated_monthly_savings_usd": round(savings_gb * S3_PRICE_PER_GB_MONTH, 4),
        },
    }


def main():
    print("[%s] storage_cleanup_daily.py starting..." % _now())

    # ---- Load config ----
    config = configparser.ConfigParser()
    config.read("/opt/etl/config.ini")

    aws_kwargs = _aws_kwargs(config)

    file_storage_bucket = config.get("s3", "file_storage_bucket")
    quarantine_bucket = config.get("s3", "quarantine_bucket")
    data_lake_bucket = config.get("s3", "data_lake_bucket")

    ds = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # ---- List all S3 objects ----
    print("[%s] Listing objects in s3://%s/%s" % (_now(), file_storage_bucket, FILES_PREFIX))

    s3_client = boto3.client("s3", **aws_kwargs)
    all_objects = list_s3_objects(s3_client, file_storage_bucket, FILES_PREFIX)

    total_objects = len(all_objects)
    total_size_bytes = sum(o["size"] for o in all_objects)

    print("[%s] Found %d objects in S3 (%d bytes total)" % (_now(), total_objects, total_size_bytes))

    # ---- List metadata references from DynamoDB ----
    print("[%s] Scanning DynamoDB table %s for metadata references..." % (_now(), DYNAMODB_TABLE_NAME))

    dynamodb = boto3.resource("dynamodb", **aws_kwargs)
    referenced_keys = scan_referenced_keys(dynamodb.Table(DYNAMODB_TABLE_NAME))

    print("[%s] Found %d S3 keys referenced in metadata" % (_now(), len(referenced_keys)))

    # ---- Find orphaned objects ----
    orphaned = [obj for obj in all_objects if obj["key"] not in referenced_keys]
    orphaned_bytes = sum(obj["size"] for obj in orphaned)
    orphaned_count = len(orphaned)

    print("[%s] Found %d orphaned objects (%.2f MB)" % (
        _now(), orphaned_count, orphaned_bytes / (1024 * 1024),
    ))

    if orphaned_count == 0:
        # Still generate report even with 0 orphans
        print("[%s] No orphaned objects to quarantine" % _now())
    else:
        # ---- Move orphaned objects to quarantine ----
        print("[%s] Moving %d orphaned objects to quarantine..." % (_now(), orphaned_count))

    moved_count, failed_count = quarantine_objects(
        s3_client, orphaned, file_storage_bucket, quarantine_bucket, ds
    )

    if orphaned_count > 0:
        print("[%s] Quarantined %d objects (%d failed) to s3://%s/%s/%s/" % (
            _now(), moved_count, failed_count, quarantine_bucket, QUARANTINE_PREFIX, ds,
        ))

    # ---- Generate storage cleanup report ----
    report = build_report(
        ds, total_objects, total_size_bytes, orphaned_count, orphaned_bytes,
        moved_count, failed_count, quarantine_bucket,
    )

    report_key = "reports/storage-cleanup/%s/report.json" % ds
    s3_client_report = boto3.client("s3", **aws_kwargs)
    s3_client_report.put_object(
        Bucket=data_lake_bucket,
        Key=report_key,
        Body=json.dumps(report, indent=2).encode("utf-8"),
    )

    savings = report["savings"]
    print("[%s] Storage cleanup report: %d orphans quarantined, %.4f GB freed, ~$%.4f/month saved" % (
        _now(), moved_count, orphaned_bytes / (1024 ** 3), savings["estimated_monthly_savings_usd"],
    ))
    print("[%s] storage_cleanup_daily.py completed successfully" % _now())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[%s] FATAL: %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(e)))
        sys.exit(1)
