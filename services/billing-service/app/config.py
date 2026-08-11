from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "billing-service"
    schema_name: str = "billing_svc"
    database_path: str = "/data/billing_svc.sqlite3"
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = {"env_prefix": "BILLING_SVC_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
