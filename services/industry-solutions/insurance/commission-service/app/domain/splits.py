"""Split-commission allocation: COMMISSION_PKG.set_commission_splits."""

from __future__ import annotations

from decimal import Decimal

from app.domain.errors import BadSplitError, ConstraintViolationError, UnknownPolicyError
from app.domain.model import CommissionRepository, Split
from app.domain.oracle_compat import oracle_to_char, round_half_up
from app.domain.rates import assert_active_agent

FULL = Decimal("100")


def set_commission_splits(
    repo: CommissionRepository,
    policy_id: int,
    splits: list[tuple[int, Decimal | None]],
    actor: str,
) -> list[Split]:
    if repo.get_policy(policy_id) is None:
        raise UnknownPolicyError(f"Unknown policy: {policy_id}")
    if not splits:
        raise BadSplitError("At least one split allocation is required")
    if len({agent_id for agent_id, _ in splits}) != len(splits):
        raise BadSplitError("Duplicate agent in split allocation")

    total = Decimal("0")
    validated: list[tuple[int, Decimal]] = []
    for agent_id, split_pct in splits:
        if split_pct is None or split_pct <= 0 or split_pct > FULL:
            raise BadSplitError(f"Split pct must be in (0, 100]: agent {agent_id}")
        assert_active_agent(repo, agent_id)
        total += split_pct
        validated.append((agent_id, split_pct))
    if total != FULL:
        raise BadSplitError(f"Split percentages must total 100.00, got {oracle_to_char(total)}")

    stored = [Split(agent_id, round_half_up(split_pct)) for agent_id, split_pct in validated]
    if any(split.split_pct <= 0 for split in stored):
        raise ConstraintViolationError("check constraint (CK_SPLITS_RANGE) violated")
    repo.replace_splits(policy_id, stored)
    repo.log_action("SPLIT_SET", None, None, policy_id, f"{len(splits)} agents", actor)
    return stored
