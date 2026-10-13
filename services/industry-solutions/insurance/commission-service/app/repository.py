"""PostgreSQL adapters for the domain ports.

Each repository is constructed for exactly one tenant and every statement
filters on that tenant explicitly; FORCE ROW LEVEL SECURITY is the backstop.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

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
    SummaryRow,
)

RATE_COLUMNS = "rate_id, product_code, agent_id, rate_pct, effective_from, effective_to, created_by"


def _rate(row: dict[str, Any]) -> Rate:
    return Rate(
        rate_id=row["rate_id"],
        product_code=row["product_code"],
        agent_id=row["agent_id"],
        rate_pct=row["rate_pct"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        created_by=row["created_by"],
    )


class PostgresCommissionRepository:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]], tenant_id: str) -> None:
        self.db = connection
        self.tenant_id = tenant_id

    def _all(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return self.db.execute(sql, (self.tenant_id, *params)).fetchall()

    def _one(self, sql: str, *params: Any) -> dict[str, Any] | None:
        return self.db.execute(sql, (self.tenant_id, *params)).fetchone()

    # --- reference data -------------------------------------------------
    def product_exists(self, product_code: str) -> bool:
        return (
            self._one(
                "SELECT 1 FROM commission.products WHERE tenant_id = %s AND product_code = %s",
                product_code,
            )
            is not None
        )

    def agent_status(self, agent_id: int) -> str | None:
        row = self._one(
            "SELECT status FROM commission.agents WHERE tenant_id = %s AND agent_id = %s",
            agent_id,
        )
        return None if row is None else row["status"]

    def get_policy(self, policy_id: int) -> Policy | None:
        row = self._one(
            """SELECT policy_id, policy_no, product_code, annual_premium, status
                 FROM commission.policies WHERE tenant_id = %s AND policy_id = %s""",
            policy_id,
        )
        return None if row is None else Policy(**row)

    # --- rates ------------------------------------------------------------
    def _lock_policy(self, policy_id: int) -> None:
        self._one(
            "SELECT 1 FROM commission.policies WHERE tenant_id = %s AND policy_id = %s FOR UPDATE",
            policy_id,
        )

    def open_rates(self, product_code: str, agent_id: int | None) -> list[Rate]:
        # Serialise every writer of one tenant/product/agent rate scope for the transaction,
        # so the read below sees rows committed by a writer we waited on.
        self._one(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s || '|' || %s || '|' || %s, 0))",
            product_code,
            "" if agent_id is None else str(agent_id),
        )
        rows = self._all(
            f"""SELECT {RATE_COLUMNS} FROM commission.commission_rates
                 WHERE tenant_id = %s AND product_code = %s
                   AND agent_id IS NOT DISTINCT FROM %s AND effective_to IS NULL
                 ORDER BY rate_id FOR UPDATE""",
            product_code,
            agent_id,
        )
        return [_rate(row) for row in rows]

    def amend_rate(self, rate_id: int, rate_pct: Decimal, actor: str) -> None:
        self.db.execute(
            """UPDATE commission.commission_rates SET rate_pct = %s, created_by = %s
                WHERE tenant_id = %s AND rate_id = %s""",
            (rate_pct, actor, self.tenant_id, rate_id),
        )

    def close_rate(self, rate_id: int, effective_to: date) -> None:
        self.db.execute(
            """UPDATE commission.commission_rates SET effective_to = %s
                WHERE tenant_id = %s AND rate_id = %s""",
            (effective_to, self.tenant_id, rate_id),
        )

    def insert_rate(
        self,
        product_code: str,
        agent_id: int | None,
        rate_pct: Decimal,
        effective_from: date,
        actor: str,
    ) -> int:
        # Per-tenant ids, serialised on the tenant row so concurrent writers cannot collide.
        self._one("SELECT 1 FROM commission.tenants WHERE tenant_id = %s FOR UPDATE")
        row = self.db.execute(
            """INSERT INTO commission.commission_rates
                   (tenant_id, rate_id, product_code, agent_id, rate_pct,
                    effective_from, effective_to, created_by)
               VALUES (%s,
                       COALESCE((SELECT MAX(rate_id) FROM commission.commission_rates
                                  WHERE tenant_id = %s), 0) + 1,
                       %s, %s, %s, %s, NULL, %s)
               RETURNING rate_id""",
            (
                self.tenant_id,
                self.tenant_id,
                product_code,
                agent_id,
                rate_pct,
                effective_from,
                actor,
            ),
        ).fetchone()
        assert row is not None
        return int(row["rate_id"])

    def rates_for_product(self, product_code: str) -> list[Rate]:
        rows = self._all(
            f"""SELECT {RATE_COLUMNS} FROM commission.commission_rates
                 WHERE tenant_id = %s AND product_code = %s ORDER BY rate_id""",
            product_code,
        )
        return [_rate(row) for row in rows]

    def get_rate(self, rate_id: int) -> Rate | None:
        row = self._one(
            f"""SELECT {RATE_COLUMNS} FROM commission.commission_rates
                 WHERE tenant_id = %s AND rate_id = %s""",
            rate_id,
        )
        return None if row is None else _rate(row)

    # --- splits -----------------------------------------------------------
    def list_splits(self, policy_id: int) -> list[Split]:
        rows = self._all(
            """SELECT agent_id, split_pct FROM commission.commission_splits
                WHERE tenant_id = %s AND policy_id = %s ORDER BY agent_id""",
            policy_id,
        )
        return [Split(**row) for row in rows]

    def replace_splits(self, policy_id: int, splits: list[Split]) -> None:
        self._lock_policy(policy_id)
        self.db.execute(
            "DELETE FROM commission.commission_splits WHERE tenant_id = %s AND policy_id = %s",
            (self.tenant_id, policy_id),
        )
        for split in splits:
            self.db.execute(
                """INSERT INTO commission.commission_splits
                       (tenant_id, policy_id, agent_id, split_pct) VALUES (%s, %s, %s, %s)""",
                (self.tenant_id, policy_id, split.agent_id, split.split_pct),
            )

    # --- ledger -----------------------------------------------------------
    def delete_ledger(self, policy_id: int, period_month: str) -> None:
        self._lock_policy(policy_id)
        self.db.execute(
            """DELETE FROM commission.commission_ledger
                WHERE tenant_id = %s AND policy_id = %s AND period_month = %s""",
            (self.tenant_id, policy_id, period_month),
        )

    def insert_ledger(self, row: LedgerRow) -> None:
        self.db.execute(
            """INSERT INTO commission.commission_ledger
                   (tenant_id, policy_id, agent_id, period_month, rate_id,
                    split_pct, base_premium, commission_amt)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                self.tenant_id,
                row.policy_id,
                row.agent_id,
                row.period_month,
                row.rate_id,
                row.split_pct,
                row.base_premium,
                row.commission_amt,
            ),
        )

    def list_ledger(self, policy_id: int | None, period_month: str | None) -> list[LedgerRow]:
        rows = self._all(
            """SELECT policy_id, agent_id, period_month, rate_id, split_pct,
                      base_premium, commission_amt
                 FROM commission.commission_ledger
                WHERE tenant_id = %s
                  AND (%s::bigint IS NULL OR policy_id = %s::bigint)
                  AND (%s::text IS NULL OR period_month = %s::text)
                ORDER BY period_month, policy_id, agent_id""",
            policy_id,
            policy_id,
            period_month,
            period_month,
        )
        return [LedgerRow(**row) for row in rows]

    # --- audit ------------------------------------------------------------
    def log_action(
        self,
        action: str,
        product_code: str | None,
        agent_id: int | None,
        policy_id: int | None,
        detail: str,
        actor: str,
    ) -> None:
        self.db.execute(
            """INSERT INTO commission.rate_audit_log
                   (tenant_id, action, product_code, agent_id, policy_id, detail, actor)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (self.tenant_id, action, product_code, agent_id, policy_id, detail, actor),
        )

    def list_audit(self) -> list[dict[str, Any]]:
        return self._all(
            """SELECT action, product_code, agent_id, policy_id, detail, actor, logged_at
                 FROM commission.rate_audit_log WHERE tenant_id = %s ORDER BY audit_id"""
        )


class PostgresWarehouseRepository:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]], tenant_id: str) -> None:
        self.db = connection
        self.tenant_id = tenant_id

    def _all(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return self.db.execute(sql, (self.tenant_id, *params)).fetchall()

    def list_agents(self) -> list[Agent]:
        rows = self._all(
            """SELECT agent_id, agent_code, full_name, status FROM commission.agents
                WHERE tenant_id = %s ORDER BY agent_id"""
        )
        return [Agent(**row) for row in rows]

    def list_products(self) -> list[Product]:
        rows = self._all(
            """SELECT product_code, product_name, line_of_business FROM commission.products
                WHERE tenant_id = %s ORDER BY product_code"""
        )
        return [Product(**row) for row in rows]

    def ledger_fact_sources(self, period_month: str | None) -> list[LedgerFactSource]:
        rows = self._all(
            """SELECT cl.policy_id, cl.agent_id, cl.period_month, po.product_code,
                      cl.split_pct, cl.base_premium, cl.commission_amt
                 FROM commission.commission_ledger cl
                 JOIN commission.policies po
                   ON po.tenant_id = cl.tenant_id AND po.policy_id = cl.policy_id
                WHERE cl.tenant_id = %s AND (%s::text IS NULL OR cl.period_month = %s::text)
                ORDER BY cl.period_month, cl.policy_id, cl.agent_id""",
            period_month,
            period_month,
        )
        return [LedgerFactSource(**row) for row in rows]

    def upsert_dim_agents(self, agents: list[Agent]) -> None:
        for agent in agents:
            self.db.execute(
                """INSERT INTO commission.dim_agent
                       (tenant_id, agent_id, agent_code, full_name, status)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id, agent_id) DO UPDATE SET
                       agent_code = EXCLUDED.agent_code,
                       full_name = EXCLUDED.full_name,
                       status = EXCLUDED.status""",
                (self.tenant_id, agent.agent_id, agent.agent_code, agent.full_name, agent.status),
            )

    def upsert_dim_products(self, products: list[Product]) -> None:
        for product in products:
            self.db.execute(
                """INSERT INTO commission.dim_product
                       (tenant_id, product_code, product_name, line_of_business)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (tenant_id, product_code) DO UPDATE SET
                       product_name = EXCLUDED.product_name,
                       line_of_business = EXCLUDED.line_of_business""",
                (
                    self.tenant_id,
                    product.product_code,
                    product.product_name,
                    product.line_of_business,
                ),
            )

    def insert_missing_periods(self, periods: list[PeriodDim]) -> None:
        for period in periods:
            self.db.execute(
                """INSERT INTO commission.dim_period
                       (tenant_id, period_month, year_num, month_num, quarter_num)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id, period_month) DO NOTHING""",
                (
                    self.tenant_id,
                    period.period_month,
                    period.year_num,
                    period.month_num,
                    period.quarter_num,
                ),
            )

    def merge_facts(self, facts: list[Fact]) -> None:
        for fact in facts:
            self.db.execute(
                """INSERT INTO commission.fact_commission
                       (tenant_id, policy_id, agent_id, period_month, product_code,
                        split_pct, base_premium, commission_amt)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id, policy_id, agent_id, period_month) DO UPDATE SET
                       split_pct = EXCLUDED.split_pct,
                       base_premium = EXCLUDED.base_premium,
                       commission_amt = EXCLUDED.commission_amt,
                       loaded_at = now()""",
                (
                    self.tenant_id,
                    fact.policy_id,
                    fact.agent_id,
                    fact.period_month,
                    fact.product_code,
                    fact.split_pct,
                    fact.base_premium,
                    fact.commission_amt,
                ),
            )

    def list_facts(self, period_month: str | None) -> list[Fact]:
        rows = self._all(
            """SELECT agent_id, product_code, period_month, policy_id, split_pct,
                      base_premium, commission_amt
                 FROM commission.fact_commission
                WHERE tenant_id = %s AND (%s::text IS NULL OR period_month = %s::text)
                ORDER BY period_month, policy_id, agent_id""",
            period_month,
            period_month,
        )
        return [Fact(**row) for row in rows]

    def summary(self, period_month: str | None) -> list[SummaryRow]:
        rows = self._all(
            """SELECT da.agent_code, da.full_name, f.period_month::text AS period_month,
                      dp.line_of_business, COUNT(*)::int AS policy_rows,
                      SUM(f.commission_amt) AS total_commission
                 FROM commission.fact_commission f
                 JOIN commission.dim_agent da
                   ON da.tenant_id = f.tenant_id AND da.agent_id = f.agent_id
                 JOIN commission.dim_product dp
                   ON dp.tenant_id = f.tenant_id AND dp.product_code = f.product_code
                WHERE f.tenant_id = %s AND (%s::text IS NULL OR f.period_month = %s::text)
                GROUP BY da.agent_code, da.full_name, f.period_month, dp.line_of_business
                ORDER BY da.agent_code, f.period_month, dp.line_of_business""",
            period_month,
            period_month,
        )
        return [SummaryRow(**row) for row in rows]
