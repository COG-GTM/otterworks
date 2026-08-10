"""What the scan records about itself, which is what the coverage gate grades."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dast_scan import request_recorder  # noqa: E402


def send(record, method: str, url: str, **kwargs) -> None:
    record(httpx.Request(method, url, **kwargs))


def test_requests_are_recorded_with_the_identity_that_made_them() -> None:
    exercised, record = request_recorder("http://localhost:8080")
    send(record, "GET", "http://localhost:8080/api/v1/documents")
    send(
        record,
        "GET",
        "http://localhost:8080/api/v1/documents",
        headers={"Authorization": "Bearer x"},
    )
    send(record, "GET", "http://localhost:8080/api/v1/documents")  # duplicate
    assert exercised == [
        {"method": "GET", "path": "/api/v1/documents", "authenticated": False},
        {"method": "GET", "path": "/api/v1/documents", "authenticated": True},
    ]


def test_a_request_to_another_origin_is_not_edge_coverage() -> None:
    """The direct-backend probe leaves the gateway on purpose; that is not coverage."""
    exercised, record = request_recorder("http://localhost:8080")
    send(record, "GET", "http://localhost:8082/api/v1/files")
    assert exercised == []


def test_a_path_routed_target_records_the_route_the_service_declares() -> None:
    """Without a tenant DNS zone the target is `<host>/<tenant>`; the route is not."""
    exercised, record = request_recorder("https://nlb.example.test/t-abc")
    send(record, "GET", "https://nlb.example.test/t-abc/api/v1/documents")
    send(record, "GET", "https://nlb.example.test/t-other/api/v1/documents")
    assert exercised == [{"method": "GET", "path": "/api/v1/documents", "authenticated": False}]
