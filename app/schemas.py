from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


Qualifier = Literal["exact", "less_than", "traces", "missing"]


class NutritionReferenceOut(BaseModel):
    source: str
    external_code: str
    source_version: str
    carbs_per_100g: float | None
    raw_value: str
    qualifier: Qualifier
    source_url: str | None = None
    license_name: str | None = None


class FoodOut(BaseModel):
    id: UUID
    canonical_name: str
    group_name: str | None = None
    subgroup_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reference: NutritionReferenceOut | None = None
    match_score: float | None = None


class FoodWrite(BaseModel):
    canonical_name: str = Field(min_length=2, max_length=300)
    group_name: str | None = Field(default=None, max_length=180)
    subgroup_name: str | None = Field(default=None, max_length=180)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    carbs_per_100g: float | None = Field(default=None, ge=0, le=100)
    raw_value: str = Field(default="", max_length=80)
    qualifier: Qualifier = "exact"
    source: str = Field(default="manual", min_length=2, max_length=80)
    external_code: str | None = Field(default=None, max_length=80)
    source_version: str = Field(default="1", min_length=1, max_length=80)
    source_url: str | None = Field(default=None, max_length=1000)
    license_name: str | None = Field(default=None, max_length=120)

    model_config = {"extra": "forbid"}

    @field_validator("canonical_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.split())


class ImportResult(BaseModel):
    source: str
    source_version: str
    rows: int
    foods_created: int
    foods_updated: int
    duplicate: bool = False
