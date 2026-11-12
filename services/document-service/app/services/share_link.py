"""Share-link tokens for read-only document links.

A share link is stateless: the token is an HMAC-SHA256 over the document id,
keyed with the server-held SHARE_LINK_SECRET. Any replica holding the key can
validate a link without a shared lookup table, and nobody without the key can
derive one. Rotating SHARE_LINK_SECRET revokes every previously minted link.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

SECRET_ENV = "SHARE_LINK_SECRET"
MIN_SECRET_LENGTH = 24
# Shipped in source as the old unkeyed salt, so it can never serve as a key.
_PUBLIC_DEFAULT_SALT = "otterworks-share"
_MESSAGE_PREFIX = b"otterworks.share-link.v1:"


class ShareLinkNotConfiguredError(RuntimeError):
    """Raised when SHARE_LINK_SECRET is missing or unusable."""


def _is_usable_secret(secret: str) -> bool:
    return len(secret) >= MIN_SECRET_LENGTH and secret != _PUBLIC_DEFAULT_SALT


def share_link_secret_configured() -> bool:
    """Return True when SHARE_LINK_SECRET holds a usable key."""
    return _is_usable_secret(os.environ.get(SECRET_ENV, ""))


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, secret: str | None = None):
        self._secret = os.environ.get(SECRET_ENV, "") if secret is None else secret

    def _key(self) -> bytes:
        if not _is_usable_secret(self._secret):
            raise ShareLinkNotConfiguredError(
                f"{SECRET_ENV} must be set to a private value of at least "
                f"{MIN_SECRET_LENGTH} characters"
            )
        return self._secret.encode()

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        message = _MESSAGE_PREFIX + document_id.encode()
        return hmac.new(self._key(), message, hashlib.sha256).hexdigest()

    def verify_token(self, document_id: str, token: str) -> bool:
        """Return True when the token is a valid share token for the document."""
        try:
            expected = self.mint_token(document_id)
        except ShareLinkNotConfiguredError:
            logger.error("share_link_secret_missing", document_id=document_id)
            return False
        ok = hmac.compare_digest(expected.encode(), token.encode())
        if not ok:
            logger.info("share_token_rejected", document_id=document_id)
        return ok
