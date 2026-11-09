from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

CENT = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def round_units(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def md5_uuid(text: str) -> UUID:
    """Mirror PostgreSQL's ``md5(text)::uuid`` so legacy-derived ids stay stable."""
    return UUID(hex=hashlib.md5(text.encode()).hexdigest())


def utc_date(value: datetime) -> date:
    return value.astimezone(UTC).date()


def utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year, month = divmod(month_index, 12)
    month += 1
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    last_day = (next_month - date.resolution).day
    return date(year, month, min(value.day, last_day))
