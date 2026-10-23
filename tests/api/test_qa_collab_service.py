"""QA black-box tests for collab-service (Socket.IO + y-websocket + presence HTTP).

Socket.IO and /api/v1/collab are exercised through the API gateway. The y-websocket
upgrade path and the raw presence endpoints are not routed by the gateway, so those
tests hit the service port directly (OTTERWORKS_COLLAB_DIRECT_URL, default :8084).

Findings referenced in xfail reasons are documented in docs/qa/collab-service.md.
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import socketio
import websocket


pytestmark = [pytest.mark.api_flow, pytest.mark.websocket]

DIRECT_URL = os.getenv("OTTERWORKS_COLLAB_DIRECT_URL", "http://localhost:8084").rstrip("/")

# Yjs v1 updates (Y.Doc().getText("content").insert(0, ...)) from distinct client ids,
# generated with yjs 13 so this suite needs no Yjs runtime.
UPDATE_ALPHA = "AQHpBwAEAQdjb250ZW50DVFBLUFMUEhBLUVESVQA"  # "QA-ALPHA-EDIT"
UPDATE_BRAVO = "AQHSDwAEAQdjb250ZW50DVFBLUJSQVZPLUVESVQA"  # "QA-BRAVO-EDIT"
UPDATE_MALLORY = "AQG7FwAEAQdjb250ZW50EHB3bmVkLWJ5LW1hbGxvcnkA"  # "pwned-by-mallory"
CORRUPT_UPDATE = "//8AAQ=="


def _ws_url(base_url: str) -> str:
    return os.getenv("OTTERWORKS_COLLAB_WS_URL", base_url.replace("http://", "ws://").replace("https://", "wss://"))


def _state_text(state_b64: str) -> str:
    return base64.b64decode(state_b64).decode("utf-8", errors="replace")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forge_token(claims: dict[str, Any], secret: str | None, alg: str = "HS256") -> str:
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    if secret is None:
        return f"{header}.{payload}."
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


class CollabClient:
    """socketio.Client wrapper that records every event it receives."""

    def __init__(self, url: str, token: str | None):
        self.url = url
        self.token = token
        self.events: dict[str, list[Any]] = {}
        self._lock = threading.Lock()
        self.sio = socketio.Client(reconnection=False, request_timeout=5)
        self.sio.on("*", self._record)

    def _record(self, event: str, data: Any = None) -> None:
        with self._lock:
            self.events.setdefault(event, []).append(data)

    def connect(self) -> "CollabClient":
        auth = {"token": self.token} if self.token is not None else None
        self.sio.connect(self.url, auth=auth, transports=["websocket"], wait_timeout=5)
        return self

    def join(self, document_id: Any) -> Any:
        return self.sio.call("join-document", {"documentId": document_id}, timeout=5)

    def emit(self, event: str, data: Any = None) -> None:
        self.sio.emit(event, data)

    def received(self, event: str) -> list[Any]:
        with self._lock:
            return list(self.events.get(event, []))

    def wait_for(
        self,
        event: str,
        predicate: Callable[[Any], bool] = lambda _: True,
        timeout: float = 5.0,
    ) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for item in self.received(event):
                if predicate(item):
                    return item
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {event!r}; got {self.events!r}")

    def assert_silent(self, event: str, seconds: float = 0.75) -> None:
        time.sleep(seconds)
        assert self.received(event) == [], f"unexpected {event!r}: {self.received(event)!r}"

    def disconnect(self) -> None:
        if self.sio.connected:
            self.sio.disconnect()


@pytest.fixture
def collab(base_url: str) -> Iterator[Callable[[str | None], CollabClient]]:
    clients: list[CollabClient] = []

    def factory(token: str | None) -> CollabClient:
        client = CollabClient(_ws_url(base_url), token)
        clients.append(client)
        return client.connect()

    yield factory
    for client in clients:
        client.disconnect()


@pytest.fixture
def owner(api_client):
    return api_client.register_user("qa-collab-owner")


@pytest.fixture
def document(api_client, owner) -> dict[str, Any]:
    return api_client.create_document(owner, title=f"QA collab {api_client.run_id}", content="qa body")


def _direct_reachable() -> bool:
    try:
        return httpx.get(f"{DIRECT_URL}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


requires_direct = pytest.mark.skipif(not _direct_reachable(), reason=f"collab-service not reachable at {DIRECT_URL}")


# --- HTTP surface through the gateway -------------------------------------------------


def test_gateway_requires_auth_for_collab_http_routes(api_client):
    for path in ("/api/v1/collab/documents", f"/api/v1/collab/documents/{uuid.uuid4()}/presence"):
        response = api_client.client.get(path)
        assert response.status_code == 401, (path, response.text)


def test_gateway_presence_for_unknown_document_is_empty(api_client, owner):
    document_id = str(uuid.uuid4())
    response = api_client.client.get(f"/api/v1/collab/documents/{document_id}/presence", headers=owner.auth_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"documentId": document_id, "users": [], "count": 0}


def test_gateway_active_documents_lists_joined_document(api_client, owner, document, collab):
    client = collab(owner.access_token)
    assert client.join(document["id"]) == {"success": True}
    response = api_client.client.get("/api/v1/collab/documents", headers=owner.auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == len(body["documents"])
    assert {"documentId": document["id"], "userCount": 1} in body["documents"]


# --- Socket.IO authentication ----------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        None,
        "not-a-jwt",
        _forge_token({"sub": "attacker", "exp": int(time.time()) + 600}, "wrong-secret"),
        _forge_token({"sub": "attacker", "exp": int(time.time()) + 600}, None, alg="none"),
    ],
    ids=["missing", "malformed", "wrong-secret", "alg-none"],
)
def test_socketio_rejects_bad_credentials(base_url, token):
    client = CollabClient(_ws_url(base_url), token)
    with pytest.raises(socketio.exceptions.ConnectionError):
        client.connect()


def test_socketio_accepts_access_token_from_auth_service(owner, collab):
    assert collab(owner.access_token).sio.connected


@pytest.mark.xfail(strict=True, reason="COLLAB-04: refresh tokens (type=refresh) are accepted as websocket credentials")
def test_socketio_rejects_refresh_token(base_url, owner):
    client = CollabClient(_ws_url(base_url), owner.refresh_token)
    try:
        with pytest.raises(socketio.exceptions.ConnectionError):
            client.connect()
    finally:
        client.disconnect()


# --- Join / presence / leave -----------------------------------------------------------


def test_join_acks_and_syncs_state_and_presence(api_client, owner, document, collab):
    client = collab(owner.access_token)
    assert client.join(document["id"]) == {"success": True}
    sync = client.wait_for("sync-document")
    assert sync["documentId"] == document["id"]
    presence = client.wait_for("presence-update", lambda p: p["count"] == 1)
    assert presence["users"][0]["userId"] == owner.id
    assert presence["users"][0]["displayName"] == owner.display_name

    http = api_client.client.get(f"/api/v1/collab/documents/{document['id']}/presence", headers=owner.auth_headers)
    assert http.status_code == 200, http.text
    assert [u["userId"] for u in http.json()["users"]] == [owner.id]


def test_two_windows_see_each_other_join_and_leave(api_client, owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])

    joined = window_a.wait_for("user-joined")
    assert joined["userId"] == owner.id
    assert joined["color"].startswith("#")
    window_a.wait_for("presence-update", lambda p: p["count"] == 2)

    window_b.emit("leave-document", {"documentId": document["id"]})
    left = window_a.wait_for("user-left")
    assert left["socketId"] != window_a.sio.sid
    window_a.wait_for("presence-update", lambda p: p["count"] == 1)


def test_disconnect_updates_presence_for_remaining_window(api_client, owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])
    window_a.wait_for("presence-update", lambda p: p["count"] == 2)

    window_b.disconnect()
    window_a.wait_for("user-left")
    api_client.poll_until(
        lambda: api_client.client.get(
            f"/api/v1/collab/documents/{document['id']}/presence", headers=owner.auth_headers
        ).json(),
        lambda body: body["count"] == 1,
        timeout_seconds=5,
        interval_seconds=0.2,
        description="presence count drops to 1 after disconnect",
    )


# --- CRDT fan-out / reconnect / persistence -------------------------------------------


def test_yjs_updates_fan_out_in_both_directions(owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])

    window_a.emit("document-update", {"documentId": document["id"], "update": UPDATE_ALPHA})
    at_b = window_b.wait_for("document-update")
    assert at_b == {"documentId": document["id"], "update": UPDATE_ALPHA}

    window_b.emit("document-update", {"documentId": document["id"], "update": UPDATE_BRAVO})
    at_a = window_a.wait_for("document-update")
    assert at_a["update"] == UPDATE_BRAVO

    assert all(u["update"] != UPDATE_ALPHA for u in window_a.received("document-update")), "sender got its own echo"


def test_reconnecting_window_receives_merged_state(owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])
    window_a.emit("document-update", {"documentId": document["id"], "update": UPDATE_ALPHA})
    window_b.wait_for("document-update")

    window_b.disconnect()
    window_a.emit("document-update", {"documentId": document["id"], "update": UPDATE_BRAVO})
    time.sleep(0.3)

    rejoined = collab(owner.access_token)
    rejoined.join(document["id"])
    state = _state_text(rejoined.wait_for("sync-document")["state"])
    assert "QA-ALPHA-EDIT" in state
    assert "QA-BRAVO-EDIT" in state


def test_state_survives_room_eviction_via_redis(owner, document, collab):
    window = collab(owner.access_token)
    window.join(document["id"])
    window.emit("document-update", {"documentId": document["id"], "update": UPDATE_ALPHA})
    time.sleep(0.3)
    window.disconnect()
    time.sleep(1.0)  # last member leaving persists to Redis and evicts the in-memory Y.Doc

    fresh = collab(owner.access_token)
    fresh.join(document["id"])
    assert "QA-ALPHA-EDIT" in _state_text(fresh.wait_for("sync-document")["state"])


def test_corrupt_update_is_rejected_without_fan_out(owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])

    window_a.emit("document-update", {"documentId": document["id"], "update": CORRUPT_UPDATE})
    error = window_a.wait_for("document-update-error")
    assert error == {"documentId": document["id"], "error": "Failed to apply update"}
    window_b.assert_silent("document-update")


def test_cursor_and_typing_carry_server_side_identity(owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])

    window_a.emit(
        "cursor-update",
        {"documentId": document["id"], "cursor": {"index": 3, "length": 0}, "selection": None},
    )
    cursor = window_b.wait_for("cursor-update")
    assert cursor["userId"] == owner.id
    assert cursor["cursor"] == {"index": 3, "length": 0}

    window_a.emit("typing-indicator", {"documentId": document["id"], "isTyping": True})
    assert window_b.wait_for("typing-indicator")["isTyping"] is True


def test_comment_author_is_taken_from_token(owner, document, collab):
    window_a = collab(owner.access_token)
    window_b = collab(owner.access_token)
    window_a.join(document["id"])
    window_b.join(document["id"])
    window_a.emit(
        "comment-add",
        {
            "documentId": document["id"],
            "comment": {"id": "c1", "content": "hi", "author": {"userId": "spoofed", "displayName": "Spoof"}},
        },
    )
    comment = window_b.wait_for("comment-added")
    assert comment["author"]["userId"] == owner.id


def test_snapshot_then_history_round_trip(owner, document, collab):
    window = collab(owner.access_token)
    window.join(document["id"])
    window.emit("document-update", {"documentId": document["id"], "update": UPDATE_ALPHA})
    window.emit("request-snapshot", {"documentId": document["id"], "label": "qa-v1"})
    snapshot = window.wait_for("snapshot-created")
    assert snapshot["label"] == "qa-v1"
    assert snapshot["createdBy"] == owner.id

    window.emit("request-history", {"documentId": document["id"], "limit": 5})
    history = window.wait_for("document-history")
    assert snapshot["id"] in [s["id"] for s in history["snapshots"]]


def test_snapshot_for_unjoined_document_errors(owner, collab):
    window = collab(owner.access_token)
    window.emit("request-snapshot", {"documentId": str(uuid.uuid4())})
    assert window.wait_for("snapshot-error")["error"] == "Document not found"


# --- Authorization / isolation (documented findings) ---------------------------------


def test_non_owner_cannot_read_document_over_rest(api_client, document):
    stranger = api_client.register_user("qa-collab-stranger")
    response = api_client.client.get(f"/api/v1/documents/{document['id']}", headers=stranger.auth_headers)
    assert response.status_code in (403, 404), response.text


@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-06: join-document has no document-level authorization; a user denied by document-service "
    "can join the room and read the live CRDT state",
)
def test_non_owner_cannot_join_document_room(api_client, owner, document, collab):
    window = collab(owner.access_token)
    window.join(document["id"])
    window.emit("document-update", {"documentId": document["id"], "update": UPDATE_ALPHA})
    time.sleep(0.3)

    stranger = api_client.register_user("qa-collab-stranger")
    intruder = collab(stranger.access_token)
    ack = intruder.join(document["id"])
    time.sleep(0.5)
    leaked = [s for s in intruder.received("sync-document") if "QA-ALPHA-EDIT" in _state_text(s["state"])]
    assert ack.get("success") is False and leaked == []


@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-02: document-update fans out to doc:<id> without checking the sender joined that room",
)
def test_non_member_cannot_inject_updates(api_client, owner, document, collab):
    window = collab(owner.access_token)
    window.join(document["id"])
    stranger = api_client.register_user("qa-collab-mallory")
    mallory = collab(stranger.access_token)
    mallory.emit("document-update", {"documentId": document["id"], "update": UPDATE_MALLORY})
    window.assert_silent("document-update")


@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-02: comment-add/comment-delete are broadcast to any client-supplied documentId",
)
def test_non_member_cannot_broadcast_comments(api_client, owner, document, collab):
    window = collab(owner.access_token)
    window.join(document["id"])
    stranger = api_client.register_user("qa-collab-mallory")
    mallory = collab(stranger.access_token)
    mallory.emit("comment-delete", {"documentId": document["id"], "commentId": "victim-comment"})
    window.assert_silent("comment-deleted")


@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-03: request-history returns snapshot state for any documentId without membership checks",
)
def test_non_member_cannot_read_history(api_client, owner, document, collab):
    window = collab(owner.access_token)
    window.join(document["id"])
    window.emit("document-update", {"documentId": document["id"], "update": UPDATE_ALPHA})
    window.emit("request-snapshot", {"documentId": document["id"]})
    window.wait_for("snapshot-created")

    stranger = api_client.register_user("qa-collab-mallory")
    mallory = collab(stranger.access_token)
    mallory.emit("request-history", {"documentId": document["id"]})
    mallory.assert_silent("document-history", seconds=1.0)


@pytest.mark.skipif(
    os.getenv("OTTERWORKS_QA_DESTRUCTIVE") != "1",
    reason="COLLAB-01: a payload-less join-document crashes collab-service (process exit); "
    "set OTTERWORKS_QA_DESTRUCTIVE=1 to reproduce",
)
@pytest.mark.xfail(strict=True, reason="COLLAB-01: payload-less socket events crash the collab-service process")
def test_payloadless_event_does_not_crash_service(api_client, owner, collab):
    client = collab(owner.access_token)
    client.emit("join-document")
    time.sleep(2.0)
    response = api_client.client.get("/api/v1/collab/documents", headers=owner.auth_headers)
    assert response.status_code == 200, response.text


# --- Direct service port (not routed by the gateway) ---------------------------------


@requires_direct
def test_direct_health_reports_redis_connected():
    body = httpx.get(f"{DIRECT_URL}/health", timeout=5).json()
    assert body["service"] == "collab-service"
    assert body["status"] == "healthy"
    assert body["redis"] == "connected"


@requires_direct
@pytest.mark.gap_revealer
@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-07: presence HTTP endpoints have no auth on the service port and expose user ids/emails",
)
def test_direct_presence_endpoint_requires_auth(owner, document, collab):
    collab(owner.access_token).join(document["id"])
    response = httpx.get(f"{DIRECT_URL}/api/v1/collab/documents/{document['id']}/presence", timeout=5)
    assert response.status_code == 401, response.text


def _yws_url(document_id: str, token: str | None) -> str:
    url = DIRECT_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/document-{document_id}"
    return f"{url}?token={token}" if token is not None else url


@requires_direct
@pytest.mark.parametrize("token", [None, "not-a-jwt"], ids=["missing", "invalid"])
def test_y_websocket_rejects_bad_tokens(token):
    with pytest.raises(websocket.WebSocketBadStatusException) as exc:
        websocket.create_connection(_yws_url(str(uuid.uuid4()), token), timeout=5)
    assert exc.value.status_code == 401


@requires_direct
def test_y_websocket_accepts_valid_token_and_sends_sync_step(owner, document):
    ws = websocket.create_connection(_yws_url(document["id"], owner.access_token), timeout=5)
    try:
        frame = ws.recv()
        assert isinstance(frame, bytes) and frame[:2] == b"\x00\x00"  # messageSync / syncStep1
    finally:
        ws.close()


@requires_direct
@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-06: the y-websocket path (used by the web editor) only verifies the JWT, not document access",
)
def test_y_websocket_rejects_non_owner(api_client, document):
    stranger = api_client.register_user("qa-collab-stranger")
    with pytest.raises(websocket.WebSocketBadStatusException):
        ws = websocket.create_connection(_yws_url(document["id"], stranger.access_token), timeout=5)
        ws.close()


@requires_direct
@pytest.mark.xfail(
    strict=True,
    reason="COLLAB-08: y-websocket connections bypass AwarenessService, so presence never reflects web editors",
)
def test_presence_reflects_y_websocket_editors(owner, document):
    ws = websocket.create_connection(_yws_url(document["id"], owner.access_token), timeout=5)
    try:
        ws.recv()
        time.sleep(0.5)
        body = httpx.get(f"{DIRECT_URL}/api/v1/collab/documents/{document['id']}/presence", timeout=5).json()
        assert body["count"] >= 1
    finally:
        ws.close()
