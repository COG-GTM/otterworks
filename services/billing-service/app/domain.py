from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, timedelta
from typing import Any


class BillingDomain:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_plans(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, code, tier, monthly_fee, included_units, overage_rate
            FROM plans WHERE active = 1 ORDER BY monthly_fee, code
            """
        ).fetchall()
        return [
            {
                "plan_id": row["id"],
                "code": row["code"],
                "tier": row["tier"],
                "monthly_fee": f"{row['monthly_fee']:.2f}",
                "included_units": row["included_units"],
                "overage_rate": f"{row['overage_rate']:.6f}",
            }
            for row in rows
        ]

    def entitlement(self, tenant_id: str, on: date) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT t.id AS tenant_id, p.code AS plan_code, p.tier,
                   p.monthly_fee, p.included_units, s.status,
                   MAX(s.starts_on, ?) AS effective_on
            FROM tenants t
            JOIN subscriptions s ON s.tenant_id = t.id
            JOIN plans p ON p.id = s.plan_id
            WHERE t.id = ? AND s.starts_on <= ?
              AND (s.ends_on IS NULL OR s.ends_on >= ?)
            ORDER BY s.starts_on DESC LIMIT 1
            """,
            (on.isoformat(), tenant_id, on.isoformat(), on.isoformat()),
        ).fetchone()
        if row is None:
            return None
        return {
            "tenant_id": row["tenant_id"],
            "plan_code": row["plan_code"],
            "tier": row["tier"],
            "monthly_fee": f"{row['monthly_fee']:.2f}",
            "included_units": row["included_units"],
            "subscription_status": row["status"],
            "effective_on": row["effective_on"],
        }

    def change_plan(self, tenant_id: str, plan_id: str, effective_on: date) -> dict[str, Any]:
        self.connection.execute(
            """
            UPDATE subscriptions
            SET ends_on = ?, status = CASE WHEN status = 'cancelled' THEN status ELSE 'active' END
            WHERE tenant_id = ? AND ends_on IS NULL AND starts_on < ?
            """,
            ((effective_on - timedelta(days=1)).isoformat(), tenant_id, effective_on.isoformat()),
        )
        subscription_id = hashlib.md5(
            f"{tenant_id}{plan_id}{effective_on.isoformat()}".encode()
        ).hexdigest()
        self.connection.execute(
            """
            INSERT INTO subscriptions
                (id, tenant_id, plan_id, starts_on, ends_on, status, suspended_on)
            VALUES (?, ?, ?, ?, NULL, 'active', NULL)
            """,
            (subscription_id, tenant_id, plan_id, effective_on.isoformat()),
        )
        self.connection.commit()
        subscriptions = self.connection.execute(
            """
            SELECT plan_id, starts_on, ends_on, status
            FROM subscriptions WHERE tenant_id = ? ORDER BY starts_on
            """,
            (tenant_id,),
        ).fetchall()
        return {
            "latest_plan": subscriptions[-1]["plan_id"],
            "latest_start": subscriptions[-1]["starts_on"],
            "subscriptions": [
                {
                    "plan_id": row["plan_id"],
                    "starts_on": row["starts_on"],
                    "ends_on": row["ends_on"],
                    "status": row["status"],
                }
                for row in subscriptions
            ],
        }
