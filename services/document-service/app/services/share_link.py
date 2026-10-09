"""Share-link tokens for read-only document links.

A share link is stateless: the token is an HMAC-SHA256 over the document id,
keyed with the server-held ``SHARE_LINK_SECRET``, so any replica can validate a
link without a shared lookup table while nobody without the key can derive one.
Rotating the secret revokes every link minted under the previous key.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

TOKEN_LENGTH = 32
MIN_SECRET_LENGTH = 16
SECRET_ENV = "SHARE_LINK_SECRET"
_MESSAGE_PREFIX = "otterworks:share-link:v1:"


class ShareLinkNotConfiguredError(RuntimeError):
    """Raised when no usable share-link secret is configured."""


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, secret: str | None = None):
        self._secret = secret if secret is not None else os.environ.get(SECRET_ENV, "")

    def _key(self) -> bytes:
        if len(self._secret) < MIN_SECRET_LENGTH:
            raise ShareLinkNotConfiguredError(
                f"{SECRET_ENV} must be set to at least {MIN_SECRET_LENGTH} characters"
            )
        return self._secret.encode()

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        message = f"{_MESSAGE_PREFIX}{document_id}".encode()
        digest = hmac.new(self._key(), message, hashlib.sha256).hexdigest()
        return digest[:TOKEN_LENGTH]

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
