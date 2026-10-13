"""Pure helpers for the daily user activity report."""

from __future__ import annotations

from datetime import date, timedelta


def window_dates(ds: str, lookback_days: int) -> list[str]:
    """``ds`` and the ``lookback_days - 1`` days before it (legacy window), newest first."""
    d = date.fromisoformat(ds)
    return [(d - timedelta(days=i)).isoformat() for i in range(lookback_days)]


def merge_top_users(daily_rows: list[list[dict]]) -> list[dict]:
    totals: dict[str, dict] = {}
    for rows in daily_rows:
        for row in rows:
            uid = row.get("user_id", "unknown")
            t = totals.setdefault(uid, {"user_id": uid, "total_actions": 0, "active_days": 0,
                                        "actions_by_type": {}})
            t["total_actions"] += int(row.get("total", 0))
            t["active_days"] += 1
            for action, n in (row.get("actions") or {}).items():
                t["actions_by_type"][action] = t["actions_by_type"].get(action, 0) + int(n)
    return sorted(totals.values(), key=lambda u: (-u["total_actions"], u["user_id"]))


def build_report(ds: str, generated_at: str, lookback_days: int, daily_summaries: list[dict],
                 users: list[dict], missing_days: list[str]) -> dict:
    total_events = sum(int(d.get("total_events") or 0) for d in daily_summaries)
    peak = max((int(d.get("active_users") or 0) for d in daily_summaries), default=0)
    avg = total_events / len(daily_summaries) if daily_summaries else 0
    return {
        "report_type": "user_activity",
        "report_date": ds,
        "generated_at": generated_at,
        "lookback_days": lookback_days,
        "trends": {"total_events": total_events, "peak_active_users": peak,
                   "avg_daily_events": round(avg, 2), "reporting_days": len(daily_summaries)},
        "daily_summaries": daily_summaries,
        "user_summaries": users[:500],
        "top_users": users[:20],
        "missing_top_user_days": missing_days,
    }


def should_replace_latest(existing_report_date: str | None, ds: str) -> bool:
    """A backfill of an older date must not overwrite a newer ``latest`` pointer."""
    return existing_report_date is None or ds >= existing_report_date
