"""PySpark job in local mode: parity with the pure-Python reference + output layout."""

import gzip
import json
import random

import analytics_daily_aggregate as job
from otterworks_etl.transforms import analytics as ref

TYPES = ["document_created", "document_edited", "comment_added", "file_uploaded",
         "file_shared", "file_deleted", "login", ""]
USER_FIELDS = ["ownerId", "editedBy", "authorId", "deletedBy", "userId", None]


def synthetic_events(n=600, seed=7):
    rnd = random.Random(seed)
    events = []
    for i in range(n):
        e = {"timestamp": f"2026-03-01T{rnd.randrange(24):02d}:{rnd.randrange(60):02d}:00Z"}
        if rnd.random() < 0.9:
            e["eventId"] = f"e{rnd.randrange(n)}"  # ~collisions simulate redelivery
        t = rnd.choice(TYPES)
        e["eventType" if rnd.random() < 0.7 else "event_type"] = t
        uf = rnd.choice(USER_FIELDS)
        if uf:
            e[uf] = f"u{rnd.randrange(40)}"
        if t.startswith("document"):
            e["documentId"] = f"d{rnd.randrange(30)}"
        if t.startswith("file"):
            e["fileId"] = f"f{rnd.randrange(30)}"
            e["sizeBytes"] = rnd.randrange(1, 10_000)
        if rnd.random() < 0.05:
            e["timestamp"] = "not-a-timestamp"
        events.append(e)
    return events


def dedupe_identical(events):
    """Reference keeps the first duplicate, Spark an arbitrary one: make duplicates identical."""
    first = {}
    for e in events:
        if "eventId" in e:
            first.setdefault(e["eventId"], e)
    return [first.get(e.get("eventId"), e) if "eventId" in e else e for e in events]


def write_jsonl_gz(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress("".join(json.dumps(e) + "\n" for e in events).encode()))


def test_parity_with_reference_implementation(spark, tmp_path):
    events = dedupe_identical(synthetic_events())
    write_jsonl_gz(tmp_path / "raw" / "sqs.jsonl.gz", events[:300])
    write_jsonl_gz(tmp_path / "raw" / "dynamodb.jsonl.gz", events[300:])
    got = job.run(spark, "2026-03-01", str(tmp_path / "raw"), str(tmp_path / "out"), 25)
    want = ref.aggregate(events, top_n=25)
    assert got["summary"] == want["summary"]
    assert got["hourly_breakdown"] == want["hourly_breakdown"]
    assert got["top_users"] == want["top_users"]


def test_outputs_overwrite_on_rerun(spark, tmp_path):
    raw = tmp_path / "raw" / "a.jsonl.gz"
    write_jsonl_gz(raw, [{"eventId": "1", "eventType": "file_uploaded", "ownerId": "u",
                          "fileId": "f", "sizeBytes": 5, "timestamp": "2026-03-01T01:00:00Z"}])
    out = str(tmp_path / "out")
    job.run(spark, "2026-03-01", str(raw.parent), out, 10)
    agg = job.run(spark, "2026-03-01", str(raw.parent), out, 10)  # idempotent re-run
    assert agg["summary"]["total_events"] == 1 and agg["summary"]["bytes_uploaded"] == 5
    parts = list((tmp_path / "out" / "aggregates").glob("part-*"))
    assert len(parts) == 1
    assert json.loads(parts[0].read_text().splitlines()[0]) == agg
    events = spark.read.parquet(f"{out}/events")
    assert events.count() == 1
    assert events.first()["ds"] == "2026-03-01"


def test_empty_and_corrupt_input(spark, tmp_path):
    empty = job.run(spark, "2026-03-01", str(tmp_path / "missing"), str(tmp_path / "o1"), 10)
    assert empty == ref.aggregate([])
    bad = tmp_path / "raw" / "bad.jsonl"
    bad.parent.mkdir()
    bad.write_text('{"eventId": "1", "eventType": "comment_added", "authorId": "u"}\nnot json\n')
    agg = job.run(spark, "2026-03-01", str(bad.parent), str(tmp_path / "o2"), 10)
    assert agg["summary"]["total_events"] == 1 and agg["summary"]["comments_added"] == 1


def test_cli_entrypoint(tmp_path, monkeypatch, spark):
    write_jsonl_gz(tmp_path / "raw" / "a.jsonl.gz",
                   [{"eventId": "1", "eventType": "document_created", "ownerId": "u",
                     "documentId": "d"}])
    monkeypatch.setattr(spark, "stop", lambda: None)  # keep the shared session alive
    rc = job.main(["--ds", "2026-03-01", "--input", str(tmp_path / "raw"),
                   "--output", str(tmp_path / "out"), "--top-n", "5"])
    assert rc == 0
    assert list((tmp_path / "out" / "aggregates").glob("part-*"))
