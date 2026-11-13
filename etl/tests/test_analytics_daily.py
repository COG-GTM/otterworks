import gzip
import json
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analytics_daily as ad  # noqa: E402

DS = "2026-11-13"


class FakeSQS:
    def __init__(self, batches):
        self.batches = list(batches)
        self.deleted = []

    def receive_message(self, **_):
        if not self.batches:
            return {}
        batch = self.batches.pop(0)
        if isinstance(batch, BaseException):
            raise batch
        return {"Messages": batch}

    def delete_message_batch(self, QueueUrl, Entries):
        self.deleted.append(Entries)


class FakeTable:
    def __init__(self, pages):
        self.pages = pages

    def scan(self, **kwargs):
        page = kwargs.get("ExclusiveStartKey", {}).get("p", 0)
        response = {"Items": [dict(i) for i in self.pages[page]]}
        if page + 1 < len(self.pages):
            response["LastEvaluatedKey"] = {"p": page + 1}
        return response


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body


def msg(i, body):
    return {"MessageId": "m%d" % i, "ReceiptHandle": "r%d" % i, "Body": body}


def client_error():
    return ClientError({"Error": {"Code": "Throttling", "Message": "slow down"}}, "ReceiveMessage")


def test_parse_sqs_messages_skips_malformed():
    events, entries = ad.parse_sqs_messages([
        msg(1, json.dumps({"eventType": "file_uploaded"})),
        msg(2, "not json"),
        {"MessageId": "m3", "ReceiptHandle": "r3"},
        msg(4, None),
    ])
    assert events == [{"eventType": "file_uploaded"}]
    assert entries == [{"Id": "m1", "ReceiptHandle": "r1"}]


def test_extract_sqs_recovers_from_transient_aws_errors():
    sqs = FakeSQS([client_error(), [msg(1, '{"a": 1}')], EndpointConnectionError(endpoint_url="x"), []])
    assert ad.extract_sqs_events(sqs) == [{"a": 1}]
    assert sqs.deleted == [[{"Id": "m1", "ReceiptHandle": "r1"}]]


def test_extract_sqs_gives_up_after_three_consecutive_errors():
    sqs = FakeSQS([client_error(), client_error(), client_error(), [msg(1, "{}")]])
    assert ad.extract_sqs_events(sqs) == []
    assert len(sqs.batches) == 1


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(2), RuntimeError("bug")])
def test_extract_sqs_does_not_swallow_unexpected_exceptions(exc):
    with pytest.raises(type(exc)):
        ad.extract_sqs_events(FakeSQS([exc]))


def test_parse_hour():
    assert ad.parse_hour("2026-11-13T07:15:00Z") == "07"
    assert ad.parse_hour("garbage") == "00"
    assert ad.parse_hour(None) == "00"
    assert ad.parse_hour(1234) == "00"


def test_extract_dynamo_paginates_and_normalizes_decimals():
    table = FakeTable([[{"sizeBytes": Decimal("10")}], [{"ratio": Decimal("0.5")}]])
    assert ad.extract_dynamo_events(table, DS) == [{"sizeBytes": 10}, {"ratio": 0.5}]


EVENTS = [
    {"eventType": "document_created", "ownerId": "u1", "documentId": "d1", "timestamp": "2026-11-13T09:00:00Z"},
    {"eventType": "document_edited", "editedBy": "u2", "documentId": "d2", "timestamp": "2026-11-13T09:30:00Z"},
    {"eventType": "comment_added", "authorId": "u2", "timestamp": "2026-11-13T10:00:00Z"},
    {"event_type": "file_uploaded", "userId": "u1", "fileId": "f1", "sizeBytes": 100, "timestamp": "bad"},
    {"event_type": "file_shared", "userId": "u3", "fileId": "f1"},
    {"event_type": "file_deleted", "deletedBy": "u1", "fileId": "f2", "timestamp": "2026-11-13T23:59:00+00:00"},
    {"event_type": "file_uploaded", "fileId": "f3", "sizeBytes": None},
]


def test_aggregate():
    events = [dict(e) for e in EVENTS]
    for e in events:
        if "event_type" in e:
            e["eventType"] = e.pop("event_type")
    result = ad.aggregate(ad.build_dataframe(events), len(events))
    assert result["summary"] == {
        "active_users": 3,
        "active_documents": 2,
        "active_files": 3,
        "total_events": 7,
        "documents_created": 1,
        "documents_edited": 1,
        "comments_added": 1,
        "files_uploaded": 2,
        "files_shared": 1,
        "files_deleted": 1,
        "bytes_uploaded": 100,
    }
    assert list(result["hourly_breakdown"]) == ["00", "09", "10", "23"]
    assert result["user_summaries"][0] == {
        "user_id": "u1",
        "actions": {"document_created": 1, "file_uploaded": 1, "file_deleted": 1},
        "total": 3,
    }


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params):
        if self.conn.fail:
            raise psycopg2.OperationalError("db down")
        self.conn.params = params

    def close(self):
        self.conn.cursor_closed = True


class FakeConn:
    def __init__(self, fail=False):
        self.fail = fail
        self.params = None
        self.committed = self.rolled_back = self.closed = self.cursor_closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


CFG = {
    "aws_access_key": "k", "aws_secret_key": "s", "aws_region": "us-east-1",
    "db_host": "db", "db_port": 5432, "db_name": "otter", "db_user": "u", "db_password": "p",
    "data_lake_bucket": "lake", "analytics_prefix": "analytics",
}


def run_main(monkeypatch, sqs, table, conn):
    s3 = FakeS3()
    clients = {"sqs": sqs, "s3": s3}

    class Resource:
        def Table(self, name):
            assert name == ad.DYNAMODB_TABLE_NAME
            return table

    class FixedDatetime(ad.datetime):
        @classmethod
        def now(cls, tz=None):
            return ad.datetime(2026, 11, 13, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(ad, "load_config", lambda: dict(CFG))
    monkeypatch.setattr(ad.boto3, "client", lambda name, **_: clients[name])
    monkeypatch.setattr(ad.boto3, "resource", lambda name, **_: Resource())
    monkeypatch.setattr(ad.psycopg2, "connect", lambda **_: conn)
    monkeypatch.setattr(ad, "datetime", FixedDatetime)
    ad.main()
    return s3


def test_main_end_to_end(monkeypatch):
    sqs = FakeSQS([[msg(i, json.dumps(e)) for i, e in enumerate(EVENTS[:4])], []])
    table = FakeTable([EVENTS[4:]])
    conn = FakeConn()
    s3 = run_main(monkeypatch, sqs, table, conn)

    prefix = "analytics/year=2026/month=11/day=13"
    summary = json.loads(gzip.decompress(s3.objects[("lake", prefix + "/summary.json.gz")]))
    assert summary["total_events"] == 7
    assert ("lake", prefix + "/hourly_breakdown.json.gz") in s3.objects
    users = gzip.decompress(s3.objects[("lake", prefix + "/top_users.jsonl.gz")]).decode().splitlines()
    assert json.loads(users[0])["user_id"] == "u1"
    report = json.loads(s3.objects[("lake", "reports/analytics/daily/%s/report.json" % DS)])
    assert report["highlights"]["peak_hour"] == {"hour": "00", "event_count": 3}
    assert conn.params == (DS,) + tuple(summary[c] for c in ad.SUMMARY_COLUMNS)
    assert conn.committed and conn.closed and conn.cursor_closed


def test_main_still_writes_report_when_postgres_fails(monkeypatch):
    conn = FakeConn(fail=True)
    s3 = run_main(monkeypatch, FakeSQS([[msg(1, json.dumps(EVENTS[0]))]]), FakeTable([[]]), conn)
    assert conn.rolled_back and conn.closed
    assert ("lake", "reports/analytics/daily/%s/report.json" % DS) in s3.objects


def test_main_exits_cleanly_with_no_events(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, FakeSQS([]), FakeTable([[]]), FakeConn())
    assert exc.value.code == 0
