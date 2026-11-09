from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.domain import PlanRow
from app.money import md5_uuid, round_money
from app.rating import Rating

TAX_RATE = Decimal("0.0825")
ZERO = Decimal("0")


@dataclass(frozen=True)
class PreviewLine:
    line_no: int
    line_type: str
    description: str
    amount: Decimal
    tax_amount: Decimal
    credit_applied: Decimal
    total: Decimal


@dataclass(frozen=True)
class CreditNote:
    credit_id: UUID
    issued_on: date
    remaining_amount: Decimal


@dataclass(frozen=True)
class InvoiceLine:
    line_id: UUID
    line_no: int
    line_type: str
    description: str
    amount: Decimal


@dataclass(frozen=True)
class IssuedInvoice:
    invoice_id: UUID
    lines: list[InvoiceLine]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    credit_balances: dict[UUID, Decimal]


def invoice_id(period_id: UUID) -> UUID:
    return md5_uuid(f"{period_id}invoice")


def preview(
    plan: PlanRow, rating: Rating, tax_exempt: bool, credits: list[CreditNote]
) -> list[PreviewLine]:
    available_credit = sum(
        (item.remaining_amount for item in credits if item.remaining_amount > 0), ZERO
    )
    charges = plan.monthly_fee + rating.overage_amount
    tax = ZERO if tax_exempt else charges * TAX_RATE
    credit = min(available_credit, round_money(charges + tax))
    fee = round_money(plan.monthly_fee)
    overage = round_money(rating.overage_amount)
    return [
        PreviewLine(1, "plan", plan.code, fee, ZERO, ZERO, fee),
        PreviewLine(2, "usage", "usage overage", overage, ZERO, ZERO, overage),
        PreviewLine(3, "tax", "regional tax", tax / 2, ZERO, ZERO, tax / 2),
        PreviewLine(4, "tax", "local tax", tax / 2, ZERO, ZERO, tax / 2),
        PreviewLine(5, "credit", "credit notes", ZERO, ZERO, credit, -credit),
    ]


def issue(
    rating_period_id: UUID, lines: list[PreviewLine], credits: list[CreditNote]
) -> IssuedInvoice:
    issued_id = invoice_id(rating_period_id)
    subtotal = tax = credit = ZERO
    persisted = []
    for line in lines:
        amount = line.total if line.line_type == "credit" else line.amount
        persisted.append(
            InvoiceLine(
                md5_uuid(f"{issued_id}{line.line_no}"),
                line.line_no,
                line.line_type,
                line.description,
                round_money(amount),
            )
        )
        if line.line_type in {"plan", "usage"}:
            subtotal += round_money(line.amount)
        elif line.line_type == "tax":
            tax += round_money(line.amount)
        elif line.line_type == "credit":
            credit = line.credit_applied
    total = round_money(subtotal + tax - credit)
    return IssuedInvoice(
        invoice_id=issued_id,
        lines=persisted,
        subtotal=round_money(subtotal),
        tax=round_money(tax),
        total=total,
        credit_balances=apply_credits(credits, credit),
    )


def apply_credits(credits: list[CreditNote], credit: Decimal) -> dict[UUID, Decimal]:
    """Draw the applied credit from open notes, oldest issue date first, then by id."""
    balances: dict[UUID, Decimal] = {}
    open_notes = sorted(
        (item for item in credits if item.remaining_amount > 0),
        key=lambda item: (item.issued_on, item.credit_id),
    )
    for note in open_notes:
        if credit <= 0:
            break
        balances[note.credit_id] = max(note.remaining_amount - credit, ZERO)
        credit = max(credit - note.remaining_amount, ZERO)
    return balances
