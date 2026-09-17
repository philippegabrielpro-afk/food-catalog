"""Admin-only read APIs, metadata editing and immutable reference history."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import require_admin_key
from .catalog import (
    _replace_labels, _set_reference, commit_change, get_food, normalize_text,
    record_audit, serialize_food, utc_timestamp,
)
from .database import get_db
from .models import AdminAudit, Food, FoodAlias, FoodTag, NutritionReference, SourceImport, now_utc
from .schemas import (
    AdminFoodOut, AuditOut, FoodMetadataWrite, FoodPageOut, ReferenceWrite, SourceImportOut,
)

router = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_admin_key)], tags=["administration"])


def detail_payload(food: Food) -> dict:
    payload = serialize_food(food)
    payload["updated_at"] = food.updated_at
    payload["references"] = [
        {
            **serialize_food(food, reference_override=reference)["reference"],
            "id": reference.id,
            "preferred": reference.preferred,
            "created_at": reference.created_at,
        }
        for reference in sorted(food.references, key=lambda item: (utc_timestamp(item.created_at), str(item.id)), reverse=True)
    ]
    return payload


@router.get("/foods", response_model=FoodPageOut)
def browse(
    q: str = Query(default="", max_length=300),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    statement = select(Food).where(Food.active.is_(True))
    # Normalize tags for accent-insensitive matching without changing their
    # published labels. Only IDs/labels are read; food pagination stays in SQL.
    tokens = normalize_text(q).split()
    tag_rows = db.execute(select(FoodTag.food_id, FoodTag.value)).all() if tokens else []
    for token in tokens:
        tag_ids = {food_id for food_id, value in tag_rows if token in normalize_text(value)}
        statement = statement.where(or_(
            Food.normalized_name.contains(token),
            Food.aliases.any(FoodAlias.normalized_value.contains(token)),
            Food.id.in_(tag_ids),
        ))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    foods = db.scalars(statement.order_by(Food.normalized_name, Food.id).offset(offset).limit(limit)).all()
    return {"items": [serialize_food(food) for food in foods], "total": total, "offset": offset, "limit": limit}


@router.get("/foods/{food_id}", response_model=AdminFoodOut)
def detail(food_id: UUID, db: Session = Depends(get_db)):
    return detail_payload(get_food(db, food_id))


@router.patch("/foods/{food_id}", response_model=AdminFoodOut)
def metadata(food_id: UUID, payload: FoodMetadataWrite, db: Session = Depends(get_db)):
    food = get_food(db, food_id)
    before = serialize_food(food)
    food.canonical_name = payload.canonical_name
    food.normalized_name = normalize_text(payload.canonical_name)
    food.group_name = payload.group_name
    food.subgroup_name = payload.subgroup_name
    food.updated_at = now_utc()
    _replace_labels(food, payload.aliases, payload.tags)
    record_audit(db, "metadata_updated", serialize_food(food), food.id, before)
    commit_change(db)
    return detail_payload(get_food(db, food_id))


@router.post("/foods/{food_id}/references", response_model=AdminFoodOut, status_code=201)
def add_reference(food_id: UUID, payload: ReferenceWrite, db: Session = Depends(get_db)):
    food = get_food(db, food_id)
    code = payload.external_code or f"manual:{food.id}"
    existing = db.scalar(select(NutritionReference).where(
        NutritionReference.source == payload.source,
        NutritionReference.external_code == code,
        NutritionReference.source_version == payload.source_version,
    ))
    if existing:
        raise HTTPException(status_code=409, detail="This reference version already exists; use a new version")
    before = serialize_food(food)
    _set_reference(food, payload)
    food.updated_at = now_utc()
    record_audit(db, "reference_added", serialize_food(food), food.id, before)
    commit_change(db)
    return detail_payload(get_food(db, food_id))


@router.post("/foods/{food_id}/references/{reference_id}/prefer", response_model=AdminFoodOut)
def prefer_reference(food_id: UUID, reference_id: UUID, db: Session = Depends(get_db)):
    food = get_food(db, food_id)
    chosen = next((item for item in food.references if item.id == reference_id), None)
    if not chosen:
        raise HTTPException(status_code=404, detail="Reference not found for this food")
    before = serialize_food(food)
    for reference in food.references:
        reference.preferred = reference.id == chosen.id
    food.updated_at = now_utc()
    record_audit(db, "preferred_reference_changed", serialize_food(food), food.id, before)
    commit_change(db)
    return detail_payload(get_food(db, food_id))


@router.get("/imports", response_model=list[SourceImportOut])
def imports(limit: int = Query(default=50, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(SourceImport).order_by(SourceImport.imported_at.desc(), SourceImport.id).limit(limit)).all()


@router.get("/audit", response_model=list[AuditOut])
def audit(
    food_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    statement = select(AdminAudit)
    if food_id:
        statement = statement.where(AdminAudit.food_id == food_id)
    return db.scalars(statement.order_by(AdminAudit.created_at.desc(), AdminAudit.id).limit(limit)).all()
