"""Rate management: COMMISSION_PKG.upsert_commission_rate / end_commission_rate / resolve_rate."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.domain.errors import (
    ConstraintViolationError,
    DuplicateOpenRateError,
    InactiveAgentError,
    InvalidRateError,
    NoRateError,
    UnknownAgentError,
    UnknownProductError,
)
from app.domain.model import ACTIVE, CommissionRepository, Rate
from app.domain.oracle_compat import oracle_to_char, round_half_up

MAX_RATE = Decimal("50")


def assert_product(repo: CommissionRepository, product_code: str) -> None:
    if not repo.product_exists(product_code):
        raise UnknownProductError(f"Unknown product: {product_code}")


def assert_active_agent(repo: CommissionRepository, agent_id: int) -> None:
    status = repo.agent_status(agent_id)
    if status is None:
        raise UnknownAgentError(f"Unknown agent: {agent_id}")
    if status != ACTIVE:
        raise InactiveAgentError(f"Agent {agent_id} is {status}")


def stored_rate(rate_pct: Decimal) -> Decimal:
    """NUMBER(5,2) storage plus CK_RATES_RANGE, applied after the raw-value check."""
    stored = round_half_up(rate_pct)
    if stored <= 0 or stored > MAX_RATE:
        raise ConstraintViolationError("check constraint (CK_RATES_RANGE) violated")
    return stored


def upsert_commission_rate(
    repo: CommissionRepository,
    product_code: str,
    agent_id: int | None,
    rate_pct: Decimal | None,
    effective_from: date,
    actor: str,
) -> int:
    if rate_pct is None or rate_pct <= 0 or rate_pct > MAX_RATE:
        shown = "NULL" if rate_pct is None else oracle_to_char(rate_pct)
        raise InvalidRateError(f"Rate must be in (0, 50]: {shown}")
    assert_product(repo, product_code)
    if agent_id is not None:
        assert_active_agent(repo, agent_id)
    pct = stored_rate(rate_pct)

    open_rates = repo.open_rates(product_code, agent_id)
    same_day = [rate for rate in open_rates if rate.effective_from == effective_from]
    if same_day:
        rate_id = same_day[0].rate_id
        repo.amend_rate(rate_id, pct, actor)
    else:
        for rate in open_rates:
            if rate.effective_from < effective_from:
                repo.close_rate(rate.rate_id, effective_from - timedelta(days=1))
        if any(rate.effective_from > effective_from for rate in open_rates):
            raise DuplicateOpenRateError(
                "unique constraint (UX_RATES_OPEN) violated: a later open rate exists"
            )
        rate_id = repo.insert_rate(product_code, agent_id, pct, effective_from, actor)

    repo.log_action(
        "RATE_UPSERT",
        product_code,
        agent_id,
        None,
        f"rate_id={rate_id} pct={oracle_to_char(rate_pct)} from={effective_from.isoformat()}",
        actor,
    )
    return rate_id


def end_commission_rate(
    repo: CommissionRepository,
    product_code: str,
    agent_id: int | None,
    effective_to: date,
    actor: str,
) -> None:
    open_rates = repo.open_rates(product_code, agent_id)
    if not open_rates:
        scope = "default" if agent_id is None else str(agent_id)
        raise NoRateError(f"No open rate for {product_code}/{scope}")
    if any(effective_to < rate.effective_from for rate in open_rates):
        raise ConstraintViolationError("check constraint (CK_RATES_DATES) violated")
    for rate in open_rates:
        repo.close_rate(rate.rate_id, effective_to)
    repo.log_action(
        "RATE_END", product_code, agent_id, None, f"to={effective_to.isoformat()}", actor
    )


def select_rate(candidates: list[Rate], agent_id: int | None, as_of: date) -> Rate | None:
    """The rate in force: agent-specific beats product default, latest start wins."""
    in_force = [
        rate
        for rate in candidates
        if (rate.agent_id is None or (agent_id is not None and rate.agent_id == agent_id))
        and rate.effective_from <= as_of
        and (rate.effective_to is None or rate.effective_to >= as_of)
    ]
    in_force.sort(
        key=lambda rate: (
            rate.agent_id is None,
            rate.agent_id or 0,
            -rate.effective_from.toordinal(),
        )
    )
    return in_force[0] if in_force else None


def resolve_rate(
    repo: CommissionRepository, product_code: str, agent_id: int | None, as_of: date
) -> Rate:
    rate = select_rate(repo.rates_for_product(product_code), agent_id, as_of)
    if rate is None:
        scope = "default" if agent_id is None else str(agent_id)
        raise NoRateError(
            f"No rate in force for {product_code}/agent {scope} on {as_of.isoformat()}"
        )
    return rate
