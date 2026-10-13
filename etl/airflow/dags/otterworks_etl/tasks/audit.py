"""audit_archive_weekly: DynamoDB audit events older than retention -> S3 Glacier -> delete."""

from __future__ import annotations

import logging

from otterworks_etl import s3io, settings
from otterworks_etl.json_logging import log_event
from otterworks_etl.transforms import audit as T

logger = logging.getLogger(__name__)

ARCHIVE_PREFIX = "audit-archive"
DYNAMODB_BATCH = 25


def _s3():
    from airflow.providers.amazon.aws.hooks.s3 import S3Hook

    return S3Hook(aws_conn_id=settings.AWS_CONN_ID)


def _table(cfg: dict):
    from airflow.providers.amazon.aws.hooks.dynamodb import DynamoDBHook

    name = cfg["audit_events_table"]
    return DynamoDBHook(aws_conn_id=settings.AWS_CONN_ID, table_name=name).get_conn().Table(name)


def staging_key(cfg: dict, ds: str) -> str:
    return f"{cfg['staging_prefix']}/audit-archive/ds={ds}/events.jsonl.gz"


def scan_audit_events(ds: str, as_of: str, cfg: dict) -> dict:
    """Snapshot events older than the cutoff into a STANDARD-class staging object."""
    table = _table(cfg)
    # Read the real key schema instead of assuming (event_id, timestamp) like the legacy script.
    key_attrs = [k["AttributeName"] for k in table.key_schema]
    cutoff_ts = T.cutoff(as_of, int(cfg["audit_retention_days"]))
    kwargs = {"FilterExpression": "#ts < :cutoff", "ExpressionAttributeNames": {"#ts": cfg["audit_timestamp_attr"]},
              "ExpressionAttributeValues": {":cutoff": cutoff_ts}}
    items: list[dict] = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    s3io.put_bytes(_s3(), cfg["data_lake_bucket"], staging_key(cfg, ds), s3io.jsonl_gz_bytes(items))
    log_event(logger, "audit_scan_complete", events=len(items), cutoff=cutoff_ts)
    return {"events_scanned": len(items), "cutoff": cutoff_ts, "key_attrs": key_attrs}


def compress_and_upload(ds: str, cfg: dict, key_attrs: list[str]) -> dict:
    """Write the staged events to a content-addressed archive object (re-runs overwrite it)."""
    s3 = _s3()
    events = list(s3io.iter_jsonl(s3io.get_bytes(s3, cfg["data_lake_bucket"], staging_key(cfg, ds))
                                  or b""))
    if not events:
        log_event(logger, "audit_nothing_to_archive")
        return {"events_archived": 0, "archive_location": None, "compressed_size_bytes": 0}
    keys = [T.item_key(e, key_attrs) for e in events]
    key = T.archive_key(ARCHIVE_PREFIX, ds, T.keys_digest(keys))
    body = s3io.jsonl_gz_bytes(events)
    s3io.put_bytes(s3, cfg["archive_bucket"], key, body,
                   StorageClass=cfg["audit_archive_storage_class"],
                   Metadata={"event-count": str(len(events))})
    location = f"s3://{cfg['archive_bucket']}/{key}"
    log_event(logger, "audit_archived", events=len(events), location=location, bytes=len(body))
    return {"events_archived": len(events), "archive_location": location,
            "archive_key": key, "compressed_size_bytes": len(body)}


def cleanup_dynamodb(ds: str, cfg: dict, key_attrs: list[str], archive_key: str | None) -> int:
    """Delete only events that are provably in the archive (head_object must succeed)."""
    if not archive_key:
        return 0
    s3 = _s3()
    if not s3.check_for_key(archive_key, bucket_name=cfg["archive_bucket"]):
        raise RuntimeError(f"archive object {archive_key} missing; refusing to delete source rows")
    events = s3io.iter_jsonl(s3io.get_bytes(s3, cfg["data_lake_bucket"], staging_key(cfg, ds)) or b"")
    keys = [T.item_key(e, key_attrs) for e in events]
    table, deleted = _table(cfg), 0
    for batch in T.chunks(keys, DYNAMODB_BATCH):
        # batch_writer resubmits UnprocessedItems; real errors propagate and fail the task.
        with table.batch_writer() as writer:
            for k in batch:
                writer.delete_item(Key=k)
        deleted += len(batch)
    log_event(logger, "audit_source_rows_deleted", deleted=deleted)
    return deleted


def generate_compliance_report(ds: str, cfg: dict, run: dict, generated_at: str) -> str:
    s3, bucket = _s3(), cfg["archive_bucket"]
    prefix = f"{ARCHIVE_PREFIX}/year={ds[:4]}/week={ds}/"
    parts = []
    for key in s3.list_keys(bucket_name=bucket, prefix=prefix) or []:
        head = s3.get_conn().head_object(Bucket=bucket, Key=key)
        parts.append({"key": key, "size_bytes": head["ContentLength"],
                      "event_count": int(head.get("Metadata", {}).get("event-count", 0))})
    report = T.compliance_report(ds, generated_at, int(cfg["audit_retention_days"]),
                                 run.get("cutoff", ""), run, parts,
                                 cfg["audit_archive_storage_class"])
    key = f"reports/compliance/audit-archive/{ds}/report.json"
    s3io.put_json(s3, bucket, key, report)
    log_event(logger, "audit_report_written", key=key, parts=len(parts))
    return key
