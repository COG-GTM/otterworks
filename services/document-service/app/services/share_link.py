"""Share-link tokens for read-only document links.

A share link is stateless: the token is a keyed MAC over the document id, so
any replica holding the same key can validate a link without a shared lookup
table, and a caller cannot derive one from public information.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

import structlog

logger = structlog.get_logger()

TOKEN_LENGTH = 16

_fallback_secret: str | None = None


def _resolve_secret() -> str:
    """Return the keying material for share tokens.

    ``SHARE_LINK_SECRET`` is the configured key. Deployments that have not set
    it yet fall back to a key derived from ``JWT_SECRET`` so every replica
    still agrees, and finally to a per-process random key, which keeps links
    unforgeable at the cost of not surviving a restart.
    """
    configured = os.environ.get("SHARE_LINK_SECRET")
    if configured:
        return configured
    jwt_secret = os.environ.get("JWT_SECRET")
    if jwt_secret:
        return hmac.new(
            jwt_secret.encode(), b"otterworks-share-link", hashlib.sha256
        ).hexdigest()
    global _fallback_secret
    if _fallback_secret is None:
        _fallback_secret = secrets.token_hex(32)
        logger.warning("share_link_secret_missing_using_ephemeral_key")
    return _fallback_secret


class ShareLinkService:
    """Mints and validates read-only share tokens for documents."""

    def __init__(self, salt: str | None = None, secret: str | None = None):
        self.salt = salt or os.environ.get("SHARE_LINK_SALT", "otterworks-share")
        self.secret = secret or _resolve_secret()

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
