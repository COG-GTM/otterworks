import configparser
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import storage_cleanup_daily as cleanup  # noqa: E402

NOW = datetime.now(tz=timezone.utc)


def _obj(key, size, age_hours):
    return {"Key": key, "Size": size, "LastModified": NOW - timedelta(hours=age_hours)}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.ini"
    path.write_text(
        "[aws]\naccess_key = x\nsecret_key = y\nregion = us-east-1\n"
        "[s3]\nfile_storage_bucket = files-bucket\nquarantine_bucket = q-bucket\n"
        "data_lake_bucket = lake-bucket\n"
    )
    monkeypatch.setattr(cleanup, "CONFIG_PATH", str(path))
    monkeypatch.delenv("ETL_ORPHAN_GRACE_HOURS", raising=False)
    return path


def _run(objects, referenced, copy_side_effect=None):
    s3 = mock.MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [{"Contents": objects}]
    if copy_side_effect is not None:
        s3.copy_object.side_effect = copy_side_effect
    table = mock.MagicMock()
    table.scan.return_value = {"Items": [{"s3_key": k} for k in referenced]}
    dynamodb = mock.MagicMock()
    dynamodb.Table.return_value = table

    with mock.patch.object(cleanup.boto3, "client", return_value=s3), \
            mock.patch.object(cleanup.boto3, "resource", return_value=dynamodb):
        rc = cleanup.main()

    report = json.loads(s3.put_object.call_args.kwargs["Body"])
    return rc, s3, table, report


def test_select_orphans_skips_objects_inside_grace_period():
    objects = [
        {"key": "files/old", "size": 1, "last_modified": NOW - timedelta(hours=48)},
        {"key": "files/new", "size": 1, "last_modified": NOW - timedelta(minutes=1)},
        {"key": "files/ref", "size": 1, "last_modified": NOW - timedelta(hours=48)},
    ]
    orphans, skipped = cleanup.select_orphans(objects, {"files/ref"}, NOW, 24)
    assert [o["key"] for o in orphans] == ["files/old"]
    assert [o["key"] for o in skipped] == ["files/new"]


def test_in_flight_upload_is_not_deleted(config_path):
    objects = [_obj("files/old-orphan", 100, 48), _obj("files/just-uploaded", 200, 0.01)]
    rc, s3, _, report = _run(objects, referenced=[])

    assert rc == 0
    deleted = [c.kwargs["Key"] for c in s3.delete_object.call_args_list]
    assert deleted == ["files/old-orphan"]
    assert report["orphans"]["orphaned_objects"] == 1
    assert report["orphans"]["skipped_recent_objects"] == 1
    assert report["orphans"]["grace_period_hours"] == 24.0


def test_scan_uses_consistent_read(config_path):
    _, _, table, _ = _run([_obj("files/a", 1, 48)], referenced=["files/a"])
    assert table.scan.call_args.kwargs["ConsistentRead"] is True


def test_grace_period_is_configurable(config_path):
    with open(config_path, "a") as f:
        f.write("[storage_cleanup]\norphan_grace_hours = 1\n")
    rc, s3, _, report = _run([_obj("files/two-hours", 5, 2)], referenced=[])
    assert rc == 0
    assert s3.delete_object.call_count == 1
    assert report["orphans"]["grace_period_hours"] == 1.0


def test_grace_period_env_override(config_path, monkeypatch):
    monkeypatch.setenv("ETL_ORPHAN_GRACE_HOURS", "72")
    _, s3, _, _ = _run([_obj("files/two-days", 5, 48)], referenced=[])
    assert s3.delete_object.call_count == 0


def test_negative_grace_period_rejected():
    config = configparser.ConfigParser()
    config.read_string("[storage_cleanup]\norphan_grace_hours = -1\n")
    with pytest.raises(ValueError):
        cleanup.get_orphan_grace_hours(config)


def test_failed_quarantine_exits_nonzero_and_reports_moved_bytes_only(config_path):
    gib = 1024 ** 3

    def copy(**kwargs):
        if kwargs["CopySource"]["Key"] == "files/fails":
            raise RuntimeError("AccessDenied")

    objects = [_obj("files/ok", gib, 48), _obj("files/fails", 3 * gib, 48)]
    rc, s3, _, report = _run(objects, referenced=[], copy_side_effect=copy)

    assert rc == 1
    assert [c.kwargs["Key"] for c in s3.delete_object.call_args_list] == ["files/ok"]
    assert report["orphans"]["orphaned_bytes"] == 4 * gib
    assert report["cleanup"]["objects_quarantined"] == 1
    assert report["cleanup"]["objects_failed"] == 1
    assert report["cleanup"]["bytes_quarantined"] == gib
    assert report["savings"]["storage_freed_gb"] == 1.0
    assert report["savings"]["estimated_monthly_savings_usd"] == 0.023
