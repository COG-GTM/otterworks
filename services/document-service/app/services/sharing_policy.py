"""Workspace sharing policy, read from the management service over SHARING_POLICY_URL.

Falls back to the hard defaults (30 / 1 / 90 days) when the URL is unset, the
service is unreachable, or it answers with something outside the hard limits.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import structlog

from app.schemas.folder_share_link import (
    POLICY_DEFAULT_EXPIRY_DAYS,
    POLICY_MAX_EXPIRY_DAYS,
    POLICY_MIN_EXPIRY_DAYS,
)

logger = structlog.get_logger()

SHARING_POLICY_URL_ENV = "SHARING_POLICY_URL"
REQUEST_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class SharingPolicy:
    default_expiry_days: int
    min_expiry_days: int
    max_expiry_days: int

    def is_valid(self) -> bool:
        return (
            self.min_expiry_days >= POLICY_MIN_EXPIRY_DAYS
            and self.max_expiry_days <= POLICY_MAX_EXPIRY_DAYS
            and self.min_expiry_days <= self.default_expiry_days <= self.max_expiry_days
        )

    def allows(self, days: int) -> bool:
        return self.min_expiry_days <= days <= self.max_expiry_days


FALLBACK_POLICY = SharingPolicy(
    default_expiry_days=POLICY_DEFAULT_EXPIRY_DAYS,
    min_expiry_days=POLICY_MIN_EXPIRY_DAYS,
    max_expiry_days=POLICY_MAX_EXPIRY_DAYS,
)


class SharingPolicyClient:
    def __init__(
        self,
        url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url if url is not None else os.environ.get(SHARING_POLICY_URL_ENV, "")
        self._transport = transport

    async def get_policy(self, authorization: str | None = None) -> SharingPolicy:
        """Return the current policy; ``authorization`` is the caller's bearer header."""
        if not self._url:
            return FALLBACK_POLICY
        headers = {"Authorization": authorization} if authorization else {}
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                resp = await client.get(self._url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            policy = SharingPolicy(
                default_expiry_days=int(data["default_expiry_days"]),
                min_expiry_days=int(data["min_expiry_days"]),
                max_expiry_days=int(data["max_expiry_days"]),
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("sharing_policy_fallback", reason=str(exc))
            return FALLBACK_POLICY
        if not policy.is_valid():
            logger.warning("sharing_policy_fallback", reason="policy outside hard limits")
            return FALLBACK_POLICY
        return policy


def get_sharing_policy_client() -> SharingPolicyClient:
    return SharingPolicyClient()
