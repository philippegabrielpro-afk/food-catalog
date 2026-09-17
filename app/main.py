from contextlib import asynccontextmanager
from pathlib import Path as FilePath
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_admin_key, require_api_key
from .admin import router as admin_router
from .catalog import (
    create_food,
    get_food,
    get_food_by_reference,
    list_search,
    record_audit,
    serialize_food,
    update_food,
)
from .config import get_settings
from .database import SessionLocal, get_db
from .importer import ImportVersionConflict, import_ciqual
from .models import Food
from .schemas import FoodOut, FoodWrite, ImportResult


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().auto_import_ciqual:
        with SessionLocal() as db:
            import_ciqual(db)
    yield


app = FastAPI(
    title="Food Catalog API",
    version="0.2.0",
    description=(
        "Generic food composition and search service. "
        "Do not send patient identifiers, meals, glucose data or medical context."
    ),
    lifespan=lifespan,
)

app.include_router(admin_router)
ADMIN_STATIC = FilePath(__file__).parent / "static" / "admin"
app.mount("/admin/assets", StaticFiles(directory=ADMIN_STATIC), name="admin-assets")


@app.middleware("http")
async def admin_security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/admin" or request.url.path.startswith(("/admin/", "/v1/admin/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'none'"
        )
    return response


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(ADMIN_STATIC / "index.html")


@app.get("/admin/", include_in_schema=False)
def admin_redirect():
    return RedirectResponse("/admin")


@app.get("/health", tags=["operations"])
def health():
    return {"status": "ok", "version": app.version}


@app.get("/ready", tags=["operations"])
def readiness(db: Session = Depends(get_db)):
    food_count = db.scalar(select(func.count()).select_from(Food)) or 0
    return {"status": "ready", "foods": food_count}


@app.get(
    "/v1/foods/search",
    response_model=list[FoodOut],
    dependencies=[Depends(require_api_key)],
    tags=["catalog"],
)
def search_foods(
    q: str = Query(min_length=2, max_length=300),
    limit: int = Query(default=8, ge=1, le=30),
    db: Session = Depends(get_db),
):
    return list_search(db, q, limit)


@app.get(
    "/v1/foods/{food_id}",
    response_model=FoodOut,
    dependencies=[Depends(require_api_key)],
    tags=["catalog"],
)
def food_detail(food_id: UUID, db: Session = Depends(get_db)):
    return serialize_food(get_food(db, food_id))


@app.get(
    "/v1/references/{source}/{external_code}",
    response_model=FoodOut,
    dependencies=[Depends(require_api_key)],
    tags=["catalog"],
)
def reference_detail(
    source: str = Path(min_length=2, max_length=80),
    external_code: str = Path(min_length=1, max_length=80),
    source_version: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db),
):
    return get_food_by_reference(
        db,
        source,
        external_code,
        source_version,
    )


@app.post(
    "/v1/admin/foods",
    response_model=FoodOut,
    status_code=201,
    dependencies=[Depends(require_admin_key)],
    tags=["administration"],
)
def admin_create_food(payload: FoodWrite, db: Session = Depends(get_db)):
    return create_food(db, payload)


@app.put(
    "/v1/admin/foods/{food_id}",
    response_model=FoodOut,
    dependencies=[Depends(require_admin_key)],
    tags=["administration"],
)
def admin_update_food(food_id: UUID, payload: FoodWrite, db: Session = Depends(get_db)):
    return update_food(db, food_id, payload)


@app.post(
    "/v1/admin/imports/ciqual",
    response_model=ImportResult,
    dependencies=[Depends(require_admin_key)],
    tags=["administration"],
)
def admin_import_ciqual(db: Session = Depends(get_db)):
    try:
        result = import_ciqual(db, commit=False)
        record_audit(db, "ciqual_import_requested", result)
        db.commit()
        return result
    except ImportVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
