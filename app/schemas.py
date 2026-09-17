from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, field_validator, model_validator


Qualifier = Literal["exact", "less_than", "traces", "missing"]
UtcDateTime = Annotated[datetime, AfterValidator(lambda value: value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc))]


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


Alias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class FoodMetadataWrite(BaseModel):
    canonical_name: str = Field(min_length=2, max_length=300)
    group_name: str | None = Field(default=None, max_length=180)
    subgroup_name: str | None = Field(default=None, max_length=180)
    aliases: list[Alias] = Field(default_factory=list, max_length=100)
    tags: list[Tag] = Field(default_factory=list, max_length=100)

    model_config = {"extra": "forbid"}

    @field_validator("canonical_name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("group_name", "subgroup_name", mode="before")
    @classmethod
    def clean_group(cls, value):
        return (" ".join(value.split()) or None) if isinstance(value, str) else value


class ReferenceWrite(BaseModel):
    carbs_per_100g: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    raw_value: str = Field(default="", max_length=80)
    qualifier: Qualifier = "exact"
    source: str = Field(default="manual", min_length=2, max_length=80)
    external_code: str | None = Field(default=None, max_length=80)
    source_version: str = Field(default="1", min_length=1, max_length=80)
    source_url: str | None = Field(default=None, max_length=1000)
    license_name: str | None = Field(default=None, max_length=120)

    model_config = {"extra": "forbid"}

    @field_validator("source", "source_version", "external_code", mode="before")
    @classmethod
    def strip_identity(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("source_url")
    @classmethod
    def safe_source_url(cls, value):
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("Source URL must use http or https")
        return value or None

    @model_validator(mode="after")
    def consistent_qualifier(self):
        if self.qualifier in {"exact", "less_than"} and self.carbs_per_100g is None:
            # Preserve the existing API's empty-reference default as missing.
            if self.qualifier == "exact" and not self.raw_value:
                self.qualifier = "missing"
            else:
                raise ValueError("A numeric value is required for this qualifier")
        if self.qualifier in {"missing", "traces"} and self.carbs_per_100g is not None:
            raise ValueError("Missing/traces values must not contain an invented number")
        return self


class FoodWrite(FoodMetadataWrite, ReferenceWrite):
    pass


class ReferenceHistoryOut(NutritionReferenceOut):
    id: UUID
    preferred: bool
    created_at: UtcDateTime


class AdminFoodOut(FoodOut):
    references: list[ReferenceHistoryOut]
    updated_at: UtcDateTime


class FoodPageOut(BaseModel):
    items: list[FoodOut]
    total: int
    offset: int
    limit: int


class SourceImportOut(BaseModel):
    id: UUID
    source: str
    source_version: str
    file_sha256: str
    row_count: int
    status: str
    imported_at: UtcDateTime

    model_config = {"from_attributes": True}


class AuditOut(BaseModel):
    id: UUID
    food_id: UUID | None
    action: str
    actor: str
    before: dict | None
    after: dict
    created_at: UtcDateTime

    model_config = {"from_attributes": True}


class ImportResult(BaseModel):
    source: str
    source_version: str
    rows: int
    foods_created: int
    foods_updated: int
    duplicate: bool = False
