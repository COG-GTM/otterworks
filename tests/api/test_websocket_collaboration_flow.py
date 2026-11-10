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


def test_socketio_two_users_join_same_document_and_presence_updates(api_client, base_url):
    user_a = api_client.register_user("ws-user-a")
    user_b = api_client.register_user("ws-user-b")
    document = api_client.create_document(
        user_a,
        title=f"WebSocket Document {api_client.run_id}",
        content="collaboration body",
    )
    document_id = document["id"]
    share_response = api_client.client.post(
        f"/api/v1/documents/{document_id}/share",
        headers=user_a.auth_headers,
    )
    assert share_response.status_code == 200, share_response.text
    share_token = share_response.json()["token"]
    received_by_b: list[dict] = []

    client_a = socketio.Client(reconnection=False, request_timeout=5)
    client_b = socketio.Client(reconnection=False, request_timeout=5)

    @client_b.on("document-update")
    def on_document_update(data):
        received_by_b.append(data)

    try:
        client_a.connect(_collab_url(base_url), auth={"token": user_a.access_token}, transports=["websocket"])
        client_b.connect(_collab_url(base_url), auth={"token": user_b.access_token}, transports=["websocket"])

        ack_a = client_a.call("join-document", {"documentId": document_id}, timeout=10)
        assert ack_a == {"success": True, "access": "write"}, ack_a
        ack_b = client_b.call(
            "join-document",
            {"documentId": document_id, "shareToken": share_token},
            timeout=10,
        )
        assert ack_b == {"success": True, "access": "read"}, ack_b
        time.sleep(0.5)

        presence_response = api_client.client.get(
            f"/api/v1/collab/documents/{document_id}/presence",
            headers=user_a.auth_headers,
        )
        assert presence_response.status_code == 200, presence_response.text

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


def test_socketio_rejects_access_to_another_users_document(api_client, base_url):
    owner = api_client.register_user("ws-owner")
    attacker = api_client.register_user("ws-attacker")
    document = api_client.create_document(
        owner,
        title=f"Private WebSocket Document {api_client.run_id}",
        content="private body",
    )
    document_id = document["id"]
    attacker_events: list[str] = []
    owner_updates: list[dict] = []

    owner_client = socketio.Client(reconnection=False, request_timeout=5)
    attacker_client = socketio.Client(reconnection=False, request_timeout=5)

    @owner_client.on("document-update")
    def on_owner_update(data):
        owner_updates.append(data)

    for event in ("sync-document", "document-history"):
        attacker_client.on(event, lambda _data, event=event: attacker_events.append(event))

    try:
        owner_client.connect(_collab_url(base_url), auth={"token": owner.access_token}, transports=["websocket"])
        attacker_client.connect(
            _collab_url(base_url), auth={"token": attacker.access_token}, transports=["websocket"]
        )
        assert owner_client.call("join-document", {"documentId": document_id}, timeout=10)["success"]

        ack = attacker_client.call("join-document", {"documentId": document_id}, timeout=10)
        assert ack == {"success": False, "error": "Access denied"}, ack
        bad_share = attacker_client.call(
            "join-document", {"documentId": document_id, "shareToken": "not-a-token"}, timeout=10
        )
        assert bad_share["success"] is False, bad_share

        attacker_client.emit("request-history", {"documentId": document_id, "limit": 50})
        attacker_client.emit("document-update", {"documentId": document_id, "update": {"text": "pwned"}})
        time.sleep(1.5)

        assert attacker_events == []
        assert owner_updates == []
    finally:
        if owner_client.connected:
            owner_client.disconnect()
        if attacker_client.connected:
            attacker_client.disconnect()
