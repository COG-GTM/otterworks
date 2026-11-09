import os
import time

import pytest
import socketio


pytestmark = [pytest.mark.api_flow, pytest.mark.websocket]


def _collab_url(base_url: str) -> str:
    return os.getenv("OTTERWORKS_COLLAB_WS_URL", base_url.replace("http://", "ws://").replace("https://", "wss://"))


def test_socketio_rejects_missing_or_invalid_token(base_url):
    sio = socketio.Client(reconnection=False, request_timeout=3)
    with pytest.raises(socketio.exceptions.ConnectionError):
        sio.connect(_collab_url(base_url), transports=["websocket"])

    invalid = socketio.Client(reconnection=False, request_timeout=3)
    with pytest.raises(socketio.exceptions.ConnectionError):
        invalid.connect(
            _collab_url(base_url),
            auth={"token": "not-a-valid-token"},
            transports=["websocket"],
        )


def _join(client: socketio.Client, document_id: str) -> dict:
    return client.call("join-document", {"documentId": document_id}, timeout=5)


def test_socketio_owner_sessions_join_same_document_and_presence_updates(api_client, base_url):
    # Documents are owner-only in document-service, so collaborate across two sessions of the owner.
    owner = api_client.register_user("ws-owner")
    document = api_client.create_document(
        owner,
        title=f"WebSocket Document {api_client.run_id}",
        content="collaboration body",
    )
    document_id = document["id"]
    received_by_b: list[dict] = []

    client_a = socketio.Client(reconnection=False, request_timeout=5)
    client_b = socketio.Client(reconnection=False, request_timeout=5)

    @client_b.on("document-update")
    def on_document_update(data):
        received_by_b.append(data)

    try:
        client_a.connect(_collab_url(base_url), auth={"token": owner.access_token}, transports=["websocket"])
        client_b.connect(_collab_url(base_url), auth={"token": owner.access_token}, transports=["websocket"])

        assert _join(client_a, document_id) == {"success": True}
        assert _join(client_b, document_id) == {"success": True}

        presence_response = api_client.client.get(
            f"/api/v1/collab/documents/{document_id}/presence",
            headers=owner.auth_headers,
        )
        assert presence_response.status_code == 200, presence_response.text
        assert presence_response.json()["count"] == 2

        client_a.emit(
            "document-update",
            {"documentId": document_id, "update": {"text": f"hello {api_client.run_id}"}},
        )

        api_client.poll_until(
            lambda: received_by_b,
            lambda updates: len(updates) >= 1,
            timeout_seconds=10,
            interval_seconds=0.25,
            description="collaboration update fanout to second socket client",
        )
    finally:
        if client_a.connected:
            client_a.disconnect()
        if client_b.connected:
            client_b.disconnect()


def test_socketio_rejects_non_owner_join_and_updates(api_client, base_url):
    owner = api_client.register_user("ws-owner")
    intruder = api_client.register_user("ws-intruder")
    document = api_client.create_document(
        owner,
        title=f"Private WebSocket Document {api_client.run_id}",
        content="confidential body",
    )
    document_id = document["id"]
    received_by_owner: list[dict] = []
    synced_by_intruder: list[dict] = []
    intruder_errors: list[dict] = []

    owner_client = socketio.Client(reconnection=False, request_timeout=5)
    intruder_client = socketio.Client(reconnection=False, request_timeout=5)

    @owner_client.on("document-update")
    def on_owner_update(data):
        received_by_owner.append(data)

    @intruder_client.on("sync-document")
    def on_intruder_sync(data):
        synced_by_intruder.append(data)

    @intruder_client.on("document-update-error")
    def on_intruder_error(data):
        intruder_errors.append(data)

    try:
        owner_client.connect(_collab_url(base_url), auth={"token": owner.access_token}, transports=["websocket"])
        intruder_client.connect(
            _collab_url(base_url), auth={"token": intruder.access_token}, transports=["websocket"]
        )

        assert _join(owner_client, document_id) == {"success": True}
        assert _join(intruder_client, document_id) == {"success": False, "error": "Access denied"}

        intruder_client.emit(
            "document-update",
            {"documentId": document_id, "update": {"text": "overwritten"}},
        )
        api_client.poll_until(
            lambda: intruder_errors,
            lambda errors: len(errors) >= 1,
            timeout_seconds=5,
            interval_seconds=0.25,
            description="document-update rejection for non-member socket",
        )
        time.sleep(0.5)
        assert received_by_owner == []
        assert synced_by_intruder == []

        presence_response = api_client.client.get(
            f"/api/v1/collab/documents/{document_id}/presence",
            headers=intruder.auth_headers,
        )
        assert presence_response.status_code == 404, presence_response.text

        active_response = api_client.client.get("/api/v1/collab/documents", headers=intruder.auth_headers)
        assert active_response.status_code == 200, active_response.text
        assert document_id not in {d["documentId"] for d in active_response.json()["documents"]}
    finally:
        if owner_client.connected:
            owner_client.disconnect()
        if intruder_client.connected:
            intruder_client.disconnect()
