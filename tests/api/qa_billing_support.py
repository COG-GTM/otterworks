"""Helpers for the billing QA functional tests (kept out of the shared conftest).

billing services are not routed through the API gateway, so these tests talk to the
procs stack (`make procs-up NS=dev`) and the legacy portal (`java -jar` on :8095) directly.
"""

from __future__ import annotations

import os

import httpx
import pytest

LEGACY_BILLING_URL = os.getenv("QA_LEGACY_BILLING_URL", "http://localhost:8109")
BILLING_SERVICE_URL = os.getenv("QA_BILLING_SERVICE_URL", "http://localhost:12109")
LEGACY_PORTAL_URL = os.getenv("QA_LEGACY_PORTAL_URL", "http://localhost:8095")

TENANT = {n: f"00000000-0000-0000-0000-00000000000{n}" for n in range(1, 10)}
UNKNOWN_TENANT = "00000000-0000-0000-0000-0000000000ff"
STARTER = "10000000-0000-0000-0000-000000000001"
GROWTH = "10000000-0000-0000-0000-000000000002"
SCALE = "10000000-0000-0000-0000-000000000003"


def service_client(url: str, health_path: str = "/health") -> httpx.Client:
    client = httpx.Client(base_url=url, timeout=10.0)
    try:
        response = client.get(health_path)
    except httpx.HTTPError as error:
        client.close()
        pytest.skip(f"{url} unreachable: {error}")
    if response.status_code != 200:
        client.close()
        pytest.skip(f"{url}{health_path} returned {response.status_code}")
    return client
