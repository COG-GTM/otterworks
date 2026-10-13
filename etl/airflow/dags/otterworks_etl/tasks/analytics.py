"""analytics_daily: SQS + DynamoDB -> raw zone -> PySpark aggregate -> data lake + Postgres."""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

from otterworks_etl import s3io, settings
from otterworks_etl.json_logging import log_event
from otterworks_etl.transforms import analytics as T

logger = logging.getLogger(__name__)

RAW_DATASET = "analytics"
DDL_PATH = Path(__file__).resolve().parents[1] / "sql" / "analytics_daily_summary.sql"


def _s3():
    from airflow.providers.amazon.aws.hooks.s3 import S3Hook

    return S3Hook(aws_conn_id=settings.AWS_CONN_ID)


def raw_prefix(cfg: dict, ds: str, source: str | None = None) -> str:
    src = f"source={source}" if source else "source=*"
    return f"{cfg['raw_prefix']}/{RAW_DATASET}/{src}/ds={ds}"


def curated_prefix(cfg: dict, ds: str) -> str:
    return f"{cfg['curated_prefix']}/{RAW_DATASET}/ds={ds}"


def _digest(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()[:16]


def extract_from_sqs(ds: str, cfg: dict) -> dict:
    """Drain the analytics queue into the raw zone, partitioned by each event's own date.

    Objects are written *before* messages are deleted (at-least-once); duplicates from
    redelivery are removed downstream by event key. Malformed bodies go to a dead-letter
    prefix instead of being dropped.
    """
    from airflow.providers.amazon.aws.hooks.sqs import SqsHook

    sqs = SqsHook(aws_conn_id=settings.AWS_CONN_ID).get_conn()
    queue_url = sqs.get_queue_url(QueueName=cfg["analytics_queue_name"])["QueueUrl"]
    s3, bucket = _s3(), cfg["data_lake_bucket"]
    received = landed = malformed = 0

    while received < int(cfg["sqs_max_messages"]):
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10,
                                   WaitTimeSeconds=int(cfg.get("sqs_wait_seconds", 2)),
                                   MessageAttributeNames=["All"])
        messages = resp.get("Messages", [])
        if not messages:
            break
        received += len(messages)
        by_date: dict[str, list[dict]] = {}
        bad: list[dict] = []
        for msg in messages:
            try:
                event = json.loads(msg["Body"])
                if not isinstance(event, dict):
                    raise ValueError("event body is not a JSON object")
            except ValueError as exc:
                bad.append({"message_id": msg["MessageId"], "body": msg["Body"], "error": str(exc)})
                continue
            event.setdefault("_source", "sqs")
            event.setdefault("_source_id", msg["MessageId"])
            by_date.setdefault(T.event_date(event, ds), []).append(event)

        batch_id = _digest([m["MessageId"] for m in messages])
        for event_ds, events in by_date.items():
            key = f"{raw_prefix(cfg, event_ds, 'sqs')}/batch-{batch_id}.jsonl.gz"
            s3io.put_bytes(s3, bucket, key, s3io.jsonl_gz_bytes(events))
            landed += len(events)
        if bad:
            key = f"{cfg['raw_prefix']}/{RAW_DATASET}/_deadletter/ds={ds}/batch-{batch_id}.jsonl.gz"
            s3io.put_bytes(s3, bucket, key, s3io.jsonl_gz_bytes(bad))
            malformed += len(bad)
            log_event(logger, "sqs_malformed_messages", logging.WARNING, count=len(bad), key=key)

        sqs.delete_message_batch(QueueUrl=queue_url, Entries=[
            {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]} for i, m in enumerate(messages)])

    result = {"received": received, "landed": landed, "malformed": malformed}
    log_event(logger, "sqs_extract_complete", **result)
    return result


def extract_from_dynamodb(ds: str, cfg: dict) -> dict:
    """Snapshot the day's DynamoDB events into one raw object (overwritten on re-run)."""
    from airflow.providers.amazon.aws.hooks.dynamodb import DynamoDBHook

    table = DynamoDBHook(aws_conn_id=settings.AWS_CONN_ID,
                         table_name=cfg["analytics_events_table"]).get_conn().Table(
        cfg["analytics_events_table"])
    kwargs = {"FilterExpression": "begins_with(event_date, :ds)",
              "ExpressionAttributeValues": {":ds": ds}}
    items: list[dict] = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    for item in items:
        item.setdefault("_source", "dynamodb")
    key = f"{raw_prefix(cfg, ds, 'dynamodb')}/events.jsonl.gz"
    s3io.put_bytes(_s3(), cfg["data_lake_bucket"], key, s3io.jsonl_gz_bytes(items))
    log_event(logger, "dynamodb_extract_complete", items=len(items), key=key)
    return {"items": len(items), "key": key}


def local_paths(cfg: dict, ds: str) -> tuple[str, str]:
    base = os.path.join(cfg["local_data_dir"], RAW_DATASET, f"ds={ds}")
    return os.path.join(base, "raw"), os.path.join(base, "out")


def stage_raw_local(ds: str, cfg: dict) -> dict:
    """Local-mode only: copy the day's raw objects to local disk for spark-submit local[*]."""
    s3, bucket = _s3(), cfg["data_lake_bucket"]
    raw_dir, out_dir = local_paths(cfg, ds)
    shutil.rmtree(os.path.dirname(raw_dir), ignore_errors=True)
    os.makedirs(raw_dir)
    keys = []
    for source in ("sqs", "dynamodb"):
        keys += s3.list_keys(bucket_name=bucket, prefix=raw_prefix(cfg, ds, source) + "/") or []
    for key in keys:
        data = s3io.get_bytes(s3, bucket, key) or b""
        fname = key.replace("/", "__")
        with open(os.path.join(raw_dir, fname), "wb") as fh:
            fh.write(data)
    log_event(logger, "raw_staged", files=len(keys), raw_dir=raw_dir)
    return {"raw_dir": raw_dir, "out_dir": out_dir, "files": len(keys)}


def read_aggregates(location: str, cfg: dict) -> dict:
    """Read the single-line aggregate JSON the Spark job writes under ``<location>/aggregates``."""
    if location.startswith(("s3://", "s3a://")):
        bucket, prefix = s3io.parse_s3_uri(location.replace("s3a://", "s3://"))
        s3 = _s3()
        keys = [k for k in s3.list_keys(bucket_name=bucket, prefix=f"{prefix}/aggregates/") or []
                if os.path.basename(k).startswith("part-")]
        data = s3io.get_bytes(s3, bucket, keys[0]).decode()
    else:
        parts = sorted(glob.glob(os.path.join(location, "aggregates", "part-*")))
        with open(parts[0], encoding="utf-8") as fh:
            data = fh.read()
    return json.loads(data.strip().splitlines()[0])


def publish_curated_local(ds: str, cfg: dict, out_dir: str) -> dict:
    """Local-mode only: upload the Spark output (parquet + aggregates) to the curated zone."""
    s3, bucket, prefix = _s3(), cfg["data_lake_bucket"], curated_prefix(cfg, ds)
    for stale in s3.list_keys(bucket_name=bucket, prefix=prefix + "/") or []:
        s3.delete_objects(bucket=bucket, keys=[stale])
    uploaded = 0
    for path in sorted(glob.glob(os.path.join(out_dir, "**", "*"), recursive=True)):
        name = os.path.basename(path)
        if os.path.isdir(path) or name.startswith((".", "_")):
            continue
        rel = os.path.relpath(path, out_dir)
        s3.load_file(path, key=f"{prefix}/{rel}", bucket_name=bucket, replace=True)
        uploaded += 1
    log_event(logger, "curated_published", files=uploaded, prefix=f"s3://{bucket}/{prefix}")
    return {"files": uploaded, "location": f"s3://{bucket}/{prefix}"}


def load_to_data_lake(ds: str, cfg: dict, agg: dict) -> str:
    """Legacy-compatible gzip JSON partition (consumed by user_activity_daily)."""
    s3, bucket = _s3(), cfg["data_lake_bucket"]
    part = T.partition_key(cfg["analytics_prefix"], ds)
    s3io.put_json(s3, bucket, f"{part}/summary.json.gz", agg["summary"], gz=True)
    s3io.put_json(s3, bucket, f"{part}/hourly_breakdown.json.gz", agg["hourly_breakdown"], gz=True)
    s3io.put_bytes(s3, bucket, f"{part}/top_users.jsonl.gz", s3io.jsonl_gz_bytes(agg["top_users"]))
    log_event(logger, "data_lake_loaded", partition=f"s3://{bucket}/{part}")
    return f"s3://{bucket}/{part}"


def update_postgres_aggregates(ds: str, cfg: dict, agg: dict) -> None:
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    hook = PostgresHook(postgres_conn_id=settings.POSTGRES_CONN_ID)
    hook.run(DDL_PATH.read_text())
    hook.run(T.UPSERT_SQL, parameters=T.upsert_params(ds, agg["summary"]))
    log_event(logger, "postgres_upserted", report_date=ds, **agg["summary"])


def generate_report(ds: str, cfg: dict, agg: dict, generated_at: str) -> str:
    report = T.build_report(ds, agg, generated_at)
    key = f"reports/analytics/daily/{ds}/report.json"
    s3io.put_json(_s3(), cfg["data_lake_bucket"], key, report)
    log_event(logger, "analytics_report_written", key=key,
              total_events=report["summary"]["total_events"],
              active_users=report["summary"]["active_users"])
    return key
