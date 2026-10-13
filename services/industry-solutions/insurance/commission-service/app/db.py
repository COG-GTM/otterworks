from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db" / "migrations"
SEEDS = ROOT / "db" / "seed"

TENANT_TABLES = (
    "fact_commission",
    "dim_period",
    "dim_product",
    "dim_agent",
    "rate_audit_log",
    "commission_ledger",
    "commission_splits",
    "commission_rates",
    "policies",
    "products",
    "agents",
    "tenants",
)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self.url, row_factory=dict_row)

    @contextmanager
    def tenant_transaction(self, tenant_id: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """One transaction with row-level security bound to a single tenant."""
        with self.connect() as connection, connection.transaction():
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            yield connection

    def migrate(self) -> None:
        with self.connect() as connection:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                connection.execute(path.read_text())

    def seed_tenants(self) -> list[str]:
        return sorted(path.stem for path in SEEDS.glob("*.sql"))

    def reset_tenant(self, tenant_id: str) -> None:
        """Restore one tenant to its seed. Other tenants are untouched."""
        seed = SEEDS / f"{tenant_id}.sql"
        if tenant_id not in self.seed_tenants():
            raise KeyError(tenant_id)
        with self.tenant_transaction(tenant_id) as connection:
            for table in TENANT_TABLES:
                connection.execute(
                    f"DELETE FROM commission.{table} WHERE tenant_id = %s",  # noqa: S608
                    (tenant_id,),
                )
            connection.execute(seed.read_text())

    def ensure_seeded(self) -> None:
        for tenant_id in self.seed_tenants():
            with self.tenant_transaction(tenant_id) as connection:
                row = connection.execute(
                    "SELECT 1 FROM commission.tenants WHERE tenant_id = %s", (tenant_id,)
                ).fetchone()
            if row is None:
                self.reset_tenant(tenant_id)
