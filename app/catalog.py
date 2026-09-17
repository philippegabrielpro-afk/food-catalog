from __future__ import annotations

import json
import re
import unicodedata
from datetime import timezone
from difflib import SequenceMatcher
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .models import AdminAudit, Food, FoodAlias, FoodTag, NutritionReference
from .schemas import FoodWrite, ReferenceWrite


def record_audit(db: Session, action: str, after: dict, food_id=None, before=None) -> None:
    db.add(AdminAudit(
        food_id=food_id, action=action,
        before=json.loads(json.dumps(before, default=str)) if before is not None else None,
        after=json.loads(json.dumps(after, default=str)),
    ))


def commit_change(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Reference identity or labels already exist") from exc


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


def preferred_reference(food: Food) -> NutritionReference | None:
    preferred = [reference for reference in food.references if reference.preferred]
    candidates = preferred or list(food.references)
    return max(candidates, key=lambda reference: utc_timestamp(reference.created_at)) if candidates else None


def utc_timestamp(value) -> float:
    # SQLite drops timezone offsets, whereas fresh ORM values remain aware
    # when SessionLocal(expire_on_commit=False) is used. Interpret both as UTC.
    if value is None:
        return 0.0
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).timestamp()


def serialize_food(
    food: Food,
    match_score: float | None = None,
    reference_override: NutritionReference | None = None,
) -> dict:
    reference = reference_override or preferred_reference(food)
    reference_payload = None
    if reference:
        reference_payload = {
            "source": reference.source,
            "external_code": reference.external_code,
            "source_version": reference.source_version,
            "carbs_per_100g": reference.carbs_per_100g,
            "raw_value": reference.raw_value,
            "qualifier": reference.qualifier,
            "source_url": reference.source_url,
            "license_name": reference.license_name,
        }
    return {
        "id": food.id,
        "canonical_name": food.canonical_name,
        "group_name": food.group_name,
        "subgroup_name": food.subgroup_name,
        "aliases": sorted(alias.value for alias in food.aliases),
        "tags": sorted(tag.value for tag in food.tags),
        "reference": reference_payload,
        "match_score": round(match_score, 4) if match_score is not None else None,
    }


def _match_score(query: str, food: Food) -> float:
    candidates = [food.normalized_name]
    candidates.extend(alias.normalized_value for alias in food.aliases)
    candidates.extend(normalize_text(tag.value) for tag in food.tags)
    query_tokens = set(query.split())
    best = 0.0
    for candidate in candidates:
        candidate_tokens = set(candidate.split())
        common = query_tokens & candidate_tokens
        coverage = len(common) / max(len(query_tokens), 1)
        precision = len(common) / max(len(candidate_tokens), 1)
        sequence = SequenceMatcher(None, query, candidate).ratio()
        prefix_bonus = 0.05 if candidate.startswith(query) else 0.0
        best = max(best, min(1.0, 0.55 * coverage + 0.2 * precision + 0.25 * sequence + prefix_bonus))
    return best


def list_search(db: Session, query: str, limit: int) -> list[dict]:
    normalized = normalize_text(query)
    if len(normalized) < 2:
        return []
    foods = db.scalars(
        select(Food)
        .where(Food.active.is_(True))
        .options(
            selectinload(Food.aliases),
            selectinload(Food.tags),
            selectinload(Food.references),
        )
    ).all()
    ranked = sorted(
        ((food, _match_score(normalized, food)) for food in foods),
        key=lambda item: (-item[1], len(item[0].canonical_name), item[0].canonical_name),
    )
    return [serialize_food(food, score) for food, score in ranked[:limit] if score > 0]


def get_food(db: Session, food_id: UUID) -> Food:
    food = db.scalar(
        select(Food)
        .where(Food.id == food_id, Food.active.is_(True))
        .options(
            selectinload(Food.aliases),
            selectinload(Food.tags),
            selectinload(Food.references),
        )
    )
    if not food:
        raise HTTPException(status_code=404, detail="Food not found")
    return food


def get_food_by_reference(
    db: Session,
    source: str,
    external_code: str,
    source_version: str | None = None,
) -> dict:
    statement = (
        select(Food, NutritionReference)
        .join(
            NutritionReference,
            NutritionReference.food_id == Food.id,
        )
        .where(
            Food.active.is_(True),
            NutritionReference.source == source,
            NutritionReference.external_code == external_code,
        )
        .options(
            selectinload(Food.aliases),
            selectinload(Food.tags),
            selectinload(Food.references),
        )
    )

    if source_version is not None:
        statement = statement.where(
            NutritionReference.source_version == source_version
        )
    else:
        statement = statement.order_by(
            NutritionReference.created_at.desc()
        )

    row = db.execute(statement).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reference not found")

    food, reference = row
    return serialize_food(food, reference_override=reference)


def _replace_labels(food: Food, aliases: list[str], tags: list[str]) -> None:
    requested_aliases: dict[str, str] = {}
    for value in aliases:
        cleaned = " ".join(value.split())
        normalized = normalize_text(cleaned)
        if normalized and normalized not in requested_aliases:
            requested_aliases[normalized] = cleaned

    existing_aliases = {alias.normalized_value: alias for alias in food.aliases}
    updated_aliases = []
    for normalized, value in requested_aliases.items():
        alias = existing_aliases.get(normalized)
        if alias is None:
            alias = FoodAlias(
                value=value,
                normalized_value=normalized,
                kind="synonym",
            )
        else:
            alias.value = value
            alias.kind = "synonym"
        updated_aliases.append(alias)
    food.aliases = updated_aliases

    requested_tags = []
    seen_tags = set()
    for value in tags:
        cleaned = " ".join(value.split()).casefold()
        if cleaned and cleaned not in seen_tags:
            seen_tags.add(cleaned)
            requested_tags.append(cleaned)

    existing_tags = {tag.value: tag for tag in food.tags}
    food.tags = [
        existing_tags.get(value) or FoodTag(value=value)
        for value in requested_tags
    ]


def _set_reference(food: Food, payload: ReferenceWrite) -> None:
    if normalize_text(payload.source) == "ciqual":
        raise HTTPException(status_code=422, detail="Ciqual is reserved for official imports; use a manual source")
    external_code = payload.external_code or f"manual:{food.id}"
    raw_value = payload.raw_value or ("" if payload.carbs_per_100g is None else str(payload.carbs_per_100g))
    existing = next(
        (
            reference
            for reference in food.references
            if reference.source == payload.source
            and reference.external_code == external_code
            and reference.source_version == payload.source_version
        ),
        None,
    )
    if existing:
        current = (
            existing.carbs_per_100g,
            existing.raw_value,
            existing.qualifier,
            existing.source_url,
            existing.license_name,
        )
        requested = (
            payload.carbs_per_100g,
            raw_value,
            payload.qualifier,
            payload.source_url,
            payload.license_name,
        )
        if current != requested:
            raise HTTPException(
                status_code=409,
                detail="Nutrition references are immutable; use a new source_version",
            )
        for reference in food.references:
            reference.preferred = False
        existing.preferred = True
        return
    for reference in food.references:
        reference.preferred = False
    food.references.append(
        NutritionReference(
            source=payload.source,
            external_code=external_code,
            source_version=payload.source_version,
            carbs_per_100g=payload.carbs_per_100g,
            raw_value=raw_value,
            qualifier=payload.qualifier,
            source_url=payload.source_url,
            license_name=payload.license_name,
            preferred=True,
        )
    )


def create_food(db: Session, payload: FoodWrite) -> dict:
    food = Food(
        canonical_name=payload.canonical_name,
        normalized_name=normalize_text(payload.canonical_name),
        group_name=payload.group_name,
        subgroup_name=payload.subgroup_name,
    )
    db.add(food)
    db.flush()
    _replace_labels(food, payload.aliases, payload.tags)
    _set_reference(food, payload)
    record_audit(db, "food_created", serialize_food(food), food.id)
    commit_change(db)
    return serialize_food(get_food(db, food.id))


def update_food(db: Session, food_id: UUID, payload: FoodWrite) -> dict:
    food = get_food(db, food_id)
    before = serialize_food(food)
    food.canonical_name = payload.canonical_name
    food.normalized_name = normalize_text(payload.canonical_name)
    food.group_name = payload.group_name
    food.subgroup_name = payload.subgroup_name
    _replace_labels(food, payload.aliases, payload.tags)
    _set_reference(food, payload)
    record_audit(db, "food_updated", serialize_food(food), food.id, before)
    commit_change(db)
    return serialize_food(get_food(db, food.id))
