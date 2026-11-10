"""Interim workspace identity for document-service.

Until OTW-42 decides what identifies a workspace, the workspace is the
``workspace_id`` claim of the gateway-issued JWT, falling back to the
``DEFAULT_WORKSPACE_ID`` environment variable (default ``"default"``).
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from fastapi import Request

DEFAULT_WORKSPACE_ID = "default"

# Roles from auth-service's User.Role enum, carried in the JWT ``roles`` claim, that
# make a user the workspace owner.
WORKSPACE_OWNER_ROLES = frozenset({"OWNER", "ADMIN"})


def _jwt_claims(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {}
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        return {}
    try:
        claims = jwt.decode(
            auth_header[len("Bearer "):], secret, algorithms=["HS256", "HS384"]
        )
    except jwt.PyJWTError:
        return {}
    return claims if isinstance(claims, dict) else {}


def default_workspace_id() -> str:
    return os.environ.get("DEFAULT_WORKSPACE_ID") or DEFAULT_WORKSPACE_ID


def resolve_workspace_id(request: Request) -> str:
    """Return the caller's workspace id: JWT ``workspace_id`` claim, else the default."""
    workspace_id = _jwt_claims(request).get("workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        return workspace_id.strip()
    return default_workspace_id()


def resolve_roles(request: Request) -> set[str]:
    """Return the caller's JWT ``roles`` claim, upper-cased."""
    roles = _jwt_claims(request).get("roles")
    if not isinstance(roles, list):
        return set()
    return {role.upper() for role in roles if isinstance(role, str)}


def is_workspace_owner(request: Request) -> bool:
    """True when the caller holds a workspace-owner role."""
    return bool(resolve_roles(request) & WORKSPACE_OWNER_ROLES)
