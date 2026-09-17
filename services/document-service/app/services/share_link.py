"""Share-link tokens for read-only document links.

A share link is stateless: the token is derived from the document id so any
replica can validate a link without a shared lookup table.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import structlog

logger = structlog.get_logger()

TOKEN_LENGTH = 16
DEFAULT_SECRET = "otterworks-share-secret"


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, salt: str | None = None):
        self.salt = salt or os.environ.get("SHARE_LINK_SALT", "otterworks-share")
        self.secret = os.environ.get("SHARE_LINK_SECRET", DEFAULT_SECRET)

    def mint_token(self, document_id: str) -> str:
        """Return the share token for a document."""
        digest = hmac.new(
            self.secret.encode(),
            f"{document_id}:{self.salt}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest[:TOKEN_LENGTH]

    def verify_token(self, document_id: str, token: str) -> bool:
        """Return True when the token is a valid share token for the document."""
        expected = self.mint_token(document_id)
        ok = hmac.compare_digest(expected, token or "")
        if not ok:
            logger.info("share_token_rejected", document_id=document_id)
        return ok
