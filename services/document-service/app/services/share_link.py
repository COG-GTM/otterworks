"""Share-link tokens for read-only document links.

A share link is stateless: the token is a keyed MAC over the document id, so
any replica holding ``SHARE_LINK_SECRET`` can validate a link without a shared
lookup table, and nobody without that secret can derive one.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

import structlog

logger = structlog.get_logger()

TOKEN_LENGTH = 16

_ephemeral_secret: str | None = None


def _process_secret() -> str:
    """Return a per-process key for deployments that set no ``SHARE_LINK_SECRET``.

    Links minted with it stop validating when the process restarts or when a
    second replica answers, which is the visible cost of leaving the secret
    unset; deriving one from public material would not be a secret at all.
    """
    global _ephemeral_secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(32)
        logger.warning("share_link_secret_unset_using_ephemeral_key")
    return _ephemeral_secret


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, salt: str | None = None, secret: str | None = None):
        self.salt = salt or os.environ.get("SHARE_LINK_SALT", "otterworks-share")
        self.secret = secret or os.environ.get("SHARE_LINK_SECRET") or _process_secret()

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
