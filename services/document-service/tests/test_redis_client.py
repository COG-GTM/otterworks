"""Redis client wiring for the shared (AUTH + TLS) ElastiCache."""

import pytest
import redis as redis_lib

from app.api import documents


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    monkeypatch.setattr(documents, "_redis_client", None)
    for var in ("REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_TLS"):
        monkeypatch.delenv(var, raising=False)
    yield
    monkeypatch.setattr(documents, "_redis_client", None)


def test_defaults_to_plain_unauthenticated_local_redis():
    pool = documents._get_redis().connection_pool
    assert pool.connection_class is redis_lib.Connection
    assert pool.connection_kwargs["host"] == "localhost"
    assert pool.connection_kwargs["password"] is None


def test_uses_auth_token_and_tls_when_configured(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "master.otterworks-redis-dev.cache.amazonaws.com")
    monkeypatch.setenv("REDIS_PASSWORD", "s3cret")
    monkeypatch.setenv("REDIS_TLS", "true")

    pool = documents._get_redis().connection_pool

    assert pool.connection_class is redis_lib.SSLConnection
    assert pool.connection_kwargs["password"] == "s3cret"
    assert pool.connection_kwargs["host"] == "master.otterworks-redis-dev.cache.amazonaws.com"


def test_empty_password_is_not_sent(monkeypatch):
    monkeypatch.setenv("REDIS_PASSWORD", "")
    assert documents._get_redis().connection_pool.connection_kwargs["password"] is None
