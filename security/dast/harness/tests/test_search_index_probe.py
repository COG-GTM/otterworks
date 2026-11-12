"""DAST-SEARCH-INDEX-WRITE: a user token must not reach the index handlers."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probes.access_control import search_index_write  # noqa: E402
from probes.base import Verdict  # noqa: E402


@dataclass
class StubIdentity:
    user_id: str = "victim-1"


class StubContext:
    run_id = "abc123"
    plant_marker = "otterworks-dast-plant-abc123"

    def __init__(self, statuses: dict[str, int], body: str = '{"error": "forbidden"}', search=()):
        self._statuses = statuses
        self._body = body
        self._search = search
        self.attacker = StubIdentity("attacker-1")
        self.victim = StubIdentity()
        self.sent: list[tuple[str, str, object]] = []

    def request(self, method: str, path: str, *, json=None, **_: object) -> httpx.Response:
        self.sent.append((method, path, json))
        status = self._statuses.get(method, 403)
        return httpx.Response(
            status, request=httpx.Request(method, f"http://gw{path}"), text=self._body
        )

    def search_as(self, identity, query):
        return None if self._search is None else list(self._search)


def test_refused_writes_with_working_search_are_secure() -> None:
    ctx = StubContext({"POST": 403, "DELETE": 403})
    result = search_index_write(ctx)
    assert result.verdict is Verdict.SECURE
    planted = [body for method, _, body in ctx.sent if method == "POST"]
    assert all(body["owner_id"] == "victim-1" for body in planted)
    assert not any(path.endswith("/reindex") for _, path, _ in ctx.sent)


def test_an_accepted_write_is_vulnerable() -> None:
    result = search_index_write(StubContext({"POST": 201, "DELETE": 200}, body="{}"))
    assert result.verdict is Verdict.VULNERABLE


def test_a_delete_answered_by_the_handler_is_vulnerable() -> None:
    ctx = StubContext({"POST": 403, "DELETE": 404}, body='{"status": "not_found"}')
    assert search_index_write(ctx).verdict is Verdict.VULNERABLE


def test_a_router_404_is_inconclusive_not_secure() -> None:
    ctx = StubContext({"POST": 404, "DELETE": 404}, body='{"error": "not found"}')
    assert search_index_write(ctx).verdict is Verdict.INCONCLUSIVE


def test_an_unavailable_backend_is_inconclusive() -> None:
    assert search_index_write(StubContext({"POST": 502, "DELETE": 502})).verdict is (
        Verdict.INCONCLUSIVE
    )


def test_refusals_without_a_working_search_are_inconclusive() -> None:
    ctx = StubContext({"POST": 403, "DELETE": 403}, search=None)
    assert search_index_write(ctx).verdict is Verdict.INCONCLUSIVE
