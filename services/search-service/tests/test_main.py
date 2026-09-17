"""Tests for application construction in app.main."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, SQSConfig
from app.main import configure_logging, create_app


@pytest.fixture()
def meili_client_patch(mock_meilisearch_client: MagicMock):
    """Patch the meilisearch client constructor for the duration of a test."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        yield mock_cls


class TestCreateApp:
    """Tests for create_app."""

    def test_defaults_to_environment_config_when_none_is_given(self, meili_client_patch):
        """create_app() with no argument builds an AppConfig from the environment."""
        app = create_app()

        assert isinstance(app.config["APP_CONFIG"], AppConfig)
        assert app.config["SEARCH_SERVICE"] is not None

    def test_registers_the_health_search_and_index_routes(self, app):
        """All three blueprints are mounted at their documented prefixes."""
        rules = {rule.rule for rule in app.url_map.iter_rules()}

        assert "/health" in rules
        assert "/api/v1/search/" in rules
        assert "/api/v1/search/index/document" in rules

    def test_index_creation_failure_is_non_fatal(self, app_config, mock_meilisearch_client):
        """A MeiliSearch outage at boot must not stop the app from serving."""
        with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
            mock_cls.return_value = mock_meilisearch_client
            with patch(
                "app.services.meilisearch_client.MeiliSearchService.ensure_indices",
                side_effect=RuntimeError("meilisearch unavailable"),
            ):
                app = create_app(app_config)

        assert app.test_client().get("/health").status_code == 200

    def test_sqs_consumer_is_started_when_enabled(self, app_config, meili_client_patch):
        """Enabling SQS wires an Indexer-backed consumer and starts it."""
        config = replace(
            app_config,
            sqs=SQSConfig(enabled=True, queue_url="https://sqs.test.local/queue"),
        )

        with patch("app.main.SQSConsumer") as consumer_cls:
            app = create_app(config)

        consumer_cls.assert_called_once()
        kwargs = consumer_cls.call_args.kwargs
        assert kwargs["queue_url"] == "https://sqs.test.local/queue"
        assert kwargs["max_messages"] == 10
        consumer_cls.return_value.start.assert_called_once()
        assert app.config["SQS_CONSUMER"] is consumer_cls.return_value

    def test_sqs_consumer_is_absent_when_disabled(self, app):
        assert "SQS_CONSUMER" not in app.config


class TestRequestMetrics:
    """Tests for the Prometheus instrumentation hooks."""

    def test_api_requests_are_counted(self, client):
        """A request to an instrumented route shows up in /metrics."""
        client.get("/api/v1/search/?q=hello")

        body = client.get("/metrics").get_data(as_text=True)

        assert 'endpoint="/api/v1/search/"' in body

    def test_health_and_metrics_are_not_instrumented(self, client):
        """The scrape endpoints are excluded to avoid self-referential noise."""
        client.get("/health")

        body = client.get("/metrics").get_data(as_text=True)

        assert 'endpoint="/health"' not in body

    def test_unmatched_routes_are_recorded_as_unknown(self, client):
        """A 404 has no url_rule, so the endpoint label falls back to 'unknown'."""
        client.get("/definitely-not-a-route")

        body = client.get("/metrics").get_data(as_text=True)

        assert 'endpoint="unknown"' in body


class TestConfigureLogging:
    """Tests for configure_logging."""

    @pytest.mark.parametrize("level", ["DEBUG", "info", "not-a-level"])
    def test_accepts_any_level_string(self, level):
        """An unrecognised level falls back to INFO instead of raising."""
        configure_logging(level)
