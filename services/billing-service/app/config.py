from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "billing-service"
    schema_name: str = "billing_svc"
    database_url: str
    cors_origins: list[str] = ["http://localhost:3000"]
    allow_internal_reset: bool = False
    jwt_secret: str | None = None
    service_token: str | None = None

    model_config = {"env_prefix": "BILLING_SVC_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
