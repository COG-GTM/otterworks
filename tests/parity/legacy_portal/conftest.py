import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from harness import CONTEXTS

TARGET_ENV = {
    "announcements": "ANNOUNCEMENTS_URL",
    "preferences": "PREFERENCES_URL",
    "feedback": "FEEDBACK_URL",
}
DEFAULT_URLS = {
    "announcements": "http://localhost:8096",
    "preferences": "http://localhost:8097",
    "feedback": "http://localhost:8098",
}
GOLDEN_DIR = Path(__file__).parent / "golden"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--record-golden",
        action="store_true",
        default=os.getenv("PARITY_RECORD") == "1",
        help="write transcripts to golden/ instead of comparing (or PARITY_RECORD=1)",
    )


def target_urls() -> dict[str, str]:
    return {
        context: os.getenv(TARGET_ENV[context], DEFAULT_URLS[context]).rstrip("/")
        for context in CONTEXTS
    }


def pytest_report_header(config: pytest.Config) -> list[str]:
    mode = "record" if config.getoption("--record-golden") else "compare"
    urls = target_urls()
    return [f"parity mode: {mode}"] + [f"  {TARGET_ENV[c]}={urls[c]}" for c in CONTEXTS]


@pytest.fixture(scope="session")
def record_golden(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("--record-golden"))


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN_DIR


def _wait_ready(client: httpx.Client, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            response = client.get("/actuator/health/readiness")
            if response.status_code == 200:
                return
            last = f"{response.status_code} {response.text[:200]}"
        except httpx.HTTPError as exc:
            last = repr(exc)
        time.sleep(1)
    pytest.exit(
        f"parity target {client.base_url} not ready after {timeout}s: {last}", 3
    )


def _require_fresh(clients: dict[str, httpx.Client]) -> None:
    """The golden transcripts assume empty tables; refuse to compare against old data."""
    problems = []
    announcements = clients["announcements"].get(
        "/api/announcements?publishedOnly=false"
    )
    if announcements.status_code != 200 or announcements.json() != []:
        problems.append(f"announcements not empty: {announcements.text[:200]}")
    average = clients["feedback"].get("/api/feedback/average-rating")
    if average.status_code != 200 or average.json() != {"averageRating": 0.0}:
        problems.append(f"feedback not empty: {average.text[:200]}")
    stored = clients["preferences"].get("/api/preferences/pref-alice")
    if stored.status_code != 200 or stored.json().get("theme") != "light":
        problems.append(f"preferences already written: {stored.text[:200]}")
    if problems:
        pytest.exit(
            "parity target is not freshly started (restart the JVM for H2, "
            "`make portal-reset` for the compose stack): " + "; ".join(problems),
            3,
        )


@pytest.fixture(scope="session")
def clients() -> Iterator[dict[str, httpx.Client]]:
    timeout = float(os.getenv("PARITY_READY_TIMEOUT", "120"))
    urls = target_urls()
    opened = {
        context: httpx.Client(
            base_url=urls[context], timeout=30.0, follow_redirects=False
        )
        for context in CONTEXTS
    }
    try:
        for client in opened.values():
            _wait_ready(client, timeout)
        _require_fresh(opened)
        yield opened
    finally:
        for client in opened.values():
            client.close()
