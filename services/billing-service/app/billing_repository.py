from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import psycopg

from app.dunning import DunningAttempt, Invoice, SuspensionNotice
from app.invoicing import CreditNote, InvoiceLine, IssuedInvoice
from app.money import utc_midnight
from app.rating import FinalizedRating, PriorRollover, UsageEvent


class PostgresBillingRepository:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _all(self, query: str, params: tuple = ()) -> list[dict]:
        return self.connection.execute(query, params).fetchall()

    def tenant_profile(self, tenant_id: UUID) -> dict | None:
        rows = self._all(
            "SELECT id, status, tax_exempt FROM billing_svc.tenants WHERE id = %s", (tenant_id,)
        )
        return rows[0] if rows else None

    def tenant_statuses(self) -> dict[UUID, str]:
        return {row["id"]: row["status"] for row in self._all(
            "SELECT id, status FROM billing_svc.tenants"
        )}

    def usage_events(self, tenant_id: UUID) -> list[UsageEvent]:
        return [
            UsageEvent(row["tenant_id"], row["occurred_at"], row["units"], row["kind"])
            for row in self._all(
                """
                SELECT tenant_id, occurred_at, units, kind
                FROM billing_svc.usage_events WHERE tenant_id = %s
                """,
                (tenant_id,),
            )
        ]

    def prior_rollovers(self, tenant_id: UUID) -> list[PriorRollover]:
        return [
            PriorRollover(row["period_start"], row["rollover_units"])
            for row in self._all(
                """
                SELECT p.period_start, r.rollover_units
                FROM billing_svc.rating_results r
                JOIN billing_svc.rating_periods p ON p.id = r.period_id
                WHERE p.tenant_id = %s
                """,
                (tenant_id,),
            )
        ]

    def save_rating(
        self, tenant_id: UUID, period_start: date, period_end: date, result: FinalizedRating
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO billing_svc.rating_periods (id, tenant_id, period_start, period_end)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, period_start) DO UPDATE SET period_end = EXCLUDED.period_end
            """,
            (result.period_id, tenant_id, period_start, period_end),
        )
        self.connection.execute(
            """
            INSERT INTO billing_svc.rating_results
                (id, period_id, subscription_id, used_units, quota_units, rollover_units,
                 billable_units, overage_amount, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                used_units = EXCLUDED.used_units,
                rollover_units = EXCLUDED.rollover_units,
                billable_units = EXCLUDED.billable_units,
                overage_amount = EXCLUDED.overage_amount
            """,
            (
                result.result_id,
                result.period_id,
                result.subscription_id,
                result.used_units,
                result.quota_units,
                result.rollover_units,
                result.billable_units,
                result.overage_amount,
                utc_midnight(period_end),
            ),
        )

    def rating_results(self, tenant_id: UUID, period_start: date) -> list[dict]:
        return self._all(
            """
            SELECT r.used_units, r.quota_units, r.rollover_units, r.billable_units,
                   r.overage_amount
            FROM billing_svc.rating_results r
            JOIN billing_svc.rating_periods p ON p.id = r.period_id
            WHERE p.tenant_id = %s AND p.period_start = %s
            ORDER BY r.id
            """,
            (tenant_id, period_start),
        )

    def credit_notes(self, tenant_id: UUID) -> list[CreditNote]:
        return [
            CreditNote(row["id"], row["issued_on"], Decimal(row["remaining_amount"]))
            for row in self._all(
                """
                SELECT id, issued_on, remaining_amount FROM billing_svc.credit_notes
                WHERE tenant_id = %s ORDER BY issued_on, id
                """,
                (tenant_id,),
            )
        ]

    def save_invoice(
        self, tenant_id: UUID, period_id: UUID, issued_at: datetime, invoice: IssuedInvoice
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO billing_svc.invoices
                (id, tenant_id, period_id, issued_at, subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, 0, 0, 0, 'issued')
            ON CONFLICT (id) DO UPDATE SET status = 'issued'
            """,
            (invoice.invoice_id, tenant_id, period_id, issued_at),
        )
        self.connection.execute(
            "DELETE FROM billing_svc.invoice_lines WHERE invoice_id = %s", (invoice.invoice_id,)
        )
        for line in invoice.lines:
            self.connection.execute(
                """
                INSERT INTO billing_svc.invoice_lines
                    (id, invoice_id, line_no, line_type, description, amount)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    line.line_id,
                    invoice.invoice_id,
                    line.line_no,
                    line.line_type,
                    line.description,
                    line.amount,
                ),
            )
        self.connection.execute(
            "UPDATE billing_svc.invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s",
            (invoice.subtotal, invoice.tax, invoice.total, invoice.invoice_id),
        )
        for credit_id, remaining in invoice.credit_balances.items():
            self.connection.execute(
                "UPDATE billing_svc.credit_notes SET remaining_amount = %s WHERE id = %s",
                (remaining, credit_id),
            )

    def period_invoices(self, period_id: UUID) -> list[dict]:
        return self._all(
            """
            SELECT id, status, subtotal, tax, total FROM billing_svc.invoices
            WHERE period_id = %s ORDER BY issued_at, id
            """,
            (period_id,),
        )

    def invoice_lines(self, invoice_id: UUID) -> list[InvoiceLine]:
        return [
            InvoiceLine(
                row["id"], row["line_no"], row["line_type"], row["description"],
                Decimal(row["amount"]),
            )
            for row in self._all(
                """
                SELECT id, line_no, line_type, description, amount
                FROM billing_svc.invoice_lines WHERE invoice_id = %s ORDER BY line_no
                """,
                (invoice_id,),
            )
        ]

    def invoices(self) -> list[Invoice]:
        return [
            Invoice(
                row["id"], row["tenant_id"], row["issued_at"], Decimal(row["total"]),
                row["status"],
            )
            for row in self._all(
                "SELECT id, tenant_id, issued_at, total, status FROM billing_svc.invoices"
            )
        ]

    def dunning_attempts(self) -> list[DunningAttempt]:
        return [
            DunningAttempt(
                row["id"], row["tenant_id"], row["invoice_id"], row["attempt_no"],
                row["scheduled_for"], row["status"],
            )
            for row in self._all(
                """
                SELECT id, tenant_id, invoice_id, attempt_no, scheduled_for, status
                FROM billing_svc.dunning_attempts ORDER BY invoice_id, attempt_no
                """
            )
        ]

    def insert_dunning_attempt(self, attempt: DunningAttempt) -> None:
        self.connection.execute(
            """
            INSERT INTO billing_svc.dunning_attempts
                (id, tenant_id, invoice_id, attempt_no, scheduled_for, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (invoice_id, attempt_no) DO NOTHING
            """,
            (
                attempt.attempt_id,
                attempt.tenant_id,
                attempt.invoice_id,
                attempt.attempt_no,
                attempt.scheduled_for,
                attempt.status,
            ),
        )

    def suspend_tenant(self, tenant_id: UUID, as_of: date) -> list[dict]:
        self.connection.execute(
            "UPDATE billing_svc.tenants SET status = 'suspended' WHERE id = %s", (tenant_id,)
        )
        return self._all(
            """
            UPDATE billing_svc.subscriptions
            SET status = 'suspended', suspended_on = %s
            WHERE tenant_id = %s AND status = 'active'
            RETURNING id, tenant_id, status, suspended_on
            """,
            (as_of, tenant_id),
        )

    def insert_suspension_notice(self, notice: SuspensionNotice) -> None:
        self.connection.execute(
            """
            INSERT INTO billing_svc.notifications (id, tenant_id, kind, sent_at)
            VALUES (%s, %s, 'suspension', %s)
            ON CONFLICT (tenant_id, kind, sent_at) DO NOTHING
            """,
            (notice.notification_id, notice.tenant_id, notice.sent_at),
        )

    def suspension_notifications(self) -> list[dict]:
        return self._all(
            """
            SELECT id, tenant_id, kind, sent_at FROM billing_svc.notifications
            WHERE kind = 'suspension' ORDER BY tenant_id, sent_at
            """
        )
