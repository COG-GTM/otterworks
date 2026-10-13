"""Task callables against moto-mocked S3/SQS/DynamoDB through the Airflow provider hooks."""

import gzip
import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

import analytics_daily_aggregate as spark_job
from otterworks_etl import s3io
from otterworks_etl.tasks import analytics as A
from otterworks_etl.tasks import audit as AU
from otterworks_etl.tasks import storage as ST
from otterworks_etl.tasks import user_activity as UA
from otterworks_etl.transforms import analytics as ref

DS = "2026-03-01"


@pytest.fixture
def aws(cfg):
    with mock_aws():
        s3 = boto3.client("s3")
        for b in ("data_lake_bucket", "file_storage_bucket", "quarantine_bucket", "archive_bucket"):
            s3.create_bucket(Bucket=cfg[b])
        yield s3


def _ddb_table(name, keys):
    ddb = boto3.resource("dynamodb")
    return ddb.create_table(
        TableName=name, BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys])


def _read_gz_jsonl(s3, bucket, key):
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return [json.loads(line) for line in gzip.decompress(body).decode().splitlines() if line]


class FakePostgres:
    calls: list = []

    def __init__(self, postgres_conn_id):
        self.conn_id = postgres_conn_id

    def run(self, sql, parameters=None):
        FakePostgres.calls.append((sql, parameters))


def test_analytics_pipeline_end_to_end(aws, cfg, spark, monkeypatch):
    sqs = boto3.client("sqs")
    url = sqs.create_queue(QueueName=cfg["analytics_queue_name"])["QueueUrl"]
    events = [
        {"eventId": "e1", "eventType": "document_created", "ownerId": "u1", "documentId": "d1",
         "timestamp": f"{DS}T09:00:00Z"},
        {"eventId": "e2", "eventType": "file_uploaded", "ownerId": "u2", "fileId": "f1",
         "sizeBytes": 100, "timestamp": f"{DS}T10:00:00Z"},
        {"eventId": "e0", "eventType": "comment_added", "authorId": "u3",
         "timestamp": "2026-02-28T23:00:00Z"},  # late event -> its own date partition
    ]
    for e in events:
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps(e))
    sqs.send_message(QueueUrl=url, MessageBody="{not json")
    table = _ddb_table(cfg["analytics_events_table"], [("event_id", "HASH")])
    table.put_item(Item={"event_id": "x1", "eventId": "x1", "event_date": DS,
                         "eventType": "document_edited", "editedBy": "u1", "documentId": "d1",
                         "timestamp": f"{DS}T09:30:00Z"})
    table.put_item(Item={"event_id": "x2", "event_date": "2026-02-27", "eventType": "login"})

    assert A.extract_from_sqs(DS, cfg) == {"received": 4, "landed": 3, "malformed": 1}
    assert int(sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"]
               ["ApproximateNumberOfMessages"]) == 0
    assert A.extract_from_dynamodb(DS, cfg)["items"] == 1
    lake = cfg["data_lake_bucket"]
    keys = [o["Key"] for o in aws.list_objects_v2(Bucket=lake)["Contents"]]
    assert any("source=sqs/ds=2026-02-28/" in k for k in keys)
    assert any("_deadletter/ds=2026-03-01/" in k for k in keys)

    staged = A.stage_raw_local(DS, cfg)
    assert staged["files"] == 2
    spark_job.run(spark, DS, staged["raw_dir"], staged["out_dir"], 100)
    location = A.publish_curated_local(DS, cfg, staged["out_dir"])["location"]
    agg = A.read_aggregates(location, cfg)
    day_events = [e for e in events if e["timestamp"].startswith(DS)] + [
        {"eventId": "x1", "eventType": "document_edited", "editedBy": "u1", "documentId": "d1",
         "timestamp": f"{DS}T09:30:00Z"}]
    assert agg == ref.aggregate(day_events)
    assert agg["summary"]["total_events"] == 3

    part = A.load_to_data_lake(DS, cfg, agg).split(lake + "/")[1]
    assert _read_gz_jsonl(aws, lake, f"{part}/top_users.jsonl.gz") == agg["top_users"]

    FakePostgres.calls = []
    monkeypatch.setattr("airflow.providers.postgres.hooks.postgres.PostgresHook", FakePostgres)
    A.update_postgres_aggregates(DS, cfg, agg)
    assert "CREATE TABLE IF NOT EXISTS analytics_daily_summary" in FakePostgres.calls[0][0]
    assert FakePostgres.calls[1][1] == ref.upsert_params(DS, agg["summary"])

    key = A.generate_report(DS, cfg, agg, "2026-03-02T02:10:00Z")
    report = json.loads(aws.get_object(Bucket=lake, Key=key)["Body"].read())
    assert report["summary"]["total_events"] == 3 and report["report_date"] == DS

    # Backfill / re-run of the same ds: raw re-snapshot + curated overwrite, no double count.
    A.extract_from_dynamodb(DS, cfg)
    staged = A.stage_raw_local(DS, cfg)
    spark_job.run(spark, DS, staged["raw_dir"], staged["out_dir"], 100)
    A.publish_curated_local(DS, cfg, staged["out_dir"])
    assert A.read_aggregates(location, cfg) == agg


def test_audit_archive_flow_is_safe_and_idempotent(aws, cfg):
    table = _ddb_table(cfg["audit_events_table"], [("event_id", "HASH"), ("timestamp", "RANGE")])
    old = [{"event_id": f"o{i}", "timestamp": "2025-01-01T00:00:00Z", "action": "x"}
           for i in range(30)]
    for item in old + [{"event_id": "new", "timestamp": "2026-03-01T00:00:00Z"}]:
        table.put_item(Item=item)

    scan = AU.scan_audit_events(DS, "2026-03-01T03:00:00+00:00", cfg)
    assert scan["events_scanned"] == 30 and scan["key_attrs"] == ["event_id", "timestamp"]
    archive = AU.compress_and_upload(DS, cfg, scan["key_attrs"])
    head = aws.head_object(Bucket=cfg["archive_bucket"], Key=archive["archive_key"])
    assert head["StorageClass"] == "GLACIER" and head["Metadata"]["event-count"] == "30"
    assert AU.cleanup_dynamodb(DS, cfg, scan["key_attrs"], archive["archive_key"]) == 30
    assert [i["event_id"] for i in table.scan()["Items"]] == ["new"]
    report_key = AU.generate_compliance_report(DS, cfg, {**scan, **archive, "events_deleted": 30},
                                               "t")
    report = json.loads(aws.get_object(Bucket=cfg["archive_bucket"], Key=report_key)["Body"].read())
    assert report["events_archived_in_partition"] == 30

    # Re-run after success: nothing left to archive, archive object untouched.
    scan2 = AU.scan_audit_events(DS, "2026-03-01T03:00:00+00:00", cfg)
    assert scan2["events_scanned"] == 0
    assert AU.compress_and_upload(DS, cfg, scan2["key_attrs"])["events_archived"] == 0


def test_audit_cleanup_refuses_without_archive(aws, cfg):
    _ddb_table(cfg["audit_events_table"], [("event_id", "HASH"), ("timestamp", "RANGE")])
    with pytest.raises(RuntimeError, match="refusing to delete"):
        AU.cleanup_dynamodb(DS, cfg, ["event_id", "timestamp"], "audit-archive/missing.jsonl.gz")


def _storage_fixture(aws, cfg):
    table = _ddb_table(cfg["file_metadata_table"], [("file_id", "HASH")])
    for i in range(4):
        aws.put_object(Bucket=cfg["file_storage_bucket"], Key=f"files/{i}.bin", Body=b"x" * (i + 1))
    for i in range(3):
        table.put_item(Item={"file_id": str(i), "s3_key": f"files/{i}.bin"})


def test_storage_cleanup_quarantines_orphans_once(aws, cfg):
    _storage_fixture(aws, cfg)
    later = datetime.now(timezone.utc) + timedelta(days=2)
    inv = ST.list_s3_objects(DS, cfg)
    assert inv == {"total_objects": 4, "total_size_bytes": 10}
    assert ST.list_metadata_references(DS, cfg) == 3
    assert ST.find_orphaned_objects(DS, cfg, later) == {"orphans": 1, "recent": 0}
    assert ST.move_to_quarantine(DS, cfg) == {"moved": 1, "failed": 0}
    assert aws.head_object(Bucket=cfg["quarantine_bucket"], Key=f"quarantined/{DS}/files/3.bin")
    key = ST.generate_storage_report(DS, cfg, inv, {"moved": 1, "failed": 0}, "t")
    rep = json.loads(aws.get_object(Bucket=cfg["data_lake_bucket"], Key=key)["Body"].read())
    assert rep["orphans"]["orphaned_objects"] == 1
    assert rep["cleanup"]["objects_in_quarantine_partition"] == 1
    # Re-run: the orphan is gone, nothing more moves.
    ST.list_s3_objects(DS, cfg)
    ST.list_metadata_references(DS, cfg)
    assert ST.find_orphaned_objects(DS, cfg, later)["orphans"] == 0
    assert ST.move_to_quarantine(DS, cfg)["moved"] == 0


def test_storage_cleanup_grace_dry_run_and_guard(aws, cfg):
    _storage_fixture(aws, cfg)
    ST.list_s3_objects(DS, cfg)
    ST.list_metadata_references(DS, cfg)
    assert ST.find_orphaned_objects(DS, cfg, datetime.now(timezone.utc)) == \
        {"orphans": 0, "recent": 1}
    cfg_dry = dict(cfg, storage_cleanup_dry_run=True)
    ST.find_orphaned_objects(DS, cfg, datetime.now(timezone.utc) + timedelta(days=2))
    assert ST.move_to_quarantine(DS, cfg_dry)["moved"] == 0
    assert len(aws.list_objects_v2(Bucket=cfg["file_storage_bucket"])["Contents"]) == 4
    with pytest.raises(RuntimeError, match="safety limit"):
        ST.find_orphaned_objects(DS, dict(cfg, storage_cleanup_max_orphan_pct=10.0),
                                 datetime.now(timezone.utc) + timedelta(days=2))


def test_user_activity_report_and_latest_pointer(aws, cfg, monkeypatch):
    lake = cfg["data_lake_bucket"]
    cfg = dict(cfg, user_activity_lookback_days=3)
    for day, rows in {"2026-03-01": [{"user_id": "u1", "total": 2, "actions": {"a": 2}}],
                      "2026-02-28": [{"user_id": "u1", "total": 1, "actions": {"b": 1}},
                                     {"user_id": "u2", "total": 5, "actions": {"a": 5}}]}.items():
        key = f"{ref.partition_key(cfg['analytics_prefix'], day)}/top_users.jsonl.gz"
        aws.put_object(Bucket=lake, Key=key, Body=s3io.jsonl_gz_bytes(rows))

    class FakePg:
        def __init__(self, postgres_conn_id):
            pass

        def get_records(self, sql, parameters=None):
            assert parameters == ("2026-02-27", "2026-03-01")
            from datetime import date
            return [(date(2026, 2, 28), 2, 1, 0, 6, 1, 0, 0, 0, 0, 0, 0),
                    (date(2026, 3, 1), 1, 1, 0, 2, 0, 1, 0, 0, 0, 0, 0)]

    monkeypatch.setattr("airflow.providers.postgres.hooks.postgres.PostgresHook", FakePg)
    assert UA.extract_daily_summaries(DS, cfg) == 2
    top = UA.extract_top_users(DS, cfg)
    assert top == {"days_found": 2, "missing_days": ["2026-02-27"]}
    key = UA.build_and_load_report(DS, cfg, top["missing_days"], "t")
    rep = json.loads(aws.get_object(Bucket=lake, Key=key)["Body"].read())
    assert rep["top_users"][0] == {"user_id": "u2", "total_actions": 5, "active_days": 1,
                                   "actions_by_type": {"a": 5}}
    assert rep["trends"]["total_events"] == 8
    assert rep["daily_summaries"][0]["report_date"] == "2026-02-28"
    latest = f"{cfg['user_activity_reports_prefix']}/latest/activity_report.json"
    assert json.loads(aws.get_object(Bucket=lake, Key=latest)["Body"].read())["report_date"] == DS

    # A backfill of an older date writes its own report but keeps the newer latest pointer.
    monkeypatch.setattr(FakePg, "get_records", lambda self, sql, parameters=None: [])
    UA.extract_daily_summaries("2026-02-20", cfg)
    UA.extract_top_users("2026-02-20", cfg)
    UA.build_and_load_report("2026-02-20", cfg, [], "t")
    assert json.loads(aws.get_object(Bucket=lake, Key=latest)["Body"].read())["report_date"] == DS
