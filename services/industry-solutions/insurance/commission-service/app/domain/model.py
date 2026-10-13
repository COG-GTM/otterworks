from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

ACTIVE = "ACTIVE"
IN_FORCE = "IN_FORCE"


@dataclass(frozen=True)
class Rate:
    rate_id: int
    product_code: str
    agent_id: int | None
    rate_pct: Decimal
    effective_from: date
    effective_to: date | None
    created_by: str


@dataclass(frozen=True)
class Policy:
    policy_id: int
    policy_no: str
    product_code: str
    annual_premium: Decimal
    status: str


@dataclass(frozen=True)
class Split:
    agent_id: int
    split_pct: Decimal


@dataclass(frozen=True)
class LedgerRow:
    policy_id: int
    agent_id: int
    period_month: str
    rate_id: int
    split_pct: Decimal
    base_premium: Decimal
    commission_amt: Decimal


@dataclass(frozen=True)
class Agent:
    agent_id: int
    agent_code: str
    full_name: str
    status: str


@dataclass(frozen=True)
class Product:
    product_code: str
    product_name: str
    line_of_business: str


@dataclass(frozen=True)
class LedgerFactSource:
    """A ledger row joined to its policy's product, as the ETL reads it."""

    policy_id: int
    agent_id: int
    period_month: str
    product_code: str
    split_pct: Decimal
    base_premium: Decimal
    commission_amt: Decimal


@dataclass(frozen=True)
class PeriodDim:
    period_month: str
    year_num: int
    month_num: int
    quarter_num: int


@dataclass(frozen=True)
class Fact:
    agent_id: int
    product_code: str
    period_month: str
    policy_id: int
    split_pct: Decimal
    base_premium: Decimal
    commission_amt: Decimal


@dataclass(frozen=True)
class SummaryRow:
    agent_code: str
    full_name: str
    period_month: str
    line_of_business: str
    policy_rows: int
    total_commission: Decimal


class CommissionRepository(Protocol):
    """Tenant-bound persistence port. Implementations scope every call."""

    def product_exists(self, product_code: str) -> bool: ...

    def agent_status(self, agent_id: int) -> str | None: ...

    def open_rates(self, product_code: str, agent_id: int | None) -> list[Rate]: ...

    def amend_rate(self, rate_id: int, rate_pct: Decimal, actor: str) -> None: ...

    def close_rate(self, rate_id: int, effective_to: date) -> None: ...

    def insert_rate(
        self,
        product_code: str,
        agent_id: int | None,
        rate_pct: Decimal,
        effective_from: date,
        actor: str,
    ) -> int: ...

    def rates_for_product(self, product_code: str) -> list[Rate]: ...

    def get_rate(self, rate_id: int) -> Rate | None: ...

    def get_policy(self, policy_id: int) -> Policy | None: ...

    def list_splits(self, policy_id: int) -> list[Split]: ...

    def replace_splits(self, policy_id: int, splits: list[Split]) -> None: ...

    def delete_ledger(self, policy_id: int, period_month: str) -> None: ...

    def insert_ledger(self, row: LedgerRow) -> None: ...

    def log_action(
        self,
        action: str,
        product_code: str | None,
        agent_id: int | None,
        policy_id: int | None,
        detail: str,
        actor: str,
    ) -> None: ...


class WarehouseRepository(Protocol):
    """Tenant-bound port for the OLAP side of DW_ETL_PKG."""

    def list_agents(self) -> list[Agent]: ...

    def list_products(self) -> list[Product]: ...

    def ledger_fact_sources(self, period_month: str | None) -> list[LedgerFactSource]: ...

    def upsert_dim_agents(self, agents: list[Agent]) -> None: ...

    def upsert_dim_products(self, products: list[Product]) -> None: ...

    def insert_missing_periods(self, periods: list[PeriodDim]) -> None: ...

    def merge_facts(self, facts: list[Fact]) -> None: ...
