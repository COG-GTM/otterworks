"""Unit tests for the pure transforms (no Airflow, AWS or Spark needed)."""

from datetime import datetime, timezone

import pytest

from otterworks_etl.transforms import analytics as A
from otterworks_etl.transforms import audit as AU
from otterworks_etl.transforms import search as SE
from otterworks_etl.transforms import storage as ST
from otterworks_etl.transforms import user_activity as UA

EVENTS = [
    {"eventId": "e1", "eventType": "document_created", "ownerId": "u1", "documentId": "d1",
     "timestamp": "2026-03-01T09:15:00Z"},
    {"eventId": "e1", "eventType": "document_created", "ownerId": "u1", "documentId": "d1",
     "timestamp": "2026-03-01T09:15:00Z"},  # SQS redelivery
    {"eventId": "e2", "event_type": "document_edited", "editedBy": "u2", "documentId": "d1",
     "timestamp": "2026-03-01T09:40:00Z"},
    {"eventId": "e3", "eventType": "file_uploaded", "ownerId": "u1", "fileId": "f1",
     "sizeBytes": 2048, "timestamp": "2026-03-01T14:00:00Z"},
    {"eventId": "e4", "eventType": "comment_added", "authorId": "u3",
     "timestamp": "2026-03-01T14:30:00+00:00"},
    {"eventType": "file_shared", "userId": "u2", "fileId": "f1", "timestamp": "garbage"},
    {"eventType": "", "timestamp": "2026-03-01T23:59:59Z"},
]


def test_aggregate_summary_dedupes_and_coalesces_event_type():
    agg = A.aggregate(EVENTS)
    assert agg["summary"] == {
        "active_users": 3, "active_documents": 1, "active_files": 1, "total_events": 6,
        "documents_created": 1, "documents_edited": 1, "comments_added": 1,
        "files_uploaded": 1, "files_shared": 1, "files_deleted": 0, "bytes_uploaded": 2048,
    }
    assert agg["hourly_breakdown"]["09"] == {"document_created": 1, "document_edited": 1}
    assert agg["hourly_breakdown"]["00"] == {"file_shared": 1}
    assert agg["hourly_breakdown"]["23"] == {"unknown": 1}


def test_top_users_are_deterministic_and_limited():
    agg = A.aggregate(EVENTS, top_n=2)
    assert [u["user_id"] for u in agg["top_users"]] == ["u1", "u2"]
    assert agg["top_users"][0] == {"user_id": "u1", "total": 2,
                                   "actions": {"document_created": 1, "file_uploaded": 1}}


def test_aggregate_empty():
    agg = A.aggregate([])
    assert agg["summary"]["total_events"] == 0 and agg["top_users"] == []
    assert A.build_report("2026-03-01", agg, "t")["highlights"]["peak_hour"] is None


def test_report_peak_hour():
    rep = A.build_report("2026-03-01", A.aggregate(EVENTS), "t")
    assert rep["highlights"]["peak_hour"] == {"hour": "09", "event_count": 2}
    assert rep["file_metrics"]["bytes_uploaded"] == 2048


@pytest.mark.parametrize("raw,expected", [
    ({"event_date": "2026-02-28"}, "2026-02-28"),
    ({"timestamp": "2026-02-27T23:00:00Z"}, "2026-02-27"),
    ({"timestamp": "nope"}, "2026-03-01"),
    ({}, "2026-03-01"),
])
def test_event_date(raw, expected):
    assert A.event_date(raw, "2026-03-01") == expected


def test_partition_and_upsert():
    assert A.partition_key("analytics/daily", "2026-03-01") == \
        "analytics/daily/year=2026/month=03/day=01"
    summary = A.aggregate(EVENTS)["summary"]
    params = A.upsert_params("2026-03-01", summary)
    assert params[0] == "2026-03-01" and len(params) == len(A.SUMMARY_COLUMNS) + 1
    assert "ON CONFLICT (report_date) DO UPDATE" in A.UPSERT_SQL
    assert A.UPSERT_SQL.count("%s") == len(params)


def test_audit_helpers_are_deterministic():
    assert AU.cutoff("2026-03-08T03:00:00+00:00", 90) == "2025-12-08T00:00:00Z"
    assert AU.cutoff("2026-03-08", 90) == "2025-12-08T00:00:00Z"
    keys = [{"event_id": "b", "timestamp": "1"}, {"event_id": "a", "timestamp": "2"}]
    assert AU.keys_digest(keys) == AU.keys_digest(list(reversed(keys)))
    assert AU.keys_digest(keys) != AU.keys_digest(keys[:1])
    assert AU.archive_key("audit-archive", "2026-03-08", "abc") == \
        "audit-archive/year=2026/week=2026-03-08/audit_events-abc.jsonl.gz"
    assert [len(c) for c in AU.chunks(list(range(60)), 25)] == [25, 25, 10]
    rep = AU.compliance_report("2026-03-08", "t", 90, "c", {"events_scanned": 3},
                               [{"event_count": 2}, {"event_count": 1}], "GLACIER")
    assert rep["events_archived_in_partition"] == 3


def test_storage_orphans_grace_and_guard():
    now = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    objs = [{"key": "files/a", "size": 1, "last_modified": "2026-02-01T00:00:00+00:00"},
            {"key": "files/b", "size": 2, "last_modified": "2026-02-01T00:00:00+00:00"},
            {"key": "files/c", "size": 4, "last_modified": "2026-03-01T11:00:00+00:00"}]
    orphans, recent = ST.find_orphans(objs, {"files/a"}, now, 24)
    assert [o["key"] for o in orphans] == ["files/b"]
    assert [o["key"] for o in recent] == ["files/c"]
    ST.check_guard(10, 5, 50.0)
    ST.check_guard(0, 0, 50.0)
    with pytest.raises(ST.OrphanGuardError):
        ST.check_guard(10, 6, 50.0)
    assert ST.quarantine_key("quarantined", "2026-03-01", "files/b") == \
        "quarantined/2026-03-01/files/b"
    rep = ST.build_report("2026-03-01", "t", {"total_objects": 3, "total_size_bytes": 7},
                          orphans, recent, 1, 0, "q", False, 1)
    assert rep["orphans"]["orphaned_objects"] == 1 and rep["orphans"]["orphaned_bytes"] == 2


def test_search_mapping():
    assert SE.staging_index("documents") == "documents_staging"
    assert SE.map_document({"document_id": "d1", "title": "T"})["id"] == "d1"
    f = SE.map_file({"id": "f1", "file_name": "a.pdf", "size_bytes": 9})
    assert (f["id"], f["name"], f["size"], f["type"]) == ("f1", "a.pdf", 9, "file")
    assert SE.page_items({"items": [1]}, "documents", "items") == [1]
    assert SE.page_items([1, 2]) == [1, 2]
    assert SE.page_items({"other": 1}, "documents") == []
    assert set(SE.INDEX_SETTINGS) == {"documents", "files"}


def test_user_activity_window_merge_and_latest_guard():
    assert UA.window_dates("2026-03-03", 3) == ["2026-03-03", "2026-03-02", "2026-03-01"]
    users = UA.merge_top_users([
        [{"user_id": "u1", "total": 2, "actions": {"a": 2}}],
        [{"user_id": "u1", "total": 1, "actions": {"a": 1}},
         {"user_id": "u2", "total": 3, "actions": {"b": 3}}],
    ])
    assert users[0] == {"user_id": "u1", "total_actions": 3, "active_days": 2,
                        "actions_by_type": {"a": 3}}
    rep = UA.build_report("2026-03-03", "t", 3, [{"total_events": 4, "active_users": 2},
                                                  {"total_events": 2, "active_users": 5}],
                          users, ["2026-03-01"])
    assert rep["trends"] == {"total_events": 6, "peak_active_users": 5,
                             "avg_daily_events": 3.0, "reporting_days": 2}
    assert UA.should_replace_latest(None, "2026-03-01")
    assert UA.should_replace_latest("2026-03-01", "2026-03-02")
    assert not UA.should_replace_latest("2026-03-05", "2026-03-02")
