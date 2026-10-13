"""OLAP load and rollup: DW_ETL_PKG.load_commission_facts and MV_AGENT_COMMISSION_SUMMARY."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.domain.model import (
    Agent,
    Fact,
    LedgerFactSource,
    PeriodDim,
    Product,
    SummaryRow,
    WarehouseRepository,
)


def period_dim(period_month: str) -> PeriodDim:
    year, month = int(period_month[:4]), int(period_month[5:7])
    return PeriodDim(period_month, year, month, (month + 2) // 3)


def facts_from_ledger(sources: list[LedgerFactSource]) -> list[Fact]:
    return [
        Fact(
            agent_id=row.agent_id,
            product_code=row.product_code,
            period_month=row.period_month,
            policy_id=row.policy_id,
            split_pct=row.split_pct,
            base_premium=row.base_premium,
            commission_amt=row.commission_amt,
        )
        for row in sources
    ]


def load_commission_facts(repo: WarehouseRepository, period_month: str | None) -> int:
    """Idempotent upsert of dimensions then facts; returns the facts merged.

    Faithful to the legacy MERGE: facts whose ledger rows have since been
    removed are not deleted.
    """
    repo.upsert_dim_agents(repo.list_agents())
    repo.upsert_dim_products(repo.list_products())
    sources = repo.ledger_fact_sources(period_month)
    periods = sorted({row.period_month for row in sources})
    repo.insert_missing_periods([period_dim(period) for period in periods])
    facts = facts_from_ledger(sources)
    repo.merge_facts(facts)
    return len(facts)


def summarize(
    facts: list[Fact], agents: dict[int, Agent], products: dict[str, Product]
) -> list[SummaryRow]:
    """Commission earned per agent per period per line of business."""
    groups: dict[tuple[str, str, str, str], list[Decimal]] = defaultdict(list)
    for fact in facts:
        agent = agents[fact.agent_id]
        product = products[fact.product_code]
        key = (agent.agent_code, agent.full_name, fact.period_month, product.line_of_business)
        groups[key].append(fact.commission_amt)
    return [
        SummaryRow(code, name, period, lob, len(amounts), sum(amounts, Decimal("0")))
        for (code, name, period, lob), amounts in sorted(groups.items())
    ]
