"""Unit tests for scripts/seed.py audit-log fixtures (no database required)."""

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

SEED_PATH = Path(__file__).resolve().parents[1] / "seed.py"


@pytest.fixture(scope="module")
def seed():
    stubs = {
        "bcrypt": types.ModuleType("bcrypt"),
        "psycopg2": types.ModuleType("psycopg2"),
        "psycopg2.extras": types.ModuleType("psycopg2.extras"),
    }
    stubs["psycopg2"].OperationalError = Exception
    stubs["psycopg2.extras"].execute_values = _capture_execute_values
    stubs["psycopg2.extras"].Json = dict
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("otterworks_seed", SEED_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def _capture_execute_values(cur, sql, rows, template=None):
    cur.inserted.extend(rows)


class FakeCursor:
    def __init__(self, users):
        self.users = users
        self.inserted = []

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return list(self.users)


def audit_rows(seed, users):
    cur = FakeCursor(users)
    seed.seed_audit_logs(cur)
    return cur.inserted


def stable_fields(row):
    _id, actor_id, actor_email, action, resource_type, resource_id, *_rest = row
    ip = row[7]
    resource = resource_id if resource_type == "AdminUser" else None
    return actor_id, actor_email, action, resource_type, resource, ip



@pytest.fixture(scope="module")
def users(seed):
    return [(u["id"], u["email"]) for u in seed.USERS]


def test_does_not_use_stdlib_random():
    source = SEED_PATH.read_text()
    assert not re.search(r"^\s*(import random|from random )", source, re.M)


def test_fixture_int_is_stable_and_in_range(seed):
    assert seed.fixture_int("k", 10) == seed.fixture_int("k", 10)
    values = {seed.fixture_int(f"k{i}", 7) for i in range(500)}
    assert values == set(range(7))


def test_audit_rows_repeatable_and_independent_of_query_order(seed, users):
    first = [stable_fields(r) for r in audit_rows(seed, users)]
    again = [stable_fields(r) for r in audit_rows(seed, list(reversed(users)))]
    assert len(first) == 80
    assert first == again


def test_audit_rows_reference_seeded_users_and_stay_in_bounds(seed, users):
    ids = {u[0] for u in users}
    actions = set(seed.AUDIT_ACTIONS)
    ip_re = re.compile(r"^192\.168\.([1-5])\.(\d{1,3})$")
    now = seed.now()
    rows = audit_rows(seed, users)
    for row in rows:
        _id, actor_id, actor_email, action, resource_type, resource_id = row[:6]
        assert (actor_id, actor_email) in users
        assert (action, resource_type) in actions
        if resource_type == "AdminUser":
            assert resource_id in ids
        m = ip_re.match(row[7])
        assert m and 1 <= int(m.group(2)) <= 254
        age_hours = (now - row[9]).total_seconds() / 3600
        assert -0.01 <= age_hours <= 30 * 24 + 0.01
    assert len({r[3] for r in rows}) > 1
    assert len({r[1] for r in rows}) > 1
