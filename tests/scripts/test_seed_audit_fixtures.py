"""Regression checks for the deterministic audit-log fixtures in scripts/seed.py.

Run with:  python -m pytest tests/scripts -q
(no database needed; psycopg2/bcrypt are stubbed when not installed)
"""
from __future__ import annotations

import importlib.util
import ipaddress
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SEED_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"


def _load_seed():
    if importlib.util.find_spec("bcrypt") is None:
        sys.modules["bcrypt"] = types.ModuleType("bcrypt")
    if importlib.util.find_spec("psycopg2") is None:
        extras = types.ModuleType("psycopg2.extras")
        extras.execute_values = extras.Json = None
        sys.modules["psycopg2"] = types.ModuleType("psycopg2")
        sys.modules["psycopg2"].extras = extras
        sys.modules["psycopg2.extras"] = extras
    spec = importlib.util.spec_from_file_location("otterworks_seed", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load_seed()

USERS = [(u["id"], u["email"]) for u in sorted(seed.USERS, key=lambda u: u["email"])]


FROZEN_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, users):
        self.users = users
        self.queries: list[str] = []

    def execute(self, sql, *args):
        self.queries.append(sql)

    def fetchall(self):
        return list(self.users)


def _audit_rows(monkeypatch, users=USERS):
    captured = {}

    def fake_execute_values(cur, sql, rows, template=None):
        captured["rows"] = rows

    monkeypatch.setattr(seed, "execute_values", fake_execute_values)
    monkeypatch.setattr(seed, "log", lambda msg: None)
    monkeypatch.setattr(seed, "now", lambda: FROZEN_NOW)
    cur = FakeCursor(users)
    seed.seed_audit_logs(cur)
    return cur, captured["rows"]


def _stable(row):
    # id and resource_id for non-user resources are uuid4
    _, actor_id, actor_email, action, resource_type, resource_id, _, ip, ua, created, _ = row
    return actor_id, actor_email, action, resource_type, resource_id if resource_type == "AdminUser" else None, ip, ua, created


def test_seed_does_not_use_random_module():
    source = SEED_PATH.read_text()
    assert not re.search(r"^\s*(import random|from random import)", source, re.M)


def test_fixture_int_is_deterministic_and_in_range():
    values = [seed.fixture_int("k", i, lo=1, hi=5) for i in range(500)]
    assert values == [seed.fixture_int("k", i, lo=1, hi=5) for i in range(500)]
    assert set(values) == {1, 2, 3, 4, 5}
    assert seed.fixture_int("x", lo=7, hi=7) == 7


def test_fixture_choice_covers_sequence():
    seq = ["a", "b", "c"]
    picks = {seed.fixture_choice(seq, "c", i) for i in range(100)}
    assert picks == set(seq)


def test_audit_users_query_is_ordered(monkeypatch):
    cur, _ = _audit_rows(monkeypatch)
    assert "ORDER BY email" in cur.queries[0]


def test_audit_rows_repeat_across_runs(monkeypatch):
    _, first = _audit_rows(monkeypatch)
    _, second = _audit_rows(monkeypatch)
    assert len(first) == 80
    assert [_stable(r) for r in first] == [_stable(r) for r in second]


def test_audit_rows_values_in_range(monkeypatch):
    _, rows = _audit_rows(monkeypatch)
    user_ids = {u[0] for u in USERS}
    emails = dict(USERS)
    actions = set(seed.AUDIT_ACTIONS)
    subnet = ipaddress.ip_network("192.168.0.0/21")
    for row in rows:
        _, actor_id, actor_email, action, resource_type, resource_id, changes, ip, ua, created, updated = row
        assert emails[actor_id] == actor_email
        assert (action, resource_type) in actions
        if resource_type == "AdminUser":
            assert resource_id in user_ids
        octets = [int(p) for p in ip.split(".")]
        assert ipaddress.ip_address(ip) in subnet and 1 <= octets[2] <= 5 and 1 <= octets[3] <= 254
        assert ua == "Mozilla/5.0 (seed)" and changes == "{}" and created == updated
        assert timedelta(0) <= FROZEN_NOW - created <= timedelta(hours=30 * 24, minutes=1)


def test_no_users_skips_insert(monkeypatch):
    monkeypatch.setattr(seed, "execute_values", lambda *a, **k: pytest.fail("should not insert"))
    monkeypatch.setattr(seed, "log", lambda msg: None)
    seed.seed_audit_logs(FakeCursor([]))
