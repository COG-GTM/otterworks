import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest


DEFAULT_GATEWAY_URL = "http://localhost:8080"
# Local docker compose defaults (docker-compose.infra.yml). Used only when the suite targets
# the default local gateway; any other environment must opt in with the env vars below.
DEFAULT_LOCAL_DATABASE_URL = "postgresql://otterworks:otterworks_dev@localhost:5432/otterworks"
DEFAULT_LOCAL_S3_ENDPOINT = "http://localhost:4566"


@dataclass(frozen=True)
class RegisteredUser:
    email: str
    password: str
    display_name: str
    id: str
    access_token: str
    refresh_token: str

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


class ApiClient:
    def __init__(self, client: httpx.Client, run_id: str):
        self.client = client
        self.run_id = run_id
        self.created_documents: list[str] = []
        self.created_files: list[str] = []
        self.created_folders: list[str] = []
        self.created_reports: list[str] = []
        self.indexed_documents: list[str] = []
        self.indexed_files: list[str] = []

    def unique_email(self, prefix: str) -> str:
        return f"{prefix}-{self.run_id}-{uuid.uuid4().hex[:8]}@example.test"

    def register_user(self, prefix: str = "api-flow-user") -> RegisteredUser:
        password = "OtterworksTest123!"
        payload = {
            "email": self.unique_email(prefix),
            "password": password,
            "displayName": f"{prefix} {self.run_id}",
        }
        response = self.client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 201, response.text
        data = response.json()
        user = data["user"]
        return RegisteredUser(
            email=payload["email"],
            password=password,
            display_name=payload["displayName"],
            id=user["id"],
            access_token=data["accessToken"],
            refresh_token=data["refreshToken"],
        )

    def login_user(self, user: RegisteredUser) -> dict:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": user.password},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def wait_for_gateway(self) -> None:
        deadline = time.monotonic() + float(os.getenv("OTTERWORKS_API_READY_TIMEOUT", "5"))
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = self.client.get("/health")
                if response.status_code < 500:
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.25)
        pytest.skip(f"OtterWorks API gateway is not reachable: {last_error}")

    def iso_time(self, days_offset: int = 0) -> str:
        return (datetime.now(UTC) + timedelta(days=days_offset)).isoformat()

    def assert_gateway_route_available(self, response: httpx.Response, route: str) -> None:
        assert response.status_code != 404, (
            f"{route} is not routed through the API gateway: {response.text}"
        )

    def assert_json_error(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type, response.text
        body = response.json()
        assert any(key in body for key in ("error", "detail", "message")), body
        forbidden_fragments = ("Traceback", "Exception", "stack", "password", "secret")
        assert not any(fragment in response.text for fragment in forbidden_fragments)
        return body

    def poll_until(
        self,
        probe: Callable[[], Any],
        predicate: Callable[[Any], bool] = bool,
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        description: str = "condition",
    ) -> Any:
        timeout = timeout_seconds or float(os.getenv("OTTERWORKS_API_POLL_TIMEOUT", "30"))
        interval = interval_seconds or float(os.getenv("OTTERWORKS_API_POLL_INTERVAL", "0.5"))
        deadline = time.monotonic() + timeout
        last_value: Any = None
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                last_value = probe()
                if predicate(last_value):
                    return last_value
            except Exception as exc:
                last_error = exc
            time.sleep(interval)
        raise AssertionError(
            f"Timed out waiting for {description}; last_value={last_value!r}; last_error={last_error!r}"
        )

    def create_document(self, user: RegisteredUser, title: str, content: str) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/documents/",
            headers=user.auth_headers,
            json={"title": title, "content": content},
        )
        assert response.status_code == 201, response.text
        document = response.json()
        self.created_documents.append(document["id"])
        return document

    def create_folder(self, user: RegisteredUser, name: str) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/folders",
            headers=user.auth_headers,
            json={"name": name, "owner_id": user.id},
        )
        assert response.status_code == 201, response.text
        folder = response.json()
        self.created_folders.append(folder["id"])
        return folder

    def upload_file(
        self, user: RegisteredUser, folder_id: str, name: str, content: bytes
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/v1/files/upload",
            headers=user.auth_headers,
            files={"file": (name, content, "text/plain")},
            data={"folder_id": folder_id},
        )
        assert response.status_code == 201, response.text
        file_metadata = response.json()["file"]
        self.created_files.append(file_metadata["id"])
        return file_metadata

    def login_as(self, user: RegisteredUser) -> RegisteredUser:
        """Log in again so the access token carries the user's current roles."""
        data = self.login_user(user)
        return RegisteredUser(
            email=user.email,
            password=user.password,
            display_name=user.display_name,
            id=user.id,
            access_token=data["accessToken"],
            refresh_token=data["refreshToken"],
        )

    def cleanup(self) -> None:
        for report_id in reversed(self.created_reports):
            self.client.delete(f"/api/v1/reports/{report_id}")
        for document_id in reversed(self.indexed_documents):
            self.client.delete(f"/api/v1/search/index/document/{document_id}")
        for file_id in reversed(self.indexed_files):
            self.client.delete(f"/api/v1/search/index/file/{file_id}")
        for file_id in reversed(self.created_files):
            self.client.delete(f"/api/v1/files/{file_id}")
        for document_id in reversed(self.created_documents):
            self.client.delete(f"/api/v1/documents/{document_id}")
        for folder_id in reversed(self.created_folders):
            self.client.delete(f"/api/v1/folders/{folder_id}")


@pytest.fixture(scope="session")
def base_url() -> str:
    return os.getenv("OTTERWORKS_API_BASE_URL", DEFAULT_GATEWAY_URL).rstrip("/")


@pytest.fixture(scope="session")
def run_id() -> str:
    return os.getenv("OTTERWORKS_API_TEST_RUN_ID", uuid.uuid4().hex[:10])


def _is_local_gateway(base_url: str) -> bool:
    return base_url == DEFAULT_GATEWAY_URL


@pytest.fixture(scope="session")
def database_url(base_url: str) -> str | None:
    """Postgres DSN shared by auth-service and document-service, or None when unknown.

    Defaults to the local docker compose database only when the suite targets the local
    gateway, so a run against another environment never writes to a local database.
    """
    explicit = os.getenv("OTTERWORKS_API_DATABASE_URL")
    if explicit:
        return explicit
    return DEFAULT_LOCAL_DATABASE_URL if _is_local_gateway(base_url) else None


@pytest.fixture(scope="session")
def s3_endpoint(base_url: str) -> str | None:
    """S3 endpoint (LocalStack locally) where audit-service writes exports, or None."""
    explicit = os.getenv("OTTERWORKS_API_S3_ENDPOINT")
    if explicit:
        return explicit.rstrip("/")
    return DEFAULT_LOCAL_S3_ENDPOINT if _is_local_gateway(base_url) else None


@pytest.fixture
def otterworks_db(database_url: str | None) -> Iterator[Any]:
    """Direct, autocommit connection to the services' Postgres database.

    Only for test setup the public API intentionally cannot do (granting the workspace-owner
    role, back-dating a link's expiry). Skips when no database is configured or reachable.
    """
    if not database_url:
        pytest.skip(
            "No database access: set OTTERWORKS_API_DATABASE_URL to run tests that need "
            "direct database setup against a non-local gateway"
        )
    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg is not installed (pip install -r tests/api/requirements.txt)")
    try:
        connection = psycopg.connect(database_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"OtterWorks database is not reachable at OTTERWORKS_API_DATABASE_URL: {exc}")
    with connection:
        yield connection


@pytest.fixture
def api_client(base_url: str, run_id: str) -> Iterator[ApiClient]:
    timeout = httpx.Timeout(15.0, connect=3.0)
    with httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=False) as client:
        api = ApiClient(client, run_id)
        api.wait_for_gateway()
        try:
            yield api
        finally:
            api.cleanup()
