"""Monthly commission ledger: COMMISSION_PKG.calculate_policy_commission."""

from __future__ import annotations

import calendar
import re
from datetime import date

from app.domain.errors import (
    BadSplitError,
    InvalidPeriodError,
    PolicyNotActiveError,
    UnknownPolicyError,
)
from app.domain.model import IN_FORCE, CommissionRepository, LedgerRow
from app.domain.oracle_compat import monthly_commission
from app.domain.rates import resolve_rate

PERIOD = re.compile(r"([0-9]{4})-([0-9]{2})")


def period_as_of(period_month: str) -> date:
    """LAST_DAY(TO_DATE(period, 'YYYY-MM')), restricted to canonical YYYY-MM."""
    match = PERIOD.fullmatch(period_month or "")
    if not match:
        raise InvalidPeriodError("literal does not match format string", -1861)
    year, month = int(match.group(1)), int(match.group(2))
    if year == 0:
        raise InvalidPeriodError("(full) year must be between -4713 and +9999, and not be 0", -1841)
    if not 1 <= month <= 12:
        raise InvalidPeriodError("not a valid month", -1843)
    return date(year, month, calendar.monthrange(year, month)[1])


def calculate_policy_commission(
    repo: CommissionRepository, policy_id: int, period_month: str, actor: str
) -> list[LedgerRow]:
    policy = repo.get_policy(policy_id)
    if policy is None:
        raise UnknownPolicyError(f"Unknown policy: {policy_id}")
    if policy.status != IN_FORCE:
        raise PolicyNotActiveError(f"Policy {policy_id} is {policy.status}")
    as_of = period_as_of(period_month)

    repo.delete_ledger(policy_id, period_month)
    splits = sorted(repo.list_splits(policy_id), key=lambda s: (-s.split_pct, s.agent_id))
    rows: list[LedgerRow] = []
    for split in splits:
        rate = resolve_rate(repo, policy.product_code, split.agent_id, as_of)
        row = LedgerRow(
            policy_id=policy_id,
            agent_id=split.agent_id,
            period_month=period_month,
            rate_id=rate.rate_id,
            split_pct=split.split_pct,
            base_premium=policy.annual_premium,
            commission_amt=monthly_commission(
                policy.annual_premium, rate.rate_pct, split.split_pct
            ),
        )
        repo.insert_ledger(row)
        rows.append(row)
    if not rows:
        raise BadSplitError(f"Policy {policy_id} has no split allocation")

    repo.log_action(
        "COMMISSION_CALC",
        policy.product_code,
        None,
        policy_id,
        f"{period_month} rows={len(rows)}",
        actor,
    )
    return rows
