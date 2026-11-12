"""Every ETL S3 request must pin the bucket owner (ExpectedBucketOwner).

Runs each script's main() end to end against an in-process fake S3 that
enforces ExpectedBucketOwner the way S3 does (403 AccessDenied on mismatch).
Real botocore clients are used, so request parameters are validated against
the S3 service model; SQS, DynamoDB and PostgreSQL are replaced with fakes.

    pip install -r etl/requirements.txt pytest
    python -m pytest etl/tests
"""

import configparser
import gzip
import importlib.util
import io
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

import boto3
import botocore.session
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import ClientError

ETL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ETL_DIR / "scripts"
OWNER = "123456789012"
ATTACKER = "999988887777"

ORIGINAL_CONFIG_READ = configparser.ConfigParser.read


class FakeS3:
    def __init__(self, bucket_owner=OWNER):
        self.bucket_owner = bucket_owner
        self.objects = {}
        self.calls = []

    def seed(self, bucket, key, body):
        self.objects[(bucket, key)] = body

    def _check(self, op, bucket, expected):
        if expected is not None and expected != self.bucket_owner:
            return {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        return None

    def handle(self, op, params):
        self.calls.append((op, params))
        bucket = params.get("Bucket")
        denied = self._check(op, bucket, params.get("ExpectedBucketOwner"))
        if op == "CopyObject":
            src_bucket, _, src_key = unquote(params["CopySource"]).partition("/")
            if not denied:
                denied = self._check(op, src_bucket, params.get("ExpectedSourceBucketOwner"))
        if denied:
            return 403, denied
        if op == "PutObject":
            body = params["Body"]
            self.objects[(bucket, params["Key"])] = body.read() if hasattr(body, "read") else body
            return 200, {}
        if op == "GetObject":
            if (bucket, params["Key"]) not in self.objects:
                return 404, {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}
            return 200, {"Body": io.BytesIO(self.objects[(bucket, params["Key"])])}
        if op == "ListObjectsV2":
            contents = [
                {"Key": k, "Size": len(v), "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc)}
                for (b, k), v in sorted(self.objects.items())
                if b == bucket and k.startswith(params.get("Prefix", ""))
            ]
            return 200, {"Contents": contents, "IsTruncated": False}
        if op == "CopyObject":
            self.objects[(bucket, params["Key"])] = self.objects[(src_bucket, src_key)]
            return 200, {}
        if op == "DeleteObject":
            self.objects.pop((bucket, params["Key"]), None)
            return 204, {}
        raise AssertionError(f"unexpected S3 operation {op}")

    def client(self):
        client = botocore.session.get_session().create_client(
            "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test"
        )

        def capture(params, context, **_):
            context["api_params"] = dict(params)

        def respond(model, context, **_):
            status, parsed = self.handle(model.name, context["api_params"])
            parsed.setdefault("ResponseMetadata", {"HTTPStatusCode": status})
            return AWSResponse("https://s3.amazonaws.com", status, {}, None), parsed

        client.meta.events.register("before-parameter-build.s3", capture)
        client.meta.events.register("before-call.s3", respond)
        return client


class FakeSQS:
    def __init__(self, bodies):
        self.batches = [[{"Body": json.dumps(b), "MessageId": str(i), "ReceiptHandle": f"rh{i}"}
                         for i, b in enumerate(bodies)]]
        self.received = 0
        self.deleted = []

    def receive_message(self, **_):
        self.received += 1
        return {"Messages": self.batches.pop(0) if self.batches else []}

    def delete_message_batch(self, Entries, **_):
        self.deleted.extend(Entries)


class FakeTable:
    def __init__(self, items):
        self.items = items
        self.deleted = []

    def scan(self, **_):
        return {"Items": [dict(i) for i in self.items]}

    def batch_writer(self):
        table = self

        class Writer:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def delete_item(self, Key):
                table.deleted.append(Key)

        return Writer()


class Harness:
    def __init__(self, monkeypatch, tmp_path, bucket_owner=OWNER, config_owner=OWNER,
                 sqs_bodies=(), dynamo_items=(), pg_rows=()):
        self.s3 = FakeS3(bucket_owner)
        self.sqs = FakeSQS(list(sqs_bodies))
        self.table = FakeTable(list(dynamo_items))
        self.aws_clients = []

        config = configparser.ConfigParser()
        ORIGINAL_CONFIG_READ(config, ETL_DIR / "config.ini")
        if config_owner is None:
            config.remove_option("s3", "expected_bucket_owner")
        else:
            config.set("s3", "expected_bucket_owner", config_owner)
        config_path = tmp_path / "config.ini"
        with open(config_path, "w") as fh:
            config.write(fh)

        def read(cfg, filenames, encoding=None):
            assert filenames == "/opt/etl/config.ini"
            return ORIGINAL_CONFIG_READ(cfg, config_path, encoding)

        def client(service, **_):
            self.aws_clients.append(service)
            return {"s3": self.s3.client, "sqs": lambda: self.sqs}[service]()

        def resource(service, **_):
            self.aws_clients.append(service)
            assert service == "dynamodb"
            return types.SimpleNamespace(Table=lambda name: self.table)

        cursor = mock.MagicMock()
        cursor.fetchall.return_value = list(pg_rows)
        connection = mock.MagicMock()
        connection.cursor.return_value = cursor
        fake_psycopg2 = types.ModuleType("psycopg2")
        fake_psycopg2.connect = mock.MagicMock(return_value=connection)

        monkeypatch.setattr(configparser.ConfigParser, "read", read)
        monkeypatch.setattr(boto3, "client", client)
        monkeypatch.setattr(boto3, "resource", resource)
        monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
        monkeypatch.syspath_prepend(str(SCRIPTS_DIR))
        monkeypatch.delenv("ETL_S3_EXPECTED_BUCKET_OWNER", raising=False)

    def run(self, script):
        spec = importlib.util.spec_from_file_location(script, SCRIPTS_DIR / f"{script}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()

    def assert_all_calls_pinned(self, expected_ops):
        assert {op for op, _ in self.s3.calls} == set(expected_ops)
        for op, params in self.s3.calls:
            assert params.get("ExpectedBucketOwner") == OWNER, (op, params)
            if op == "CopyObject":
                assert params.get("ExpectedSourceBucketOwner") == OWNER, params


def today():
    return datetime.now(tz=timezone.utc)


EVENT = {"eventType": "document_created", "ownerId": "u1", "documentId": "d1",
         "timestamp": "2026-11-12T10:00:00Z"}
AUDIT_ITEM = {"event_id": "e1", "timestamp": "2020-01-01T00:00:00Z", "action": "login"}


def seed_storage(s3):
    s3.seed("otterworks-file-storage", "files/kept.bin", b"kept")
    s3.seed("otterworks-file-storage", "files/orphan.bin", b"orphan")


def seed_top_users(s3):
    d = today()
    key = f"analytics/daily/year={d:%Y}/month={d:%m}/day={d:%d}/top_users.jsonl.gz"
    line = json.dumps({"user_id": "u1", "total": 3, "actions": {"document_created": 3}})
    s3.seed("otterworks-data-lake", key, gzip.compress(line.encode()))


# ---- owner matches: every request carries ExpectedBucketOwner and succeeds ----

def test_analytics_daily_pins_owner(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, sqs_bodies=[EVENT])
    h.run("analytics_daily")
    h.assert_all_calls_pinned({"PutObject"})
    assert len(h.s3.calls) == 4
    assert len(h.s3.objects) == 4


def test_audit_archive_weekly_pins_owner(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, dynamo_items=[AUDIT_ITEM])
    h.run("audit_archive_weekly")
    h.assert_all_calls_pinned({"PutObject"})
    assert h.s3.calls[0][1]["StorageClass"] == "GLACIER"
    assert h.table.deleted == [{"event_id": "e1", "timestamp": "2020-01-01T00:00:00Z"}]


def test_storage_cleanup_daily_pins_owner(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, dynamo_items=[{"s3_key": "files/kept.bin"}])
    seed_storage(h.s3)
    h.run("storage_cleanup_daily")
    h.assert_all_calls_pinned({"ListObjectsV2", "CopyObject", "DeleteObject", "PutObject"})
    assert ("otterworks-file-storage", "files/orphan.bin") not in h.s3.objects
    assert ("otterworks-file-storage", "files/kept.bin") in h.s3.objects
    assert any(b == "otterworks-file-quarantine" for b, _ in h.s3.objects)


def test_user_activity_daily_pins_owner(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path)
    seed_top_users(h.s3)
    h.run("user_activity_daily")
    h.assert_all_calls_pinned({"GetObject", "PutObject"})
    latest = json.loads(h.s3.objects[("otterworks-data-lake", "reports/user-activity/latest/activity_report.json")])
    assert latest["top_users"][0]["user_id"] == "u1"


# ---- bucket owned by another account: S3 refuses, nothing is written ----

def test_analytics_daily_refuses_foreign_bucket(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, bucket_owner=ATTACKER, sqs_bodies=[EVENT])
    with pytest.raises(ClientError, match="AccessDenied"):
        h.run("analytics_daily")
    assert h.s3.objects == {}


def test_audit_archive_weekly_refuses_foreign_bucket_and_keeps_source(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, bucket_owner=ATTACKER, dynamo_items=[AUDIT_ITEM])
    with pytest.raises(ClientError, match="AccessDenied"):
        h.run("audit_archive_weekly")
    assert h.s3.objects == {}
    assert h.table.deleted == []


def test_storage_cleanup_daily_refuses_foreign_bucket(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, bucket_owner=ATTACKER)
    seed_storage(h.s3)
    with pytest.raises(ClientError, match="AccessDenied"):
        h.run("storage_cleanup_daily")
    assert [op for op, _ in h.s3.calls] == ["ListObjectsV2"]
    assert len(h.s3.objects) == 2


def test_user_activity_daily_refuses_foreign_bucket(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, bucket_owner=ATTACKER)
    seed_top_users(h.s3)
    with pytest.raises(ClientError, match="AccessDenied"):
        h.run("user_activity_daily")
    assert len(h.s3.objects) == 1


# ---- configuration ----

SCRIPTS = ["analytics_daily", "audit_archive_weekly", "storage_cleanup_daily", "user_activity_daily"]


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("owner", [None, "", "12345", "otterworks", "1234567890123"])
def test_missing_or_invalid_owner_fails_before_any_aws_call(monkeypatch, tmp_path, script, owner):
    h = Harness(monkeypatch, tmp_path, config_owner=owner, sqs_bodies=[EVENT], dynamo_items=[AUDIT_ITEM])
    with pytest.raises(SystemExit, match="expected_bucket_owner"):
        h.run(script)
    assert h.aws_clients == []
    assert h.sqs.received == 0


def test_env_var_overrides_config(monkeypatch, tmp_path):
    h = Harness(monkeypatch, tmp_path, bucket_owner=ATTACKER, config_owner=OWNER, sqs_bodies=[EVENT])
    monkeypatch.setenv("ETL_S3_EXPECTED_BUCKET_OWNER", ATTACKER)
    h.run("analytics_daily")
    assert {p["ExpectedBucketOwner"] for _, p in h.s3.calls} == {ATTACKER}
