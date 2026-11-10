"""Workspace owner check (v1: one tenant deployment = one workspace)."""

import os
from uuid import UUID

import jwt
from fastapi import Request

from app.config import settings

# Roles auth-service puts in the JWT ``roles`` claim for privileged users.
WORKSPACE_OWNER_ROLES = frozenset({"OWNER", "ADMIN"})


def _owner_allowlist() -> set[str]:
    return {
        value.strip().lower()
        for value in settings.share_policy_owner_ids.split(",")
        if value.strip()
    }


def _jwt_roles(request: Request) -> set[str]:
    auth_header = request.headers.get("Authorization", "")
    secret = os.environ.get("JWT_SECRET", "")
    if not secret or not auth_header.startswith("Bearer "):
        return set()
    try:
        payload = jwt.decode(
            auth_header[len("Bearer "):], secret, algorithms=["HS256", "HS384"]
        )
    except jwt.PyJWTError:
        return set()
    roles = payload.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return {str(role).upper().removeprefix("ROLE_") for role in roles}


def is_workspace_owner(request: Request, user_id: UUID) -> bool:
    """True for users in SHARE_POLICY_OWNER_IDS or whose JWT carries an owner role."""
    if str(user_id).lower() in _owner_allowlist():
        return True
    return bool(_jwt_roles(request) & WORKSPACE_OWNER_ROLES)
