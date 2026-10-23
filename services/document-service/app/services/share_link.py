"""Share-link tokens for read-only document links.

A share link is stateless: the token is an HMAC-SHA256 over the document id,
keyed with a server-held secret, so any replica can validate a link without a
shared lookup table while nobody without the key can derive one. Rotating the
secret revokes every link minted under the previous key.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

SECRET_ENV = "SHARE_LINK_SECRET"
LEGACY_SECRET_ENV = "SHARE_LINK_SALT"
MIN_SECRET_LENGTH = 16
# Formerly the source-visible default salt; never accepted as keying material.
_PUBLIC_DEFAULT_SALT = "otterworks-share"
_MESSAGE_PREFIX = "otterworks:share-link:v1:"


class ShareLinkNotConfiguredError(RuntimeError):
    """Raised when no usable share-link secret is configured."""


def _configured_secret() -> str:
    return os.environ.get(SECRET_ENV) or os.environ.get(LEGACY_SECRET_ENV) or ""


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, secret: str | None = None):
        self._secret = _configured_secret() if secret is None else secret

    def _key(self) -> bytes:
        if len(self._secret) < MIN_SECRET_LENGTH or self._secret == _PUBLIC_DEFAULT_SALT:
            raise ShareLinkNotConfiguredError(
                f"{SECRET_ENV} must be set to a private value of at least "
                f"{MIN_SECRET_LENGTH} characters"
            )
        return self._secret.encode()

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        message = f"{_MESSAGE_PREFIX}{document_id}".encode()
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
