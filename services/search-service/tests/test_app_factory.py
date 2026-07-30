"""Tests for the Flask application factory in app.main."""

from __future__ import annotations

import logging
import runpy
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.api.health import REQUEST_COUNT
from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import configure_logging, create_app


@pytest.fixture()
def meilisearch_cls(mock_meilisearch_client: MagicMock):
    """Patch the meilisearch client class for the duration of a test."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        yield mock_cls


class TestConfigureLogging:
    """configure_logging maps the configured level onto stdlib logging."""

    @pytest.mark.parametrize(
        ("level", "expected"),
        [("debug", logging.DEBUG), ("WARNING", logging.WARNING), ("nonsense", logging.INFO)],
    )
    def test_configured_level_falls_back_to_info(self, level, expected):
        with patch("app.main.logging.basicConfig") as basic_config:
            configure_logging(level)

        assert basic_config.call_args.kwargs["level"] == expected


class TestCreateApp:
    """create_app wires config, services, blueprints and middleware."""

    def test_defaults_to_environment_config(self, meilisearch_cls):
        app = create_app()

        assert isinstance(app.config["APP_CONFIG"], AppConfig)
        assert app.config["SEARCH_SERVICE"] is not None
        assert "SQS_CONSUMER" not in app.config

    def test_indices_are_ensured_on_startup(self, app_config, meilisearch_cls):
        app = create_app(app_config)

        app.config["SEARCH_SERVICE"].client.index.assert_any_call(
            app_config.meilisearch.documents_index
        )

    def test_startup_survives_an_unreachable_meilisearch(self, app_config, meilisearch_cls):
        with patch(
            "app.services.meilisearch_client.MeiliSearchService.ensure_indices",
            side_effect=RuntimeError("connection refused"),
        ):
            app = create_app(app_config)

        assert app.config["SEARCH_SERVICE"] is not None
        assert app.test_client().get("/health").status_code == 200

    def test_all_blueprints_are_registered(self, app_config, meilisearch_cls):
        app = create_app(app_config)

        rules = {rule.rule for rule in app.url_map.iter_rules()}
        assert "/health" in rules
        assert "/api/v1/search/" in rules
        assert "/api/v1/search/index/document" in rules


class TestSQSConsumerWiring:
    """The SQS consumer is only started when SQS is enabled."""

    def test_consumer_is_started_with_the_configured_settings(self, app_config, meilisearch_cls):
        sqs_config = SQSConfig(
            queue_url="https://sqs.test/q",
            region="eu-west-1",
            endpoint_url="http://localstack:4566",
            max_messages=5,
            wait_time_seconds=1,
            visibility_timeout=30,
            enabled=True,
        )
        config = replace(app_config, sqs=sqs_config)

        with patch("app.main.SQSConsumer") as consumer_cls:
            app = create_app(config)

        consumer_cls.assert_called_once()
        kwargs = consumer_cls.call_args.kwargs
        assert kwargs["queue_url"] == "https://sqs.test/q"
        assert kwargs["region"] == "eu-west-1"
        assert kwargs["endpoint_url"] == "http://localstack:4566"
        assert kwargs["max_messages"] == 5
        assert kwargs["wait_time_seconds"] == 1
        assert kwargs["visibility_timeout"] == 30
        consumer_cls.return_value.start.assert_called_once_with()
        assert app.config["SQS_CONSUMER"] is consumer_cls.return_value

    def test_consumer_is_not_created_when_disabled(self, app_config, meilisearch_cls):
        with patch("app.main.SQSConsumer") as consumer_cls:
            app = create_app(app_config)

        consumer_cls.assert_not_called()
        assert "SQS_CONSUMER" not in app.config


class TestRequestMetrics:
    """The after_request hook records Prometheus metrics for non-probe routes."""

    def _count(self, endpoint: str, status: int, method: str = "GET") -> float:
        return REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status)._value.get()

    def test_matched_route_is_counted_by_rule(self, client):
        before = self._count("/api/v1/search/analytics", 200)

        client.get("/api/v1/search/analytics")

        assert self._count("/api/v1/search/analytics", 200) == before + 1

    def test_unmatched_route_is_counted_as_unknown(self, client):
        before = self._count("unknown", 404)

        client.get("/does-not-exist")

        assert self._count("unknown", 404) == before + 1

    @pytest.mark.parametrize("path", ["/health", "/metrics"])
    def test_probe_endpoints_are_not_counted(self, client, path):
        before = self._count(path, 200)

        client.get(path)

        assert self._count(path, 200) == before


class TestReadiness:
    """The readiness probe depends on the search service being wired up."""

    def test_unwired_search_service_reports_not_ready(self, app):
        app.config["SEARCH_SERVICE"] = None

        response = app.test_client().get("/health/ready")

        assert response.status_code == 503
        assert response.get_json() == {"ready": False, "reason": "meilisearch_unavailable"}


class TestModuleEntrypoint:
    """Running app/main.py as a script boots the development server."""

    def test_script_execution_starts_the_flask_server(self, meilisearch_cls, monkeypatch):
        monkeypatch.setenv("PORT", "8099")
        monkeypatch.setenv("HOST", "127.0.0.1")
        main_py = Path(__file__).resolve().parents[1] / "app" / "main.py"

        with patch("flask.Flask.run") as run:
            runpy.run_path(str(main_py), run_name="__main__")

        run.assert_called_once_with(host="127.0.0.1", port=8099, debug=False)


class TestAppConfigDefaults:
    """AppConfig reads its values from the environment."""

    def test_environment_overrides_are_picked_up(self, monkeypatch):
        monkeypatch.setenv("PORT", "9999")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        monkeypatch.setenv("FLASK_DEBUG", "true")
        monkeypatch.setenv("SQS_ENABLED", "true")
        monkeypatch.setenv("REQUIRE_AUTH", "false")
        monkeypatch.setenv("MEILISEARCH_URL", "http://meili:7700")

        config = AppConfig()

        assert config.port == 9999
        assert config.log_level == "WARNING"
        assert config.debug is True
        assert config.sqs.enabled is True
        assert config.auth.require_auth is False
        assert config.meilisearch.url == "http://meili:7700"

    def test_defaults_when_environment_is_empty(self, monkeypatch):
        for var in (
            "PORT",
            "LOG_LEVEL",
            "FLASK_DEBUG",
            "SQS_ENABLED",
            "REQUIRE_AUTH",
            "MEILISEARCH_URL",
            "MEILISEARCH_API_KEY",
            "MEILISEARCH_DOCUMENTS_INDEX",
            "MEILISEARCH_FILES_INDEX",
            "SEARCH_SERVICE_TOKEN",
            "AWS_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

        config = AppConfig()

        assert config.port == 8087
        assert config.debug is False
        assert config.meilisearch == MeiliSearchConfig(
            url="http://localhost:7700",
            api_key="",
            documents_index="documents",
            files_index="files",
        )
        assert config.sqs.enabled is False
        assert config.sqs.region == "us-east-1"
        assert config.auth == AuthConfig(service_token="", require_auth=True)
