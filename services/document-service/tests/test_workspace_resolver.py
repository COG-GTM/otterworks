"""Interim workspace resolver app/services/workspace.py (OTW-43, pending OTW-42)."""

import jwt
import pytest
from starlette.requests import Request

from app.services.workspace import (
    is_workspace_owner,
    resolve_roles,
    resolve_workspace_id,
)
from tests.conftest import TEST_JWT_SECRET


def _request(claims: dict | None = None, *, secret: str = TEST_JWT_SECRET) -> Request:
    headers = []
    if claims is not None:
        token = jwt.encode(claims, secret, algorithm="HS256")
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("DEFAULT_WORKSPACE_ID", raising=False)


def test_workspace_claim_wins():
    """Given a JWT with a workspace_id claim, Then that workspace is used."""
    assert resolve_workspace_id(_request({"user_id": "u", "workspace_id": "ws-42"})) == "ws-42"


def test_falls_back_to_default():
    """Given no workspace_id claim, Then the workspace is 'default'."""
    assert resolve_workspace_id(_request({"user_id": "u"})) == "default"
    assert resolve_workspace_id(_request()) == "default"


def test_falls_back_to_env_default(monkeypatch):
    """Given DEFAULT_WORKSPACE_ID is set and no claim, Then the env value is used."""
    monkeypatch.setenv("DEFAULT_WORKSPACE_ID", "acme")
    assert resolve_workspace_id(_request({"user_id": "u"})) == "acme"


def test_forged_token_is_ignored():
    """Given a token not signed with JWT_SECRET, Then its workspace claim is ignored."""
    forged = _request({"workspace_id": "victim", "roles": ["OWNER"]}, secret="x" * 32)
    assert resolve_workspace_id(forged) == "default"
    assert not is_workspace_owner(forged)


@pytest.mark.parametrize("role", ["OWNER", "owner", "ADMIN"])
def test_owner_roles_make_workspace_owner(role):
    """Given gateway roles include the owner role, Then the caller is the workspace owner."""
    assert is_workspace_owner(_request({"user_id": "u", "roles": ["USER", role]}))


@pytest.mark.parametrize("roles", [["USER"], ["EDITOR", "USER"], [], None, "OWNER"])
def test_other_roles_are_not_workspace_owner(roles):
    """Given gateway roles without the owner role, Then the caller is not the workspace owner."""
    assert not is_workspace_owner(_request({"user_id": "u", "roles": roles}))


def test_resolve_roles_normalises_case():
    assert resolve_roles(_request({"roles": ["user", "Editor"]})) == {"USER", "EDITOR"}
