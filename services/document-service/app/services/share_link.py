"""Share-link tokens for read-only document links.

A share link is stateless: the token is an HMAC-SHA256 over the document id,
keyed with a server-held secret, so any replica can validate a link without a
shared lookup table while nobody without the key can derive one.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

_KEY_DERIVATION_LABEL = b"otterworks-share-link-v1"


class ShareLinkUnavailableError(RuntimeError):
    """Raised when no share-link signing key is configured."""


def _resolve_key(secret: str | None) -> bytes:
    secret = secret or os.environ.get("SHARE_LINK_SECRET")
    if secret:
        return secret.encode()
    jwt_secret = os.environ.get("JWT_SECRET")
    if jwt_secret:
        # Domain-separated subkey so a share token is never a valid JWT MAC.
        return hmac.new(jwt_secret.encode(), _KEY_DERIVATION_LABEL, hashlib.sha256).digest()
    raise ShareLinkUnavailableError(
        "SHARE_LINK_SECRET (or JWT_SECRET) must be set to mint or verify share links"
    )


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, secret: str | None = None):
        self._key = _resolve_key(secret)

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        return hmac.new(self._key, document_id.encode(), hashlib.sha256).hexdigest()

    def verify_token(self, document_id: str, token: str) -> bool:
        """Return True when the token is a valid share token for the document."""
        expected = self.mint_token(document_id)
        ok = hmac.compare_digest(expected.encode(), token.encode())
        if not ok:
            logger.info("share_token_rejected", document_id=document_id)
        return ok
