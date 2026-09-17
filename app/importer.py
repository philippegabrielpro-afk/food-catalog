from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .catalog import normalize_text
from .models import Food, FoodAlias, FoodTag, NutritionReference, SourceImport


CIQUAL_SOURCE = "Ciqual"
CIQUAL_VERSION = "2025-11-03"
CIQUAL_SOURCE_URL = "https://doi.org/10.57745/RDMHWY"
CIQUAL_LICENSE = "Licence Ouverte 2.0 (Etalab)"
CIQUAL_DATA_FILE = Path(__file__).parent / "data" / "ciqual-2025-foods.csv"


class ImportVersionConflict(ValueError):
    """Raised when a published source version no longer matches its imported file."""


def _add_tag(food: Food, value: str | None) -> None:
    cleaned = (value or "").strip().casefold()
    if cleaned and all(tag.value != cleaned for tag in food.tags):
        food.tags.append(FoodTag(value=cleaned))


def import_ciqual(db: Session, path: Path = CIQUAL_DATA_FILE, *, commit: bool = True) -> dict:
    content = path.read_bytes()
    file_sha256 = hashlib.sha256(content).hexdigest()
    previous = db.scalar(
        select(SourceImport).where(
            SourceImport.source == CIQUAL_SOURCE,
            SourceImport.source_version == CIQUAL_VERSION,
            SourceImport.file_sha256 == file_sha256,
            SourceImport.status == "processed",
        )
    )
    if previous:
        return {
            "source": CIQUAL_SOURCE,
            "source_version": CIQUAL_VERSION,
            "rows": previous.row_count,
            "foods_created": 0,
            "foods_updated": 0,
            "duplicate": True,
        }

    same_version = db.scalar(
        select(SourceImport).where(
            SourceImport.source == CIQUAL_SOURCE,
            SourceImport.source_version == CIQUAL_VERSION,
            SourceImport.status == "processed",
        )
    )
    if same_version:
        raise ImportVersionConflict(
            f"{CIQUAL_SOURCE} {CIQUAL_VERSION} was already imported with a different SHA-256"
        )

    batch = SourceImport(
        source=CIQUAL_SOURCE,
        source_version=CIQUAL_VERSION,
        file_sha256=file_sha256,
    )
    db.add(batch)
    db.flush()
    created = 0
    updated = 0

    try:
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"), newline="")))
        for row in rows:
            code = row["ciqual_code"].strip()
            prior_reference = db.scalar(
                select(NutritionReference).where(
                    NutritionReference.source == CIQUAL_SOURCE,
                    NutritionReference.external_code == code,
                ).order_by(NutritionReference.created_at.desc())
            )
            if prior_reference:
                food = db.get(Food, prior_reference.food_id)
                updated += 1
            else:
                food = Food(
                    canonical_name=row["name_fr"].strip(),
                    normalized_name=normalize_text(row["name_fr"]),
                    group_name=row["group_name_fr"].strip() or None,
                    subgroup_name=row["subgroup_name_fr"].strip() or None,
                )
                db.add(food)
                db.flush()
                created += 1

            old_name = food.canonical_name
            new_name = row["name_fr"].strip()
            if old_name != new_name and all(alias.normalized_value != normalize_text(old_name) for alias in food.aliases):
                food.aliases.append(
                    FoodAlias(value=old_name, normalized_value=normalize_text(old_name), kind="previous_name")
                )
            food.canonical_name = new_name
            food.normalized_name = normalize_text(new_name)
            food.group_name = row["group_name_fr"].strip() or None
            food.subgroup_name = row["subgroup_name_fr"].strip() or None
            _add_tag(food, food.group_name)
            _add_tag(food, food.subgroup_name)
            has_non_ciqual_preferred = any(
                reference.preferred and reference.source != CIQUAL_SOURCE
                for reference in food.references
            )
            for reference in food.references:
                if reference.source == CIQUAL_SOURCE:
                    reference.preferred = False

            numeric = row["carbs_g_100g"].strip()
            db.add(
                NutritionReference(
                    food_id=food.id,
                    source=CIQUAL_SOURCE,
                    external_code=code,
                    source_version=CIQUAL_VERSION,
                    carbs_per_100g=float(numeric) if numeric else None,
                    raw_value=row["carbs_raw"].strip(),
                    qualifier=row["carbs_qualifier"].strip(),
                    source_url=CIQUAL_SOURCE_URL,
                    license_name=CIQUAL_LICENSE,
                    preferred=not has_non_ciqual_preferred,
                )
            )
        batch.row_count = len(rows)
        batch.status = "processed"
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        db.rollback()
        raise

    return {
        "source": CIQUAL_SOURCE,
        "source_version": CIQUAL_VERSION,
        "rows": len(rows),
        "foods_created": created,
        "foods_updated": updated,
        "duplicate": False,
    }
