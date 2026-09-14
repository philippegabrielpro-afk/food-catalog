import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import FoodWrite


def test_contract_rejects_health_context():
    with pytest.raises(ValidationError):
        FoodWrite(
            canonical_name="Riz cuit",
            carbs_per_100g=30,
            glucose_value=120,
        )


def test_production_rejects_placeholder_or_shared_keys():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            api_key="change-consumer-key",
            admin_api_key="change-admin-key",
        )

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            api_key="a" * 32,
            admin_api_key="a" * 32,
        )

    settings = Settings(
        environment="production",
        api_key="a" * 32,
        admin_api_key="b" * 32,
    )
    assert settings.environment == "production"
