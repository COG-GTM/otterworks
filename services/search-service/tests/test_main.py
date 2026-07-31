"""Tests for application construction in app.main."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig, AuthConfig, MeiliSearchConfig, SQSConfig
from app.main import configure_logging, create_app


@pytest.fixture()
def patched_meilisearch(mock_meilisearch_client: MagicMock):
    """Patch the meilisearch client constructor for the duration of a test."""
    with patch("app.services.meilisearch_client.meilisearch.Client") as mock_cls:
        mock_cls.return_value = mock_meilisearch_client
        yield mock_cls


def _config(**overrides) -> AppConfig:
    base = {
        "service_name": "search-service-test",
        "meilisearch": MeiliSearchConfig(
            url="http://localhost:7700",
            api_key="",
            documents_index="test-otterworks-documents",
            files_index="test-otterworks-files",
        ),
        "sqs": SQSConfig(enabled=False),
        "auth": AuthConfig(service_token="", require_auth=False),
    }
    base.update(overrides)
    return AppConfig(**base)


class TestCreateApp:
    """Tests for create_app wiring."""

    def test_defaults_to_environment_config_when_none_given(self, patched_meilisearch):
        """create_app() with no argument builds an AppConfig from the environment."""
        app = create_app()
        assert isinstance(app.config["APP_CONFIG"], AppConfig)
        assert app.config["APP_CONFIG"].service_name == "search-service"

    def test_stores_config_and_search_service(self, patched_meilisearch):
        """The config and MeiliSearch service are exposed on app.config."""
        config = _config()
        app = create_app(config)
        assert app.config["APP_CONFIG"] is config
        assert app.config["SEARCH_SERVICE"].documents_index_name == (
            "test-otterworks-documents"
        )

    def test_index_creation_failure_is_non_fatal(self, patched_meilisearch):
        """A MeiliSearch outage at boot must not prevent the app from starting."""
        with patch(
            "app.services.meilisearch_client.MeiliSearchService.ensure_indices",
            side_effect=ConnectionError("meilisearch unreachable"),
        ):
            app = create_app(_config())
        assert app.test_client().get("/health").status_code == 200

    def test_sqs_consumer_is_not_created_when_disabled(self, patched_meilisearch):
        """No consumer is wired up when SQS is off."""
        app = create_app(_config(sqs=SQSConfig(enabled=False)))
        assert "SQS_CONSUMER" not in app.config

    def test_sqs_consumer_is_started_when_enabled(self, patched_meilisearch):
        """When SQS is on the consumer is constructed from config and started."""
        sqs_config = SQSConfig(
            enabled=True,
            queue_url="https://sqs.test.local/queue/search-index",
            region="eu-west-1",
            endpoint_url="http://localstack:4566",
            max_messages=5,
            wait_time_seconds=1,
            visibility_timeout=30,
        )
        with patch("app.services.sqs_consumer.SQSConsumer.start") as start:
            app = create_app(_config(sqs=sqs_config))

        start.assert_called_once_with()
        consumer = app.config["SQS_CONSUMER"]
        assert consumer.queue_url == sqs_config.queue_url
        assert consumer.region == "eu-west-1"
        assert consumer.endpoint_url == "http://localstack:4566"
        assert consumer.max_messages == 5
        assert consumer.wait_time_seconds == 1
        assert consumer.visibility_timeout == 30

    def test_cors_headers_are_exposed_to_the_web_app_origin(self, patched_meilisearch):
        """The React web app origin is allowed by CORS."""
        app = create_app(_config())
        response = app.test_client().get(
            "/health", headers={"Origin": "http://localhost:3000"}
        )
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"


class TestRequestMetrics:
    """Tests for the Prometheus instrumentation hooks."""

    def test_api_requests_are_counted(self, client):
        """A request to an API route increments the request counter."""
        client.get("/api/v1/search/?q=metrics-probe")
        body = client.get("/metrics").get_data(as_text=True)
        assert 'endpoint="/api/v1/search/"' in body
        assert "search_service_requests_total" in body

    def test_probe_endpoints_are_not_counted(self, client):
        """/health and /metrics are excluded from request metrics."""
        client.get("/health")
        body = client.get("/metrics").get_data(as_text=True)
        assert 'endpoint="/health"' not in body

    def test_unrouted_requests_are_counted_as_unknown(self, client):
        """A 404 has no url_rule, so it is recorded under the 'unknown' endpoint."""
        client.get("/api/v1/does-not-exist")
        body = client.get("/metrics").get_data(as_text=True)
        assert 'endpoint="unknown"' in body


class TestConfigureLogging:
    """Tests for log configuration."""

    @pytest.mark.parametrize(
        ("level", "expected"),
        [("debug", 10), ("INFO", 20), ("warning", 30), ("nonsense", 20)],
    )
    def test_log_level_is_applied_with_info_fallback(self, level, expected):
        """Known level names are honoured; unknown ones fall back to INFO."""
        with patch("app.main.logging.basicConfig") as basic_config:
            configure_logging(level)
        assert basic_config.call_args.kwargs["level"] == expected

    def test_logging_is_configured_for_structlog_json_output(self):
        """configure_logging installs a structlog stdlib pipeline."""
        import structlog

        with patch("app.main.logging.basicConfig"):
            configure_logging("INFO")
        assert structlog.is_configured()
        assert isinstance(
            structlog.get_logger().bind(), structlog.stdlib.BoundLogger
        )
