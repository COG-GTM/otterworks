"""In-memory implementation of the domain ports, seeded like the Oracle fixture."""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.model import (
    Agent,
    Fact,
    LedgerFactSource,
    LedgerRow,
    PeriodDim,
    Policy,
    Product,
    Rate,
    Split,
)

D = Decimal


def fixture_state() -> dict[str, Any]:
    return {
        "agents": {
            1: Agent(1, "AG-100", "Maria Alvarez", "ACTIVE"),
            2: Agent(2, "AG-101", "James Okafor", "ACTIVE"),
            3: Agent(3, "AG-102", "Priya Natarajan", "ACTIVE"),
            4: Agent(4, "AG-103", "Dale Whitfield", "SUSPENDED"),
        },
        "products": {
            "AUTO-STD": Product("AUTO-STD", "Standard Auto", "AUTO"),
            "HOME-PLUS": Product("HOME-PLUS", "HomeOwners Plus", "HOME"),
            "TERM-20": Product("TERM-20", "20-Year Term Life", "LIFE"),
        },
        "rates": {
            1: Rate(1, "AUTO-STD", None, D("8.00"), date(2024, 1, 1), None, "seed"),
            2: Rate(2, "HOME-PLUS", None, D("10.00"), date(2024, 1, 1), None, "seed"),
            3: Rate(3, "TERM-20", None, D("15.00"), date(2024, 1, 1), None, "seed"),
            4: Rate(4, "AUTO-STD", 1, D("9.50"), date(2024, 6, 1), None, "seed"),
        },
        "policies": {
            1: Policy(1, "POL-2025-0001", "AUTO-STD", D("1800.00"), "IN_FORCE"),
            2: Policy(2, "POL-2025-0002", "HOME-PLUS", D("2400.00"), "IN_FORCE"),
            3: Policy(3, "POL-2025-0003", "TERM-20", D("1200.00"), "IN_FORCE"),
            4: Policy(4, "POL-2025-0004", "AUTO-STD", D("9600.00"), "IN_FORCE"),
            5: Policy(5, "POL-2025-0005", "HOME-PLUS", D("2000.00"), "LAPSED"),
        },
        "splits": {
            1: [Split(1, D("100.00"))],
            2: [Split(1, D("60.00")), Split(2, D("40.00"))],
            4: [Split(1, D("50.00")), Split(2, D("30.00")), Split(3, D("20.00"))],
        },
        "ledger": {},
        "audit": [],
        "dim_agent": {},
        "dim_product": {},
        "dim_period": {},
        "facts": {},
    }


class FakeRepository:
    """Implements CommissionRepository and WarehouseRepository; transactional per call."""

    def __init__(self) -> None:
        self.state = fixture_state()

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.state = snapshot

    # CommissionRepository
    def product_exists(self, product_code: str) -> bool:
        return product_code in self.state["products"]

    def agent_status(self, agent_id: int) -> str | None:
        agent = self.state["agents"].get(agent_id)
        return None if agent is None else agent.status

    def open_rates(self, product_code: str, agent_id: int | None) -> list[Rate]:
        return [
            rate
            for rate in self.state["rates"].values()
            if rate.product_code == product_code
            and rate.agent_id == agent_id
            and rate.effective_to is None
        ]

    def amend_rate(self, rate_id: int, rate_pct: Decimal, actor: str) -> None:
        rates = self.state["rates"]
        rates[rate_id] = replace(rates[rate_id], rate_pct=rate_pct, created_by=actor)

    def close_rate(self, rate_id: int, effective_to: date) -> None:
        rates = self.state["rates"]
        rates[rate_id] = replace(rates[rate_id], effective_to=effective_to)

    def insert_rate(
        self,
        product_code: str,
        agent_id: int | None,
        rate_pct: Decimal,
        effective_from: date,
        actor: str,
    ) -> int:
        rate_id = max(self.state["rates"], default=0) + 1
        self.state["rates"][rate_id] = Rate(
            rate_id, product_code, agent_id, rate_pct, effective_from, None, actor
        )
        return rate_id

    def rates_for_product(self, product_code: str) -> list[Rate]:
        return [r for r in self.state["rates"].values() if r.product_code == product_code]

    def get_rate(self, rate_id: int) -> Rate | None:
        return self.state["rates"].get(rate_id)

    def get_policy(self, policy_id: int) -> Policy | None:
        return self.state["policies"].get(policy_id)

    def list_splits(self, policy_id: int) -> list[Split]:
        return list(self.state["splits"].get(policy_id, []))

    def replace_splits(self, policy_id: int, splits: list[Split]) -> None:
        self.state["splits"][policy_id] = list(splits)

    def delete_ledger(self, policy_id: int, period_month: str) -> None:
        ledger = self.state["ledger"]
        for key in [k for k in ledger if k[0] == policy_id and k[2] == period_month]:
            del ledger[key]

    def insert_ledger(self, row: LedgerRow) -> None:
        self.state["ledger"][(row.policy_id, row.agent_id, row.period_month)] = row

    def log_action(
        self,
        action: str,
        product_code: str | None,
        agent_id: int | None,
        policy_id: int | None,
        detail: str,
        actor: str,
    ) -> None:
        self.state["audit"].append((action, product_code, agent_id, policy_id, detail, actor))

    # WarehouseRepository
    def list_agents(self) -> list[Agent]:
        return list(self.state["agents"].values())

    def list_products(self) -> list[Product]:
        return list(self.state["products"].values())

    def ledger_fact_sources(self, period_month: str | None) -> list[LedgerFactSource]:
        return [
            LedgerFactSource(
                row.policy_id,
                row.agent_id,
                row.period_month,
                self.state["policies"][row.policy_id].product_code,
                row.split_pct,
                row.base_premium,
                row.commission_amt,
            )
            for row in self.state["ledger"].values()
            if period_month is None or row.period_month == period_month
        ]

    def upsert_dim_agents(self, agents: list[Agent]) -> None:
        self.state["dim_agent"].update({agent.agent_id: agent for agent in agents})

    def upsert_dim_products(self, products: list[Product]) -> None:
        self.state["dim_product"].update({p.product_code: p for p in products})

    def insert_missing_periods(self, periods: list[PeriodDim]) -> None:
        for period in periods:
            self.state["dim_period"].setdefault(period.period_month, period)

    def merge_facts(self, facts: list[Fact]) -> None:
        for fact in facts:
            self.state["facts"][(fact.policy_id, fact.agent_id, fact.period_month)] = fact


def transactional(repo: FakeRepository, action: Any) -> Any:
    """Mirror the PL/SQL ROLLBACK-on-error: state is unchanged if action raises."""
    snapshot = repo.snapshot()
    try:
        return action()
    except Exception:
        repo.restore(snapshot)
        raise
