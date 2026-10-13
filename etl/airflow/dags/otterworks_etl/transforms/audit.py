"""Pure helpers for the weekly audit archive."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta


def cutoff(as_of: str, retention_days: int) -> str:
    """ISO cutoff for ``as_of`` (a date or datetime string); older events are archived."""
    d = date.fromisoformat(as_of[:10]) - timedelta(days=retention_days)
    return f"{d.isoformat()}T00:00:00Z"


def item_key(item: dict, key_attrs: list[str]) -> dict:
    return {a: item[a] for a in key_attrs}


def keys_digest(keys: list[dict]) -> str:
    """Stable digest of an event-key set: identical input -> identical archive object key."""
    canon = sorted(json.dumps(k, sort_keys=True, default=str) for k in keys)
    return hashlib.sha256("\n".join(canon).encode()).hexdigest()[:16]


def archive_key(prefix: str, ds: str, digest: str) -> str:
    return f"{prefix}/year={ds[:4]}/week={ds}/audit_events-{digest}.jsonl.gz"


def chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def compliance_report(ds: str, generated_at: str, retention_days: int, cutoff_ts: str,
                      run: dict, parts: list[dict], storage_class: str) -> dict:
    return {
        "report_type": "audit_archive_compliance",
        "execution_date": ds,
        "generated_at": generated_at,
        "retention_policy": {"retention_days": retention_days, "cutoff_date": cutoff_ts},
        "results": {
            "events_scanned": run.get("events_scanned", 0),
            "events_archived": run.get("events_archived", 0),
            "events_deleted_from_source": run.get("events_deleted", 0),
            "archive_location": run.get("archive_location"),
            "archive_storage_class": storage_class,
            "compressed_size_bytes": run.get("compressed_size_bytes", 0),
        },
        # Every archive part written for this partition, across re-runs/backfills.
        "archive_parts": parts,
        "events_archived_in_partition": sum(int(p.get("event_count", 0)) for p in parts),
    }
