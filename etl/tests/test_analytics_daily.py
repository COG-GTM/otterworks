import gzip
import json
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

for _name in ("boto3", "psycopg2"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analytics_daily as ad  # noqa: E402


class FakeSQS:
    def __init__(self, batches):
        self.batches = list(batches)
        self.deleted = []

    def receive_message(self, **_):
        if not self.batches:
            return {}
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return {"Messages": batch}

    def delete_message_batch(self, QueueUrl, Entries):
        self.deleted.append(Entries)


class FakeTable:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        page = kwargs.get("ExclusiveStartKey", {}).get("p", 0)
        response = {"Items": self.pages[page]}
        if page + 1 < len(self.pages):
            response["LastEvaluatedKey"] = {"p": page + 1}
        return response


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body


def _msg(i, body):
    return {"MessageId": "m%d" % i, "ReceiptHandle": "r%d" % i, "Body": body}


def test_extract_sqs_skips_malformed_and_retries_transient_errors():
    sqs = FakeSQS([
        [_msg(1, '{"eventType": "a"}'), _msg(2, "{bad"), {"MessageId": "m3"}],
        RuntimeError("throttled"),
        [_msg(4, '{"eventType": "b"}')],
    ])
    events = ad.extract_sqs_events(sqs)
    assert events == [{"eventType": "a"}, {"eventType": "b"}]
    assert sqs.deleted == [
        [{"Id": "m1", "ReceiptHandle": "r1"}],
        [{"Id": "m4", "ReceiptHandle": "r4"}],
    ]


def test_extract_sqs_gives_up_after_three_consecutive_errors():
    sqs = FakeSQS([RuntimeError()] * 3 + [[_msg(1, "{}")]])
    assert ad.extract_sqs_events(sqs) == []
    assert len(sqs.batches) == 1


def test_extract_sqs_respects_max_messages():
    sqs = FakeSQS([[_msg(i, "{}") for i in range(10)]] * 5)
    assert len(ad.extract_sqs_events(sqs, max_messages=20)) == 20


def test_extract_dynamo_paginates_and_converts_decimals():
    table = FakeTable([[{"n": Decimal("3"), "f": Decimal("2.5")}], [{"s": "x"}]])
    events = ad.extract_dynamo_events(table, "2026-11-12")
    assert events == [{"n": 3, "f": 2.5}, {"s": "x"}]
    assert isinstance(events[0]["n"], int)
    assert table.calls[1]["ExclusiveStartKey"] == {"p": 1}


@pytest.mark.parametrize("ts, hour", [
    ("2026-11-12T03:15:00Z", "03"),
    ("2026-11-12T23:00:00+00:00", "23"),
    ("garbage", "00"),
    (12345, "00"),
    (None, "00"),
])
def test_parse_hour(ts, hour):
    assert ad.parse_hour(ts) == hour


def test_build_events_frame_normalizes_fields():
    df = ad.build_events_frame([
        {"event_type": "document_created", "userId": "", "ownerId": "u1", "timestamp": "2026-11-12T05:00:00Z"},
        {"event_type": "file_shared", "editedBy": "u2", "userId": "u3"},
        {"event_type": "comment_added"},
    ])
    assert list(df["eventType"]) == ["document_created", "file_shared", "comment_added"]
    assert list(df["resolved_user_id"]) == ["u1", "u2", "unknown"]
    assert list(df["hour"]) == ["05", "00", "00"]


def test_aggregate_metrics():
    events = [
        {"eventType": "document_created", "ownerId": "u1", "documentId": "d1", "timestamp": "2026-11-12T01:00:00Z"},
        {"eventType": "document_edited", "editedBy": "u1", "documentId": "d1", "timestamp": "2026-11-12T01:30:00Z"},
        {"eventType": "document_edited", "editedBy": "u2", "documentId": "d2", "timestamp": "2026-11-12T02:00:00Z"},
        {"eventType": "comment_added", "authorId": "u2", "documentId": "d3"},
        {"eventType": "file_uploaded", "userId": "u1", "fileId": "f1", "sizeBytes": 100},
        {"eventType": "file_uploaded", "userId": "u3", "fileId": "f2"},
        {"eventType": "file_shared", "userId": "u3", "fileId": "f2"},
        {"eventType": "file_deleted", "deletedBy": "u1", "fileId": "f3"},
        {"eventType": "page_view"},
    ]
    result = ad.aggregate(ad.build_events_frame(events), len(events))
    assert result["summary"] == {
        "active_users": 3,
        "active_documents": 2,
        "active_files": 3,
        "total_events": 9,
        "documents_created": 1,
        "documents_edited": 2,
        "comments_added": 1,
        "files_uploaded": 2,
        "files_shared": 1,
        "files_deleted": 1,
        "bytes_uploaded": 100,
    }
    assert result["document_metrics"] == {"created": 1, "edited": 2, "comments": 1}
    assert result["file_metrics"] == {"uploaded": 2, "shared": 1, "deleted": 1, "bytes_uploaded": 100}
    assert result["user_summaries"][0] == {
        "user_id": "u1",
        "actions": {"document_created": 1, "document_edited": 1, "file_uploaded": 1, "file_deleted": 1},
        "total": 4,
    }
    assert list(result["hourly_breakdown"]) == ["00", "01", "02"]
    assert result["hourly_breakdown"]["01"] == {"document_created": 1, "document_edited": 1}


def test_top_users_limited_to_100():
    events = [{"eventType": "x", "userId": "u%d" % i} for i in range(150)]
    assert len(ad.top_users(ad.build_events_frame(events))) == 100


def test_load_to_data_lake_and_report():
    events = [{"eventType": "file_uploaded", "userId": "u1", "fileId": "f1", "timestamp": "2026-11-12T07:00:00Z"}]
    result = ad.aggregate(ad.build_events_frame(events), 1)
    s3 = FakeS3()
    ad.load_to_data_lake(s3, "lake", "analytics", "2026-11-12", result)
    prefix = "analytics/year=2026/month=11/day=12"
    assert sorted(k for _, k in s3.objects) == sorted(
        "%s/%s" % (prefix, f) for f in ("summary.json.gz", "hourly_breakdown.json.gz", "top_users.jsonl.gz")
    )
    summary = json.loads(gzip.decompress(s3.objects[("lake", prefix + "/summary.json.gz")]))
    assert summary == result["summary"]
    users = gzip.decompress(s3.objects[("lake", prefix + "/top_users.jsonl.gz")]).decode().splitlines()
    assert [json.loads(u)["user_id"] for u in users] == ["u1"]

    report = ad.build_report("2026-11-12", result)
    assert report["highlights"] == {"peak_hour": {"hour": "07", "event_count": 1}, "most_active_users": ["u1"]}
    ad.publish_report(s3, "lake", "2026-11-12", report)
    assert ("lake", "reports/analytics/daily/2026-11-12/report.json") in s3.objects


def test_upsert_rolls_back_and_continues_on_failure(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append(("execute", params))
            raise RuntimeError("db down")

        def close(self):
            calls.append(("cursor_close",))

    class Conn:
        def cursor(self):
            return Cursor()

        def commit(self):
            calls.append(("commit",))

        def rollback(self):
            calls.append(("rollback",))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(ad.psycopg2, "connect", lambda **_: Conn(), raising=False)
    cfg = {"db_host": "h", "db_port": 5432, "db_name": "d", "db_user": "u", "db_password": "p"}
    summary = {col: i for i, col in enumerate(ad.SUMMARY_COLUMNS)}
    ad.upsert_daily_summary(cfg, "2026-11-12", summary)
    assert calls == [
        ("execute", ("2026-11-12", *range(len(ad.SUMMARY_COLUMNS)))),
        ("rollback",),
        ("cursor_close",),
        ("close",),
    ]
