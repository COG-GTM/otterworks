"""Tests for application factory wiring in app.main."""

from __future__ import annotations

import logging
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, SQSConfig
from app.main import configure_logging, create_app


@pytest.fixture()
def patched_meili(mock_meilisearch_client: MagicMock):
    """Patch the meilisearch client class for the duration of a test."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        yield mock_meilisearch_client


def test_create_app_without_config_falls_back_to_environment_defaults(patched_meili):
    """create_app() with no argument builds an AppConfig from the environment."""
    app = create_app()
    assert isinstance(app.config["APP_CONFIG"], AppConfig)
    assert app.config["SEARCH_SERVICE"] is not None


def test_create_app_survives_meilisearch_being_unavailable(app_config, patched_meili):
    """Index creation failures at boot are logged, not fatal."""
    patched_meili.index.return_value.update_searchable_attributes.side_effect = RuntimeError(
        "meili down"
    )

    app = create_app(app_config)

    assert app.config["SEARCH_SERVICE"] is not None
    assert "SQS_CONSUMER" not in app.config


def test_create_app_starts_the_sqs_consumer_when_enabled(app_config, patched_meili):
    """With SQS enabled the consumer is constructed from config and started."""
    config = replace(
        app_config,
        sqs=SQSConfig(
            queue_url="https://sqs.test/q",
            region="eu-west-1",
            endpoint_url="http://localstack:4566",
            enabled=True,
        ),
    )

    with patch("app.main.SQSConsumer") as consumer_cls:
        app = create_app(config)

    kwargs = consumer_cls.call_args.kwargs
    assert kwargs["queue_url"] == "https://sqs.test/q"
    assert kwargs["region"] == "eu-west-1"
    assert kwargs["endpoint_url"] == "http://localstack:4566"
    consumer_cls.return_value.start.assert_called_once()
    assert app.config["SQS_CONSUMER"] is consumer_cls.return_value


def test_metrics_are_recorded_for_regular_requests(client):
    """The after_request hook increments the request counter for API calls."""
    from app.api.health import REQUEST_COUNT

    before = REQUEST_COUNT.labels(
        method="GET", endpoint="/api/v1/search/", status=400
    )._value.get()

    client.get("/api/v1/search/")

    after = REQUEST_COUNT.labels(
        method="GET", endpoint="/api/v1/search/", status=400
    )._value.get()
    assert after == before + 1


def test_unknown_routes_are_not_counted_against_a_url_rule(client):
    """A 404 has no url_rule and must not blow up the metrics hook."""
    response = client.get("/does-not-exist")
    assert response.status_code == 404


def test_readiness_is_false_when_no_search_service_is_configured(app):
    """Without a search service the readiness probe reports unavailable."""
    app.config["SEARCH_SERVICE"] = None

    response = app.test_client().get("/health/ready")

    assert response.status_code == 503
    assert response.get_json() == {"ready": False, "reason": "meilisearch_unavailable"}


def test_configure_logging_maps_the_level_name_onto_stdlib_logging():
    """configure_logging translates the configured level name for basicConfig."""
    with patch("app.main.logging.basicConfig") as basic_config:
        configure_logging("warning")
    assert basic_config.call_args.kwargs["level"] == logging.WARNING


def test_configure_logging_falls_back_to_info_for_unknown_levels():
    """An unrecognised level name degrades to INFO rather than raising."""
    with patch("app.main.logging.basicConfig") as basic_config:
        configure_logging("NOT_A_LEVEL")
    assert basic_config.call_args.kwargs["level"] == logging.INFO
