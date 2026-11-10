"""Application configuration via pydantic-settings."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "document-service"
    app_version: str = "0.1.0"
    debug: bool = False

    database_url: str = (
        "postgresql+asyncpg://otterworks:otterworks_dev@localhost:5432/otterworks"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20

    sns_topic_arn: str = ""
    aws_endpoint_url: str = ""
    aws_region: str = "us-east-1"
    sns_enabled: bool = False

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = False

    file_service_url: str = "http://file-service:8082"
    file_service_timeout_seconds: float = 5.0
    # Public web-client origin that serves /s/{token}; share link URLs are built from it.
    public_app_url: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("PUBLIC_APP_URL", "DOC_SVC_PUBLIC_APP_URL"),
    )

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:4200"]

    model_config = {"env_prefix": "DOC_SVC_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
