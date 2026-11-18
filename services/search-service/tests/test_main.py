"""Tests for application factory wiring."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

from app.config import AppConfig, SQSConfig
from app.main import create_app


def _create(config, mock_client):
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_client
        return create_app(config)


class TestCreateApp:
    def test_default_config_used_when_none(self, mock_meilisearch_client, monkeypatch):
        monkeypatch.setenv("REQUIRE_AUTH", "false")
        monkeypatch.setenv("SQS_ENABLED", "false")
        flask_app = _create(None, mock_meilisearch_client)
        assert isinstance(flask_app.config["APP_CONFIG"], AppConfig)
        assert flask_app.config["APP_CONFIG"].auth.require_auth is False

    def test_startup_tolerates_meilisearch_unavailable(self, app_config, mock_meilisearch_client):
        mock_meilisearch_client.index.side_effect = ConnectionError("down")
        flask_app = _create(app_config, mock_meilisearch_client)
        assert flask_app.test_client().get("/health").status_code == 200

    def test_sqs_consumer_started_when_enabled(self, app_config, mock_meilisearch_client):
        sqs = SQSConfig(
            queue_url="http://localstack:4566/q",
            region="eu-west-1",
            endpoint_url="http://localstack:4566",
            enabled=True,
        )
        config = replace(app_config, sqs=sqs)
        with patch("app.main.SQSConsumer") as consumer_cls:
            flask_app = _create(config, mock_meilisearch_client)

        kwargs = consumer_cls.call_args.kwargs
        assert kwargs["queue_url"] == "http://localstack:4566/q"
        assert kwargs["region"] == "eu-west-1"
        assert kwargs["endpoint_url"] == "http://localstack:4566"
        assert kwargs["max_messages"] == 10
        assert kwargs["wait_time_seconds"] == 20
        assert kwargs["visibility_timeout"] == 60
        assert kwargs["indexer"].search is flask_app.config["SEARCH_SERVICE"]
        consumer_cls.return_value.start.assert_called_once()
        assert flask_app.config["SQS_CONSUMER"] is consumer_cls.return_value

    def test_sqs_consumer_not_started_when_disabled(self, app):
        assert "SQS_CONSUMER" not in app.config

    def test_metrics_recorded_for_unmatched_route(self, client):
        response = client.get("/no-such-route")
        assert response.status_code == 404
        metrics = client.get("/metrics").get_data(as_text=True)
        assert 'endpoint="unknown"' in metrics

    def test_metrics_recorded_for_matched_route(self, client):
        client.get("/api/v1/search/analytics")
        metrics = client.get("/metrics").get_data(as_text=True)
        assert 'endpoint="/api/v1/search/analytics"' in metrics


class TestReadiness:
    def test_not_ready_without_search_service(self, app):
        app.config["SEARCH_SERVICE"] = None
        response = app.test_client().get("/health/ready")
        assert response.status_code == 503
        assert response.get_json()["reason"] == "meilisearch_unavailable"


