from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./food-catalog.db"
    api_key: str = "dev-consumer-key"
    admin_api_key: str = "dev-admin-key"
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
            for name, value in (("api_key", self.api_key), ("admin_api_key", self.admin_api_key)):
                if len(value) < 32 or value.startswith(("dev-", "change-")):
                    raise ValueError(f"{name} must be a non-placeholder secret of at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
