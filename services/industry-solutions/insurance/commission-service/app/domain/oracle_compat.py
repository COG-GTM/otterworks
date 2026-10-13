"""Numeric semantics the PL/SQL relied on, reproduced explicitly."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

CENT = Decimal("0.01")
# Oracle NUMBER carries up to 38-40 significant digits; Python's default is 28.
ORACLE_PRECISION = 40


def round_half_up(value: Decimal, places: Decimal = CENT) -> Decimal:
    """ROUND(x, 2) and NUMBER(p, 2) storage: half away from zero."""
    return value.quantize(places, rounding=ROUND_HALF_UP)


def oracle_to_char(value: Decimal | int | None) -> str:
    """TO_CHAR(number) with the default format, as used in legacy messages.

    Trailing zeros are dropped and the leading zero of a fraction is omitted:
    8.50 -> '8.5', 0.5 -> '.5', -0.5 -> '-.5', 110.00 -> '110'.
    """
    if value is None:
        return ""
    number = Decimal(value)
    if number == 0:
        return "0"
    text = format(number.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text.startswith("0."):
        text = text[1:]
    elif text.startswith("-0."):
        text = "-" + text[2:]
    return text


def monthly_commission(annual_premium: Decimal, rate_pct: Decimal, split_pct: Decimal) -> Decimal:
    """annual_premium / 12 * rate_pct / 100 * split_pct / 100, rounded to cents.

    Evaluated left to right at Oracle-like precision, then rounded once.
    """
    with localcontext() as context:
        context.prec = ORACLE_PRECISION
        amount = annual_premium / 12 * rate_pct / 100 * split_pct / 100
    return round_half_up(amount)
