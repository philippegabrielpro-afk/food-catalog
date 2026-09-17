from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from .database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


UUID_TYPE = Uuid().with_variant(UUID(as_uuid=True), "postgresql")


class Food(Base):
    __tablename__ = "food"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    group_name: Mapped[str | None] = mapped_column(String(180), index=True)
    subgroup_name: Mapped[str | None] = mapped_column(String(180), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    aliases: Mapped[list[FoodAlias]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    tags: Mapped[list[FoodTag]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    references: Mapped[list[NutritionReference]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class FoodAlias(Base):
    __tablename__ = "food_alias"
    __table_args__ = (UniqueConstraint("food_id", "normalized_value", name="uq_food_alias_food_value"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    food_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("food.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(300))
    normalized_value: Mapped[str] = mapped_column(String(300), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="synonym")


class FoodTag(Base):
    __tablename__ = "food_tag"
    __table_args__ = (UniqueConstraint("food_id", "value", name="uq_food_tag_food_value"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    food_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("food.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(100), index=True)


class NutritionReference(Base):
    __tablename__ = "nutrition_reference"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_code",
            "source_version",
            name="uq_nutrition_reference_source_code_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    food_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("food.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    external_code: Mapped[str] = mapped_column(String(80), index=True)
    source_version: Mapped[str] = mapped_column(String(80), index=True)
    carbs_per_100g: Mapped[float | None] = mapped_column(Float)
    raw_value: Mapped[str] = mapped_column(String(80))
    qualifier: Mapped[str] = mapped_column(String(20), default="exact")
    source_url: Mapped[str | None] = mapped_column(Text)
    license_name: Mapped[str | None] = mapped_column(String(120))
    preferred: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SourceImport(Base):
    __tablename__ = "source_import"
    __table_args__ = (
        UniqueConstraint("source", "source_version", "file_sha256", name="uq_source_import_version_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(80), index=True)
    source_version: Mapped[str] = mapped_column(String(80), index=True)
    file_sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="processing")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AdminAudit(Base):
    """Generic catalog changes only. Never store credentials or health data."""

    __tablename__ = "admin_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    food_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, index=True)
    action: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(80), default="shared-admin-key")
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)
