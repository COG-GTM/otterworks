import ast
import configparser
import gzip
import io
import json
import sys
import types
from pathlib import Path

import boto3
import botocore.awsrequest
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s3_ownership

OWNER = "111122223333"
S3_OPS = {"get_object", "put_object", "delete_object", "copy_object", "paginate"}


def _config(owner=None):
    cfg = configparser.ConfigParser()
    cfg["s3"] = {"data_lake_bucket": "lake"}
    if owner is not None:
        cfg["s3"]["expected_bucket_owner"] = owner
    return cfg


@pytest.fixture(autouse=True)
def _no_env_owner(monkeypatch):
    monkeypatch.delenv(s3_ownership.ENV_VAR, raising=False)


def test_owner_from_config():
    assert s3_ownership.expected_bucket_owner(_config(f" {OWNER} ")) == OWNER


def test_env_overrides_config(monkeypatch):
    monkeypatch.setenv(s3_ownership.ENV_VAR, "444455556666")
    assert s3_ownership.expected_bucket_owner(_config(OWNER)) == "444455556666"


@pytest.mark.parametrize("owner", [None, "", "1234", "12345678901a", "arn:aws:iam::111122223333:root"])
def test_missing_or_malformed_owner_is_rejected(owner):
    with pytest.raises(ValueError, match="12-digit AWS account ID"):
        s3_ownership.expected_bucket_owner(_config(owner))


@pytest.mark.parametrize("script", sorted(p.name for p in SCRIPTS.glob("*_daily.py")) + sorted(p.name for p in SCRIPTS.glob("*_weekly.py")))
def test_every_s3_call_verifies_bucket_owner(script):
    tree = ast.parse((SCRIPTS / script).read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        kwargs = {k.arg: k.value for k in node.keywords}
        if node.func.attr not in S3_OPS or "Bucket" not in kwargs:
            continue
        owner = kwargs.get("ExpectedBucketOwner")
        assert isinstance(owner, ast.Name) and owner.id == "bucket_owner", (script, node.lineno)
        if node.func.attr == "copy_object":
            src = kwargs.get("ExpectedSourceBucketOwner")
            assert isinstance(src, ast.Name) and src.id == "bucket_owner", (script, node.lineno)


class _Raw(io.BytesIO):
    def stream(self, **_):
        yield self.getvalue()


def _write_config(tmp_path, owner):
    path = tmp_path / "config.ini"
    path.write_text(
        "[aws]\naccess_key = AKIDTEST\nsecret_key = secret\nregion = us-east-1\n"
        "[database]\nhost = db\nport = 5432\ndatabase = d\nuser = u\npassword = p\n"
        "[s3]\ndata_lake_bucket = otterworks-data-lake\nexpected_bucket_owner = {owner}\n"
    )
    return path


def _load_user_activity(monkeypatch, tmp_path, owner):
    cfg_path = _write_config(tmp_path, owner)
    real_read = configparser.ConfigParser.read
    monkeypatch.setattr(configparser.ConfigParser, "read", lambda self, _p, **kw: real_read(self, cfg_path))

    cursor = types.SimpleNamespace(execute=lambda *a, **k: None, fetchall=list, close=lambda: None)
    conn = types.SimpleNamespace(cursor=lambda: cursor, close=lambda: None)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda **kw: conn))
    sys.modules.pop("user_activity_daily", None)
    import user_activity_daily
    return user_activity_daily


def test_user_activity_sends_expected_bucket_owner_header(monkeypatch, tmp_path):
    module = _load_user_activity(monkeypatch, tmp_path, OWNER)
    sent = []
    real_client = boto3.client

    def client(*args, **kwargs):
        c = real_client(*args, **kwargs)

        def capture(request, **_):
            sent.append((request.method, request.url, request.headers.get("x-amz-expected-bucket-owner")))
            if request.method == "GET":
                body = gzip.compress(json.dumps({"user_id": "u1", "total": 3, "actions": {"edit": 3}}).encode())
                return botocore.awsrequest.AWSResponse(request.url, 200, {}, _Raw(body))
            return botocore.awsrequest.AWSResponse(request.url, 200, {}, _Raw(b""))

        c.meta.events.register("before-send.s3", capture)
        return c

    monkeypatch.setattr(module.boto3, "client", client)
    module.main()

    gets = [s for s in sent if s[0] == "GET"]
    puts = [s for s in sent if s[0] == "PUT"]
    assert len(gets) == 30 and len(puts) == 3
    assert any(url.endswith("/reports/user-activity/latest/activity_report.json") for _, url, _ in puts)
    assert {header for _, _, header in sent} == {OWNER.encode()}


def test_user_activity_refuses_to_run_without_owner(monkeypatch, tmp_path):
    module = _load_user_activity(monkeypatch, tmp_path, "")
    monkeypatch.setattr(module.boto3, "client", lambda *a, **k: pytest.fail("S3 client created without bucket owner"))
    with pytest.raises(ValueError, match="12-digit AWS account ID"):
        module.main()
