"""Share-link tokens for read-only document links.

A share link is stateless: the token is an HMAC-SHA256 of the document id under a
deployment secret, so any replica can validate a link without a shared lookup
table, and nobody without the secret can derive a token from a document id.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

_KEY_CONTEXT = b"otterworks-share-link-v1"


class ShareLinkUnavailableError(RuntimeError):
    """Raised when no share-link secret is configured, so no token can be minted."""


def _resolve_key(secret: str | None) -> bytes | None:
    # Prefer a dedicated SHARE_LINK_SECRET; otherwise derive a domain-separated key
    # from JWT_SECRET, which every deployment already provisions as a secret.
    if secret:
        return secret.encode()
    dedicated = os.environ.get("SHARE_LINK_SECRET", "")
    if dedicated:
        return dedicated.encode()
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if jwt_secret:
        return hmac.new(jwt_secret.encode(), _KEY_CONTEXT, hashlib.sha256).digest()
    return None


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, secret: str | None = None):
        self._key = _resolve_key(secret)

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        if self._key is None:
            raise ShareLinkUnavailableError(
                "SHARE_LINK_SECRET (or JWT_SECRET) must be set to mint share links"
            )
        return hmac.new(self._key, document_id.encode(), hashlib.sha256).hexdigest()

    def verify_token(self, document_id: str, token: str) -> bool:
        """Return True when the token is a valid share token for the document."""
        if self._key is None:
            logger.warning("share_token_rejected_no_secret", document_id=document_id)
            return False
        expected = self.mint_token(document_id)
        ok = hmac.compare_digest(expected.encode(), token.encode())
        if not ok:
            logger.info("share_token_rejected", document_id=document_id)
        return ok
