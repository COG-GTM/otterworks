"""Reference (pure Python) implementation of the analytics_daily aggregation.

The production aggregation runs in PySpark (``etl/spark/jobs/analytics_daily_aggregate.py``);
this module defines the same semantics for small inputs and is the oracle the
PySpark parity tests compare against. Semantics follow the legacy
``etl/scripts/analytics_daily.py`` with three deliberate fixes:

* event type is coalesced per row (``eventType`` -> ``event_type`` -> ``unknown``);
  legacy only copied ``event_type`` when *no* row had ``eventType``;
* duplicate deliveries are removed by event key (SQS is at-least-once);
* top-user ties are broken by ``user_id`` so the output is deterministic.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

USER_ID_FIELDS = ("ownerId", "editedBy", "authorId", "deletedBy", "userId")
EVENT_KEY_FIELDS = ("eventId", "event_id", "id", "_source_id")

DOC_CREATED, DOC_EDITED, COMMENT_ADDED = "document_created", "document_edited", "comment_added"
FILE_UPLOADED, FILE_SHARED, FILE_DELETED = "file_uploaded", "file_shared", "file_deleted"


def _present(v: Any) -> bool:
    return v is not None and v != ""


def parse_hour(ts: Any) -> str:
    if isinstance(ts, str) and ts:
        try:
            return "%02d" % datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
        except ValueError:
            pass
    return "00"


def event_date(raw: dict, default_ds: str) -> str:
    """Calendar date (YYYY-MM-DD) an event belongs to: ``event_date``, else ``timestamp``."""
    for field in ("event_date", "timestamp"):
        val = raw.get(field)
        if isinstance(val, str) and len(val) >= 10:
            try:
                return datetime.fromisoformat(val[:10]).date().isoformat()
            except ValueError:
                continue
    return default_ds


def event_key(raw: dict) -> str | None:
    for field in EVENT_KEY_FIELDS:
        if _present(raw.get(field)):
            return str(raw[field])
    return None


def normalize(raw: dict) -> dict:
    etype = raw.get("eventType")
    if not _present(etype):
        etype = raw.get("event_type")
    user = next((str(raw[f]) for f in USER_ID_FIELDS if _present(raw.get(f))), "unknown")
    size = raw.get("sizeBytes")
    return {
        "event_key": event_key(raw),
        "event_type": str(etype) if _present(etype) else "unknown",
        "user_id": user,
        "document_id": raw.get("documentId") if _present(raw.get("documentId")) else None,
        "file_id": raw.get("fileId") if _present(raw.get("fileId")) else None,
        "size_bytes": int(size) if _present(size) else 0,
        "hour": parse_hour(raw.get("timestamp")),
    }


def dedupe(events: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for e in events:
        k = e.get("event_key")
        if k is not None:
            if k in seen:
                continue
            seen.add(k)
        out.append(e)
    return out


def aggregate(raw_events: list[dict], top_n: int = 100) -> dict:
    events = dedupe([normalize(r) for r in raw_events])
    by_type = Counter(e["event_type"] for e in events)

    user_actions: dict[str, Counter] = defaultdict(Counter)
    hourly: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        user_actions[e["user_id"]][e["event_type"]] += 1
        hourly[e["hour"]][e["event_type"]] += 1

    top_users = sorted(
        ({"user_id": u, "actions": dict(sorted(c.items())), "total": sum(c.values())}
         for u, c in user_actions.items()),
        key=lambda u: (-u["total"], u["user_id"]),
    )[:top_n]

    active_docs = {e["document_id"] for e in events
                   if e["event_type"] in (DOC_CREATED, DOC_EDITED) and e["document_id"]}
    active_files = {e["file_id"] for e in events
                    if e["event_type"] in (FILE_UPLOADED, FILE_SHARED, FILE_DELETED) and e["file_id"]}
    bytes_uploaded = sum(e["size_bytes"] for e in events if e["event_type"] == FILE_UPLOADED)

    summary = {
        "active_users": len({e["user_id"] for e in events} - {"unknown"}),
        "active_documents": len(active_docs),
        "active_files": len(active_files),
        "total_events": len(events),
        "documents_created": by_type[DOC_CREATED],
        "documents_edited": by_type[DOC_EDITED],
        "comments_added": by_type[COMMENT_ADDED],
        "files_uploaded": by_type[FILE_UPLOADED],
        "files_shared": by_type[FILE_SHARED],
        "files_deleted": by_type[FILE_DELETED],
        "bytes_uploaded": bytes_uploaded,
    }
    return {
        "summary": summary,
        "hourly_breakdown": {h: dict(sorted(c.items())) for h, c in sorted(hourly.items())},
        "top_users": top_users,
    }


def build_report(ds: str, agg: dict, generated_at: str) -> dict:
    summary, hourly, top = agg["summary"], agg["hourly_breakdown"], agg["top_users"]
    peak_hour = None
    if hourly:
        h, counts = max(hourly.items(), key=lambda kv: (sum(kv[1].values()), -int(kv[0])))
        peak_hour = {"hour": h, "event_count": sum(counts.values())}
    return {
        "report_type": "daily_analytics",
        "report_date": ds,
        "generated_at": generated_at,
        "summary": summary,
        "highlights": {"peak_hour": peak_hour,
                       "most_active_users": [u["user_id"] for u in top[:5]]},
        "document_metrics": {"created": summary["documents_created"],
                             "edited": summary["documents_edited"],
                             "comments": summary["comments_added"]},
        "file_metrics": {"uploaded": summary["files_uploaded"], "shared": summary["files_shared"],
                         "deleted": summary["files_deleted"],
                         "bytes_uploaded": summary["bytes_uploaded"]},
    }


def partition_key(prefix: str, ds: str) -> str:
    """Legacy-compatible Hive partition: ``<prefix>/year=YYYY/month=MM/day=DD``."""
    return f"{prefix}/year={ds[:4]}/month={ds[5:7]}/day={ds[8:10]}"


SUMMARY_COLUMNS = (
    "active_users", "active_documents", "active_files", "total_events", "documents_created",
    "documents_edited", "comments_added", "files_uploaded", "files_shared", "files_deleted",
    "bytes_uploaded",
)

UPSERT_SQL = """
INSERT INTO analytics_daily_summary (report_date, {cols}, updated_at)
VALUES (%s, {placeholders}, NOW())
ON CONFLICT (report_date) DO UPDATE SET {updates}, updated_at = NOW();
""".format(
    cols=", ".join(SUMMARY_COLUMNS),
    placeholders=", ".join(["%s"] * len(SUMMARY_COLUMNS)),
    updates=", ".join(f"{c} = EXCLUDED.{c}" for c in SUMMARY_COLUMNS),
)


def upsert_params(ds: str, summary: dict) -> tuple:
    return (ds, *(summary[c] for c in SUMMARY_COLUMNS))
