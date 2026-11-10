"""Hook point for workspace share-policy change events.

OTW-46 sends ``workspace_share_policy_changed`` to audit-service from here.
"""

from __future__ import annotations

import uuid

from app.services.share_link_repository import EffectiveSharePolicy


async def emit_policy_changed_event(
    old: EffectiveSharePolicy,
    new: EffectiveSharePolicy,
    *,
    actor_id: uuid.UUID,
    workspace_id: str,
) -> None:
    """Called once after every successful policy update. Intentionally a no-op for now."""
    return None
