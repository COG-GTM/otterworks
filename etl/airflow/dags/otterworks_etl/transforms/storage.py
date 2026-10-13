"""Pure helpers for the daily orphaned-object cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta


class OrphanGuardError(RuntimeError):
    """Raised when the orphan ratio is implausibly high (e.g. empty metadata scan)."""


def find_orphans(objects: list[dict], referenced: set[str], now: datetime,
                 grace_hours: float) -> tuple[list[dict], list[dict]]:
    """Split unreferenced objects into (orphans, too_recent_to_judge)."""
    threshold = now - timedelta(hours=grace_hours)
    orphans, recent = [], []
    for obj in objects:
        if obj["key"] in referenced:
            continue
        modified = datetime.fromisoformat(obj["last_modified"])
        (recent if modified > threshold else orphans).append(obj)
    return orphans, recent


def check_guard(total: int, orphaned: int, max_pct: float) -> None:
    if total and orphaned / total * 100 > max_pct:
        raise OrphanGuardError(
            f"{orphaned}/{total} objects ({orphaned / total:.0%}) look orphaned, above the "
            f"{max_pct}% safety limit; refusing to quarantine. Check the metadata scan, or raise "
            f"storage_cleanup_max_orphan_pct in the otterworks_etl Variable."
        )


def quarantine_key(prefix: str, ds: str, source_key: str) -> str:
    return f"{prefix}/{ds}/{source_key}"


def build_report(ds: str, generated_at: str, inventory: dict, orphans: list[dict],
                 recent: list[dict], moved: int, failed: int, quarantine_bucket: str,
                 dry_run: bool, quarantined_total: int) -> dict:
    total_objects, total_bytes = inventory["total_objects"], inventory["total_size_bytes"]
    orphaned_bytes = sum(o["size"] for o in orphans)
    gb = orphaned_bytes / (1024 ** 3)
    return {
        "report_type": "storage_cleanup",
        "report_date": ds,
        "generated_at": generated_at,
        "dry_run": dry_run,
        "inventory": {"total_objects": total_objects, "total_size_bytes": total_bytes,
                      "total_size_gb": round(total_bytes / (1024 ** 3), 4)},
        "orphans": {
            "orphaned_objects": len(orphans),
            "orphaned_bytes": orphaned_bytes,
            "orphaned_size_gb": round(gb, 4),
            "orphan_percentage": round(len(orphans) / total_objects * 100 if total_objects else 0, 2),
            "skipped_within_grace_period": len(recent),
        },
        "cleanup": {"objects_quarantined": moved, "objects_failed": failed,
                    "quarantine_bucket": quarantine_bucket,
                    "objects_in_quarantine_partition": quarantined_total},
        "savings": {"storage_freed_gb": round(gb, 4),
                    "estimated_monthly_savings_usd": round(gb * 0.023, 4)},
    }
