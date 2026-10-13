from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_BYTES = 32


class Settings(BaseSettings):
    """All secrets come from the environment (or a mounted secret); none have defaults."""

    model_config = SettingsConfigDict(env_prefix="COMMISSION_SVC_", extra="ignore")

    database_url: str = Field(min_length=1)
    jwt_secret: str = Field(validation_alias="JWT_SECRET", min_length=MIN_SECRET_BYTES)
    jwt_algorithms: list[str] = ["HS256", "HS384", "HS512"]
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    tenant_claim: str = "tenant_id"
    enable_reset: bool = False
    reset_tenants: str = ""

    @property
    def reset_tenant_ids(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.reset_tenants.split(",") if t.strip())

    @field_validator("jwt_algorithms")
    @classmethod
    def hmac_only(cls, value: list[str]) -> list[str]:
        if not value or any(not alg.startswith("HS") for alg in value):
            raise ValueError("only HMAC algorithms shared with auth-service are supported")
        return value


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
