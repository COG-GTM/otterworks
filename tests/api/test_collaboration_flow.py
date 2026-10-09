import pytest


pytestmark = pytest.mark.api_flow


def test_collaboration_presence_endpoints(api_client):
    user = api_client.register_user("collab-flow")
    document_response = api_client.client.post(
        "/api/v1/documents/",
        headers=user.auth_headers,
        json={"title": f"Collab Doc {api_client.run_id}", "content": "collab body"},
    )
    assert document_response.status_code == 201, document_response.text
    document_id = document_response.json()["id"]

    active_documents_response = api_client.client.get(
        "/api/v1/collab/documents",
        headers=user.auth_headers,
    )
    assert active_documents_response.status_code == 403, active_documents_response.text

    presence_response = api_client.client.get(
        f"/api/v1/collab/documents/{document_id}/presence",
        headers=user.auth_headers,
    )
    assert presence_response.status_code == 200, presence_response.text
    assert presence_response.json()["documentId"] == document_id

    other_user = api_client.register_user("collab-other")
    other_presence_response = api_client.client.get(
        f"/api/v1/collab/documents/{document_id}/presence",
        headers=other_user.auth_headers,
    )
    assert other_presence_response.status_code == 403, other_presence_response.text


def test_collaboration_invalid_document_presence_is_stable(api_client):
    user = api_client.register_user("collab-validation")

    presence_response = api_client.client.get(
        "/api/v1/collab/documents/not-a-real-document/presence",
        headers=user.auth_headers,
    )
    assert presence_response.status_code == 400, presence_response.text
