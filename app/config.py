from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./food-catalog.db"
    api_key: str = "dev-consumer-key"
    admin_api_key: str = "dev-admin-key"
    admin_username: str = "admin"
    admin_password_hash: str = "pbkdf2_sha256$1000$Zm9vZC1jYXRhbG9nLWRldmVsb3BtZW50$QKwhDHnYuRiqpV4rLVOnm7VJZy3fd-VjFQiMfuK_nCg"
    session_secret: str = "dev-session-secret"
    session_ttl_seconds: int = 28800
    auto_import_ciqual: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FOOD_CATALOG_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_keys(self):
        if self.api_key == self.admin_api_key:
            raise ValueError("consumer and admin API keys must be different")
        if self.environment == "production":
            for name, value in (("api_key", self.api_key), ("admin_api_key", self.admin_api_key), ("session_secret", self.session_secret)):
                if len(value) < 32 or value.startswith(("dev-", "change-")):
                    raise ValueError(f"{name} must be a non-placeholder secret of at least 32 characters")
            if self.admin_username in {"", "admin", "administrator"}:
                raise ValueError("admin_username must be changed in production")
            if not self.admin_password_hash.startswith("pbkdf2_sha256$"):
                raise ValueError("admin_password_hash must use pbkdf2_sha256")
            try:
                iterations = int(self.admin_password_hash.split("$", 3)[1])
            except (ValueError, IndexError) as exc:
                raise ValueError("admin_password_hash is malformed") from exc
            if iterations < 600000:
                raise ValueError("admin_password_hash must use at least 600000 iterations")
        if not 900 <= self.session_ttl_seconds <= 86400:
            raise ValueError("session_ttl_seconds must be between 900 and 86400")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
