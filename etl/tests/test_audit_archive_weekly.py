import configparser
import importlib.util
import os
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "audit_archive_weekly.py")
BUCKET = "otterworks-audit-archive"
TABLE = "otterworks-audit-events"
MOTO_ACCOUNT = "123456789012"
FOREIGN_ACCOUNT = "999988887777"


def load_script():
    spec = importlib.util.spec_from_file_location("audit_archive_weekly", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def aws(monkeypatch, tmp_path):
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "event_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "event_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        old = (datetime.now(tz=timezone.utc) - timedelta(days=200)).isoformat()
        for i in range(3):
            table.put_item(Item={"event_id": "evt-%d" % i, "timestamp": old, "action": "login"})
        yield {"s3": s3, "table": table, "tmp_path": tmp_path, "monkeypatch": monkeypatch}


def run_script(aws, owner_setting=None):
    """Run main() with a temp config and an S3 hook that enforces ExpectedBucketOwner like AWS."""
    ini = aws["tmp_path"] / "config.ini"
    owner_line = "archive_bucket_owner = %s\n" % owner_setting if owner_setting is not None else ""
    ini.write_text(
        "[aws]\naccess_key = testing\nsecret_key = testing\nregion = us-east-1\n"
        "[s3]\narchive_bucket = %s\n%s" % (BUCKET, owner_line)
    )
    real_read = configparser.ConfigParser.read
    aws["monkeypatch"].setattr(
        configparser.ConfigParser, "read", lambda self, _path, **kw: real_read(self, str(ini))
    )

    put_calls = []

    def enforce_owner(params, **_):
        put_calls.append(dict(params))
        if params.get("ExpectedBucketOwner") != MOTO_ACCOUNT:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject"
            )

    real_client = boto3.client

    def client(service, *args, **kwargs):
        c = real_client(service, *args, **kwargs)
        if service == "s3":
            c.meta.events.register("provide-client-params.s3.PutObject", enforce_owner)
        return c

    module = load_script()
    aws["monkeypatch"].setattr(module.boto3, "client", client)
    module.main()
    return put_calls


def test_uploads_pass_expected_bucket_owner_from_caller_account(aws):
    put_calls = run_script(aws)

    assert len(put_calls) == 2
    assert all(c["ExpectedBucketOwner"] == MOTO_ACCOUNT for c in put_calls)
    keys = [o["Key"] for o in aws["s3"].list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert any(k.endswith("audit_events.jsonl.gz") for k in keys)
    assert any(k.endswith("report.json") for k in keys)
    assert aws["table"].scan()["Count"] == 0


def test_explicit_owner_setting_is_used(aws):
    put_calls = run_script(aws, owner_setting=MOTO_ACCOUNT)

    assert [c["ExpectedBucketOwner"] for c in put_calls] == [MOTO_ACCOUNT, MOTO_ACCOUNT]


def test_foreign_bucket_owner_aborts_before_deleting_events(aws):
    with pytest.raises(ClientError, match="AccessDenied"):
        run_script(aws, owner_setting=FOREIGN_ACCOUNT)

    assert aws["s3"].list_objects_v2(Bucket=BUCKET).get("KeyCount") == 0
    assert aws["table"].scan()["Count"] == 3


def test_malformed_owner_setting_rejected(aws):
    with pytest.raises(ValueError, match="12-digit"):
        run_script(aws, owner_setting="not-an-account")

    assert aws["table"].scan()["Count"] == 3
