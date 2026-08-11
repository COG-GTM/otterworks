from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "billing-service"
    schema_name: str = "billing_svc"
    database_url: str = (
        "postgresql://billing_svc:billing_svc@localhost:56432/billing_svc_dev"
    )
    cors_origins: list[str] = ["http://localhost:3000"]
    allow_internal_reset: bool = False

    model_config = {"env_prefix": "BILLING_SVC_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
