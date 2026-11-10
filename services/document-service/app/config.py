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

    workspace_id: str = Field(
        default="default",
        validation_alias=AliasChoices("WORKSPACE_ID", "DOC_SVC_WORKSPACE_ID"),
        max_length=64,
    )

    file_service_url: str = Field(
        default="http://localhost:8082",
        validation_alias=AliasChoices("DOC_SVC_FILE_SERVICE_URL", "FILE_SERVICE_URL"),
    )
    file_service_timeout_seconds: float = 5.0
    public_web_url: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("PUBLIC_WEB_URL", "DOC_SVC_PUBLIC_WEB_URL"),
    )
    share_link_hmac_key: str = Field(
        default="",
        validation_alias=AliasChoices("SHARE_LINK_HMAC_KEY", "DOC_SVC_SHARE_LINK_HMAC_KEY"),
    )
    share_policy_owner_ids: str = Field(
        default="",
        validation_alias=AliasChoices("SHARE_POLICY_OWNER_IDS", "DOC_SVC_SHARE_POLICY_OWNER_IDS"),
    )

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:4200"]

    model_config = {"env_prefix": "DOC_SVC_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
