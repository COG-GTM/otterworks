"""OTW-66 token helper tests.

Scenario (OTW-63 US1): Given a link is created, Then its token comes from a CSPRNG,
only a keyed hash of the token is stored, and the raw token is returned once.
"""

import hashlib
import hmac
import secrets

import pytest

from app.services import folder_share_token
from app.services.folder_share_token import (
    ShareLinkSecretMissingError,
    generate_token,
    hash_token,
    new_token,
    verify_token,
)

SECRET = "test-share-link-secret"  # noqa: S105


@pytest.fixture(autouse=True)
def share_link_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARE_LINK_SECRET", SECRET)


# US1 / Given a link is created, Then its token comes from a CSPRNG
def test_us1_token_comes_from_csprng(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = secrets.token_urlsafe

    def spy(nbytes: int) -> str:
        calls.append(nbytes)
        return real(nbytes)

    monkeypatch.setattr(folder_share_token.secrets, "token_urlsafe", spy)
    token = generate_token()

    assert calls == [32]
    assert len(token) >= 43
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_us1_tokens_are_unique() -> None:
    assert len({generate_token() for _ in range(1000)}) == 1000


# US1 / Then only a keyed hash of the token is stored
def test_us1_hash_is_hmac_sha256_keyed_with_share_link_secret() -> None:
    token = generate_token()
    expected = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()

    token_hash = hash_token(token)

    assert token_hash == expected
    assert len(token_hash) == 64
    assert token not in token_hash


def test_us1_hash_is_deterministic_and_depends_on_key() -> None:
    token = generate_token()
    assert hash_token(token) == hash_token(token)
    assert hash_token(token, secret="other-secret") != hash_token(token)  # noqa: S106
    assert hash_token(token) != hashlib.sha256(token.encode()).hexdigest()


def test_us1_hashing_refuses_to_run_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHARE_LINK_SECRET", raising=False)
    with pytest.raises(ShareLinkSecretMissingError):
        hash_token("anything")
    monkeypatch.setenv("SHARE_LINK_SECRET", "")
    with pytest.raises(ShareLinkSecretMissingError):
        new_token()


def test_us1_new_token_returns_raw_token_and_its_hash() -> None:
    token, token_hash = new_token()
    assert token_hash == hash_token(token)
    assert verify_token(token, token_hash)


# US4 / Given an unknown or tampered token, Then it does not match (API returns 404)
def test_us4_verify_rejects_tampered_and_unknown_tokens() -> None:
    token, token_hash = new_token()
    tampered = ("A" if token[0] != "A" else "B") + token[1:]

    assert verify_token(token, token_hash)
    assert not verify_token(tampered, token_hash)
    assert not verify_token(generate_token(), token_hash)
    assert not verify_token("", token_hash)
    assert not verify_token("é-not-ascii", token_hash)


def test_verify_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(folder_share_token.hmac, "compare_digest", spy)
    token, token_hash = new_token()

    assert verify_token(token, token_hash)
    assert len(calls) == 1
