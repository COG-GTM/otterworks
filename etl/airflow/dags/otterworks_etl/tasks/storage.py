"""storage_cleanup_daily: quarantine S3 objects no longer referenced by file metadata."""

from __future__ import annotations

import logging
from datetime import datetime

from otterworks_etl import s3io, settings
from otterworks_etl.json_logging import log_event
from otterworks_etl.transforms import storage as T

logger = logging.getLogger(__name__)


def _s3():
    from airflow.providers.amazon.aws.hooks.s3 import S3Hook

    return S3Hook(aws_conn_id=settings.AWS_CONN_ID)


def _staging(cfg: dict, ds: str, name: str) -> str:
    return f"{cfg['staging_prefix']}/storage-cleanup/ds={ds}/{name}.json"


def list_s3_objects(ds: str, cfg: dict) -> dict:
    s3 = _s3()
    paginator = s3.get_conn().get_paginator("list_objects_v2")
    objects = [{"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"].isoformat()}
               for page in paginator.paginate(Bucket=cfg["file_storage_bucket"],
                                              Prefix=cfg["files_prefix"])
               for o in page.get("Contents", [])]
    s3io.put_json(s3, cfg["data_lake_bucket"], _staging(cfg, ds, "objects"), objects)
    log_event(logger, "s3_inventory", objects=len(objects))
    return {"total_objects": len(objects), "total_size_bytes": sum(o["size"] for o in objects)}


def list_metadata_references(ds: str, cfg: dict) -> int:
    from airflow.providers.amazon.aws.hooks.dynamodb import DynamoDBHook

    name = cfg["file_metadata_table"]
    table = DynamoDBHook(aws_conn_id=settings.AWS_CONN_ID, table_name=name).get_conn().Table(name)
    kwargs, refs = {"ProjectionExpression": "s3_key"}, set()
    while True:
        resp = table.scan(**kwargs)
        refs.update(i["s3_key"] for i in resp.get("Items", []) if i.get("s3_key"))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    s3io.put_json(_s3(), cfg["data_lake_bucket"], _staging(cfg, ds, "references"), sorted(refs))
    log_event(logger, "metadata_references", references=len(refs))
    return len(refs)


def find_orphaned_objects(ds: str, cfg: dict, now: datetime) -> dict:
    s3, bucket = _s3(), cfg["data_lake_bucket"]
    objects = s3io.get_json(s3, bucket, _staging(cfg, ds, "objects")) or []
    refs = set(s3io.get_json(s3, bucket, _staging(cfg, ds, "references")) or [])
    orphans, recent = T.find_orphans(objects, refs, now, float(cfg["storage_cleanup_grace_hours"]))
    T.check_guard(len(objects), len(orphans), float(cfg["storage_cleanup_max_orphan_pct"]))
    s3io.put_json(s3, bucket, _staging(cfg, ds, "orphans"), {"orphans": orphans, "recent": recent})
    log_event(logger, "orphans_found", orphans=len(orphans), within_grace=len(recent))
    return {"orphans": len(orphans), "recent": len(recent)}


def move_to_quarantine(ds: str, cfg: dict) -> dict:
    s3, dry_run = _s3(), bool(cfg["storage_cleanup_dry_run"])
    found = s3io.get_json(s3, cfg["data_lake_bucket"], _staging(cfg, ds, "orphans")) or {}
    client, moved, failed = s3.get_conn(), 0, []
    for obj in found.get("orphans", []):
        dest = T.quarantine_key(cfg["quarantine_prefix"], ds, obj["key"])
        if dry_run:
            log_event(logger, "would_quarantine", key=obj["key"], dest=dest)
            continue
        try:
            client.copy_object(Bucket=cfg["quarantine_bucket"], Key=dest, MetadataDirective="COPY",
                               CopySource={"Bucket": cfg["file_storage_bucket"], "Key": obj["key"]})
            client.delete_object(Bucket=cfg["file_storage_bucket"], Key=obj["key"])
            moved += 1
        except client.exceptions.ClientError as exc:
            failed.append(obj["key"])
            log_event(logger, "quarantine_failed", logging.ERROR, key=obj["key"], error=str(exc))
    if failed:
        raise RuntimeError(f"failed to quarantine {len(failed)} object(s): {failed[:10]}")
    log_event(logger, "quarantine_complete", moved=moved, dry_run=dry_run)
    return {"moved": moved, "failed": 0}


def generate_storage_report(ds: str, cfg: dict, inventory: dict, moved: dict,
                            generated_at: str) -> str:
    s3 = _s3()
    found = s3io.get_json(s3, cfg["data_lake_bucket"], _staging(cfg, ds, "orphans")) or {}
    quarantined = s3.list_keys(bucket_name=cfg["quarantine_bucket"],
                               prefix=f"{cfg['quarantine_prefix']}/{ds}/") or []
    report = T.build_report(ds, generated_at, inventory, found.get("orphans", []),
                            found.get("recent", []), moved["moved"], moved["failed"],
                            cfg["quarantine_bucket"], bool(cfg["storage_cleanup_dry_run"]),
                            len(quarantined))
    key = f"reports/storage-cleanup/{ds}/report.json"
    s3io.put_json(s3, cfg["data_lake_bucket"], key, report)
    log_event(logger, "storage_report_written", key=key, **report["orphans"])
    return key
