from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from tests.fakes import FakeRepository  # noqa: E402


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()
