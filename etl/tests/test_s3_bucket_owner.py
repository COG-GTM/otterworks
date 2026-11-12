import ast
import configparser
import sys
from pathlib import Path
from unittest import mock

import boto3
import pytest
from botocore.stub import Stubber

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from s3_ownership import resolve_expected_bucket_owner

S3_BUCKET_CALLS = {
    "put_object", "get_object", "delete_object", "copy_object", "head_object",
    "list_objects", "list_objects_v2", "paginate",
}


def _config(owner=None):
    config = configparser.ConfigParser()
    config.add_section("s3")
    if owner is not None:
        config.set("s3", "expected_bucket_owner", owner)
    return config


def _s3_calls(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in S3_BUCKET_CALLS
            and any(kw.arg == "Bucket" for kw in node.keywords)
        ):
            yield node


@pytest.mark.parametrize("script", sorted(p.name for p in SCRIPTS.glob("*.py")))
def test_every_s3_bucket_call_verifies_ownership(script):
    for call in _s3_calls(SCRIPTS / script):
        kwargs = {kw.arg for kw in call.keywords}
        where = f"{script}:{call.lineno} {call.func.attr}"
        assert "ExpectedBucketOwner" in kwargs, where
        if call.func.attr == "copy_object":
            assert "ExpectedSourceBucketOwner" in kwargs, where


def test_analytics_daily_uploads_are_covered():
    assert len(list(_s3_calls(SCRIPTS / "analytics_daily.py"))) == 4


def test_env_var_takes_precedence(monkeypatch):
    monkeypatch.setenv("ETL_EXPECTED_BUCKET_OWNER", "111122223333")
    assert resolve_expected_bucket_owner(_config("444455556666"), "a", "s", "us-east-1") == "111122223333"


def test_config_value_used_without_env(monkeypatch):
    monkeypatch.delenv("ETL_EXPECTED_BUCKET_OWNER", raising=False)
    assert resolve_expected_bucket_owner(_config(" 444455556666 "), "a", "s", "us-east-1") == "444455556666"


def test_falls_back_to_caller_account(monkeypatch):
    monkeypatch.delenv("ETL_EXPECTED_BUCKET_OWNER", raising=False)
    sts = boto3.client("sts", region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="s")
    with Stubber(sts) as stub, mock.patch("s3_ownership.boto3.client", return_value=sts):
        stub.add_response(
            "get_caller_identity",
            {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/etl", "UserId": "AIDAEXAMPLE"},
        )
        assert resolve_expected_bucket_owner(_config(""), "a", "s", "us-east-1") == "123456789012"
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("bad", ["12345", "12345678901a", "arn:aws:iam::123456789012:root"])
def test_rejects_non_account_ids(monkeypatch, bad):
    monkeypatch.setenv("ETL_EXPECTED_BUCKET_OWNER", bad)
    with pytest.raises(ValueError):
        resolve_expected_bucket_owner(_config(), "a", "s", "us-east-1")
