"""Share-link tokens for read-only document links.

A share link is stateless: the token is a keyed MAC over the document id, so
any replica can validate a link without a shared lookup table while a token
stays underivable from public information.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

import structlog

logger = structlog.get_logger()

TOKEN_LENGTH = 16

_EPHEMERAL_SECRET = secrets.token_hex(32)


def _configured_secret() -> str:
    """Return the keying material for share tokens.

    Falls back to the service's JWT secret, then to a per-process random key
    so a token is never derivable from anything in the source tree. Links
    minted under the ephemeral key do not survive a restart.
    """
    secret = os.environ.get("SHARE_LINK_SECRET") or os.environ.get("JWT_SECRET")
    if secret:
        return secret
    logger.warning("share_link_secret_missing")
    return _EPHEMERAL_SECRET


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, salt: str | None = None, secret: str | None = None):
        self.salt = salt or os.environ.get("SHARE_LINK_SALT", "otterworks-share")
        self.secret = secret or _configured_secret()

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
        ok = hmac.compare_digest(expected, token)
        if not ok:
            logger.info("share_token_rejected", document_id=document_id)
        return ok
