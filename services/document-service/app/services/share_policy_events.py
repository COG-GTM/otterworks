"""Hook point for workspace share-policy change events (OTW-46).

Sends ``workspace_share_policy_changed`` to audit-service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.services.audit_events import build_audit_payload, publish_audit_event
from app.services.share_link_repository import EffectiveSharePolicy

WORKSPACE_SHARE_POLICY_CHANGED = "workspace_share_policy_changed"


def _policy_value(policy: EffectiveSharePolicy) -> dict[str, int]:
    return {"default_days": policy.default_days, "max_days": policy.max_days}


async def emit_policy_changed_event(
    old: EffectiveSharePolicy,
    new: EffectiveSharePolicy,
    *,
    actor_id: uuid.UUID,
    workspace_id: str,
) -> None:
    """Called once after every successful policy update."""
    payload = build_audit_payload(
        WORKSPACE_SHARE_POLICY_CHANGED,
        actor=actor_id,
        workspace_id=workspace_id,
        resource_type="workspace",
        resource_id=workspace_id,
        old_value=_policy_value(old),
        new_value=_policy_value(new),
        occurred_at=new.updated_at or datetime.now(UTC),
    )
    await publish_audit_event(WORKSPACE_SHARE_POLICY_CHANGED, payload)
