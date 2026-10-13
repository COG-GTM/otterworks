from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.domain.oracle_compat import oracle_to_char, round_half_up


@pytest.mark.rule("INS-RATE-006")
@pytest.mark.parametrize(
    ("value", "text"),
    [
        (D("8.50"), "8.5"),
        (D("0.5"), ".5"),
        (D("-0.5"), "-.5"),
        (D("110.00"), "110"),
        (D("100"), "100"),
        (D("0"), "0"),
        (D("12.345"), "12.345"),
        (None, ""),
    ],
)
def test_oracle_to_char(value: D | None, text: str) -> None:
    assert oracle_to_char(value) == text


@pytest.mark.rule("INS-CALC-003")
def test_round_half_up() -> None:
    assert round_half_up(D("2.345")) == D("2.35")
    assert round_half_up(D("-2.345")) == D("-2.35")
