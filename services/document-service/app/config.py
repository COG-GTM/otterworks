"""Application configuration via pydantic-settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when the service is started without a database connection string."""


class Settings(BaseSettings):
    app_name: str = "document-service"
    app_version: str = "0.1.0"
    debug: bool = False

    # Supplied by the environment (DOC_SVC_DATABASE_URL); credentials never live in code.
    database_url: SecretStr = SecretStr("")
    db_pool_size: int = 10
    db_max_overflow: int = 20

    sns_topic_arn: str = ""
    aws_endpoint_url: str = ""
    aws_region: str = "us-east-1"
    sns_enabled: bool = False

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = False

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:4200"]

    model_config = {"env_prefix": "DOC_SVC_", "env_file": ".env", "extra": "ignore"}

    def require_database_url(self) -> str:
        url = self.database_url.get_secret_value().strip()
        if not url:
            raise DatabaseNotConfiguredError(
                "DOC_SVC_DATABASE_URL is not set; refusing to start without database credentials"
            )
        return url


settings = Settings()
