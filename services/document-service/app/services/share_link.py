"""Share-link tokens for read-only document links.

A share link is stateless: the token is an HMAC-SHA256 over the document id,
keyed with a server-held secret, so any replica holding the secret can validate
a link without a shared lookup table, and nobody without it can derive one.

The key is ``SHARE_LINK_SECRET``. When that is unset it is derived from
``JWT_SECRET`` (domain-separated, so a share token never doubles as anything
else), which every deployment already provisions. With neither set the service
fails closed: it refuses to mint links and rejects every token. Rotating the
secret revokes every outstanding link.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

_JWT_DERIVATION_LABEL = b"otterworks/share-link/v1"


class ShareLinkNotConfiguredError(RuntimeError):
    """Raised when no share-link secret is available to mint a token."""


def _resolve_key(secret: str | None) -> bytes | None:
    if secret:
        return secret.encode()
    configured = os.environ.get("SHARE_LINK_SECRET", "")
    if configured:
        return configured.encode()
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if jwt_secret:
        return hmac.new(jwt_secret.encode(), _JWT_DERIVATION_LABEL, hashlib.sha256).digest()
    return None


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, secret: str | None = None):
        self._key = _resolve_key(secret)

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        if self._key is None:
            raise ShareLinkNotConfiguredError(
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
