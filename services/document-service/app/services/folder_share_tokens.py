"""Tokens for folder share links: CSPRNG secrets stored only as HMAC-SHA256."""

import hashlib
import hmac
import os
import secrets

import structlog

from app.config import settings

logger = structlog.get_logger()

TOKEN_BYTES = 32  # 256 bits of entropy
MAX_TOKEN_LENGTH = 128


class ShareLinkKeyMissingError(RuntimeError):
    """Neither SHARE_LINK_HMAC_KEY nor JWT_SECRET is configured."""


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _hmac_key() -> bytes:
    if settings.share_link_hmac_key:
        return settings.share_link_hmac_key.encode()
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if not jwt_secret:
        raise ShareLinkKeyMissingError("SHARE_LINK_HMAC_KEY is not configured")
    # Fallback for deployments that do not set SHARE_LINK_HMAC_KEY yet: a key derived
    # from the service's JWT secret, domain-separated so it is never the JWT key itself.
    logger.warning("share_link_hmac_key_derived_from_jwt_secret")
    return hmac.new(jwt_secret.encode(), b"otterworks-folder-share-link", hashlib.sha256).digest()


def hash_token(token: str) -> str:
    """HMAC-SHA256 hex digest of the token (64 chars, matches token_hash)."""
    return hmac.new(_hmac_key(), token.encode(), hashlib.sha256).hexdigest()


def token_matches(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)
