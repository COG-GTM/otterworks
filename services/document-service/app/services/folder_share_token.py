"""Tokens for expiring folder share links.

Raw tokens come from a CSPRNG and are never stored. The database keeps only
``hash_token(token)``: a hex HMAC-SHA256 keyed with ``SHARE_LINK_SECRET``, so a
leaked table cannot be replayed as links. Look a link up by ``token_hash`` and
use ``verify_token`` for any comparison against a stored hash.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

SHARE_LINK_SECRET_ENV = "SHARE_LINK_SECRET"
TOKEN_BYTES = 32


class ShareLinkSecretMissingError(RuntimeError):
    """Raised when no HMAC key is configured; links must never be hashed unkeyed."""


def _key(secret: str | None) -> bytes:
    value = secret if secret is not None else os.environ.get(SHARE_LINK_SECRET_ENV, "")
    if not value:
        raise ShareLinkSecretMissingError(f"{SHARE_LINK_SECRET_ENV} is not set")
    return value.encode()


def generate_token() -> str:
    """Return a new URL-safe raw token (256 bits of CSPRNG entropy)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str, secret: str | None = None) -> str:
    """Return the 64-char hex HMAC-SHA256 of ``token`` keyed with the share-link secret."""
    return hmac.new(_key(secret), token.encode(), hashlib.sha256).hexdigest()


def verify_token(token: str, token_hash: str, secret: str | None = None) -> bool:
    """Constant-time check that ``token`` hashes to ``token_hash``."""
    return hmac.compare_digest(hash_token(token, secret).encode(), token_hash.encode())


def new_token(secret: str | None = None) -> tuple[str, str]:
    """Return ``(raw_token, token_hash)`` for a new link."""
    token = generate_token()
    return token, hash_token(token, secret)
