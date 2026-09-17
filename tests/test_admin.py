import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.config import get_settings
from app.database import Base, get_db
from app.importer import ImportVersionConflict
from app.models import AdminAudit, Food, NutritionReference, SourceImport


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    main_module.app.dependency_overrides[get_db] = override
    # Existing API tests inject their own database and deliberately skip lifespan.
    test_client = TestClient(main_module.app)
    test_client.engine = engine
    test_client.headers.update({"X-API-Key": get_settings().admin_api_key})
    try:
        yield test_client
    finally:
        test_client.close()
        main_module.app.dependency_overrides.clear()
        engine.dispose()


def create(client, name="Riz basmati cuit", code="rice", value=32.9):
    response = client.post("/v1/admin/foods", json={
        "canonical_name": name, "external_code": code, "carbs_per_100g": value,
        "aliases": ["riz maison"] if code == "rice" else [], "tags": ["cuit"],
    })
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("path", ["/v1/admin/foods", "/v1/admin/imports", "/v1/admin/audit", f"/v1/admin/foods/{uuid4()}"])
def test_admin_reads_do_not_accept_consumer_key(client, path):
    assert client.get(path, headers={"X-API-Key": ""}).status_code == 401
    assert client.get(path, headers={"X-API-Key": get_settings().api_key}).status_code == 401
    assert client.get("/v1/foods/search?q=riz").status_code == 401  # Admin key is not a consumer key.


@pytest.mark.parametrize("method,path", [
    ("post", "/v1/admin/foods"), ("put", f"/v1/admin/foods/{uuid4()}"),
    ("patch", f"/v1/admin/foods/{uuid4()}"),
    ("post", f"/v1/admin/foods/{uuid4()}/references"),
    ("post", f"/v1/admin/foods/{uuid4()}/references/{uuid4()}/prefer"),
    ("post", "/v1/admin/imports/ciqual"),
])
def test_admin_mutations_require_admin_key(client, method, path):
    response = getattr(client, method)(path, json={}, headers={"X-API-Key": get_settings().api_key})
    assert response.status_code == 401


def test_browse_pagination_and_metadata_do_not_rewrite_references(client):
    rice = create(client)
    create(client, "Compote de pomme", "apple", 12)
    page = client.get("/v1/admin/foods?limit=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert client.get("/v1/admin/foods?limit=1&offset=1").json()["items"][0]["id"] != page["items"][0]["id"]
    assert client.get("/v1/admin/foods?offset=100").json()["items"] == []
    assert client.get("/v1/admin/foods?q=riz+maison+cuit").json()["total"] == 1
    assert client.get("/v1/admin/foods?q=doesnotexist").json()["total"] == 0
    before = client.get(f'/v1/admin/foods/{rice["id"]}').json()
    payload = {"canonical_name": "  Riz basmati  cuit maison ", "aliases": ["riz maison", "RIZ MAISON"], "tags": ["Cuit", "cuit"], "group_name": "céréales"}
    for _ in range(2):
        response = client.patch(f'/v1/admin/foods/{rice["id"]}', json=payload)
        assert response.status_code == 200, response.text
    after = response.json()
    assert after["canonical_name"] == "Riz basmati cuit maison"
    assert after["references"] == before["references"]
    assert after["aliases"] == ["riz maison"] and after["tags"] == ["cuit"]
    assert client.patch(f'/v1/admin/foods/{rice["id"]}', json={**payload, "patient_id": "no-health"}).status_code == 422
    assert client.get("/v1/admin/foods?limit=101").status_code == 422
    payload["tags"] = ["féculent"]
    assert client.patch(f'/v1/admin/foods/{rice["id"]}', json=payload).status_code == 200
    assert client.get("/v1/admin/foods?q=feculent").json()["total"] == 1


def test_reference_history_conflicts_preference_and_atomic_audit(client):
    rice = create(client)
    other = create(client, "Autre riz", "other", 20)
    path = f'/v1/admin/foods/{rice["id"]}'
    ref_payload = {"source": "manual", "external_code": "rice", "source_version": "2", "carbs_per_100g": 30}
    response = client.post(f"{path}/references", json=ref_payload)
    assert response.status_code == 201, response.text
    detail = response.json()
    assert detail["reference"]["carbs_per_100g"] == 30
    assert len(detail["references"]) == 2
    old = next(item for item in detail["references"] if item["source_version"] == "1")
    assert old["carbs_per_100g"] == 32.9
    assert client.post(f"{path}/references", json=ref_payload).status_code == 409
    assert client.post(f'/v1/admin/foods/{other["id"]}/references', json=ref_payload).status_code == 409
    assert client.post(f"{path}/references", json={**ref_payload, "carbs_per_100g": 90}).status_code == 409
    response = client.post(f'{path}/references/{old["id"]}/prefer')
    assert response.status_code == 200
    assert response.json()["reference"]["carbs_per_100g"] == 32.9
    assert sum(item["preferred"] for item in response.json()["references"]) == 1
    assert client.post(f'{path}/references/{uuid4()}/prefer').status_code == 404
    assert client.post(f'/v1/admin/foods/{other["id"]}/references/{old["id"]}/prefer').status_code == 404
    audit = client.get(f'/v1/admin/audit?food_id={rice["id"]}').json()
    assert len(audit) == 3  # Failed writes do not persist audit entries.
    assert audit[0]["action"] == "preferred_reference_changed"
    assert audit[0]["before"]["reference"]["carbs_per_100g"] == 30
    assert audit[0]["after"]["reference"]["carbs_per_100g"] == 32.9
    assert get_settings().admin_api_key not in str(audit)
    consumer = {"X-API-Key": get_settings().api_key}
    historical = client.get("/v1/references/manual/rice?source_version=2", headers=consumer)
    assert historical.json()["reference"]["carbs_per_100g"] == 30


@pytest.mark.parametrize("source", ["Ciqual", "ciqual", " CIQUAL ", "CiQuAl"])
def test_official_ciqual_source_cannot_be_fabricated(client, source):
    rice = create(client)
    payload = {"source": source, "external_code": "9125", "source_version": "invented", "carbs_per_100g": 30}
    assert client.post(f'/v1/admin/foods/{rice["id"]}/references', json=payload).status_code == 422
    assert client.post("/v1/admin/foods", json={"canonical_name": "Faux Ciqual", **payload}).status_code == 422
    assert client.get("/v1/admin/foods").json()["total"] == 1


@pytest.mark.parametrize("extra", [
    {"canonical_name": "  "}, {"tags": ["x" * 101]}, {"aliases": ["x" * 301]},
    {"source": "  "}, {"source_version": " "}, {"source_url": "javascript:alert(1)"},
    {"carbs_per_100g": 101}, {"carbs_per_100g": -1},
    {"carbs_per_100g": 30, "qualifier": "traces"}, {"carbs_per_100g": 30, "qualifier": "missing"},
])
def test_invalid_generic_fields_are_rejected(client, extra):
    assert client.post("/v1/admin/foods", json={"canonical_name": "Riz cuit", "carbs_per_100g": 30, **extra}).status_code == 422


def test_global_duplicate_creation_rolls_back_food_and_audit(client):
    create(client)
    response = client.post("/v1/admin/foods", json={"canonical_name": "Riz doublon", "external_code": "rice", "carbs_per_100g": 30})
    assert response.status_code == 409
    assert client.get("/v1/admin/foods").json()["total"] == 1
    assert len(client.get("/v1/admin/audit").json()) == 1


def test_admin_static_security_headers_and_no_persistence(client):
    for path in ["/admin", "/admin/assets/admin.js", "/admin/assets/admin.css", "/v1/admin/foods"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
    script = client.get("/admin/assets/admin.js").text
    assert "localStorage" not in script and "sessionStorage" not in script and "document.cookie" not in script
    assert get_settings().admin_api_key not in client.get("/admin").text
    assert client.get("/admin/").status_code == 200


def test_import_tracking_and_duplicate_actions(client, monkeypatch):
    def fake_import(db, *, commit):
        existing = db.scalar(select(SourceImport))
        if not existing:
            db.add(SourceImport(source="Ciqual", source_version="test", file_sha256="a" * 64, row_count=1, status="processed"))
            db.commit()
        return {"source": "Ciqual", "source_version": "test", "rows": 1, "foods_created": 0, "foods_updated": 0, "duplicate": bool(existing)}

    monkeypatch.setattr(main_module, "import_ciqual", fake_import)
    assert client.post("/v1/admin/imports/ciqual").json()["duplicate"] is False
    assert client.post("/v1/admin/imports/ciqual").json()["duplicate"] is True
    assert len(client.get("/v1/admin/imports").json()) == 1
    assert len(client.get("/v1/admin/audit").json()) == 2
    with Session(client.engine) as db:
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 2

    def conflict(_, *, commit):
        raise ImportVersionConflict("Changed source hash")

    monkeypatch.setattr(main_module, "import_ciqual", conflict)
    assert client.post("/v1/admin/imports/ciqual").status_code == 409
    assert len(client.get("/v1/admin/audit").json()) == 2


def test_alembic_upgrade_keeps_existing_food_and_references(tmp_path):
    env = {**os.environ, "FOOD_CATALOG_DATABASE_URL": f"sqlite:///{tmp_path / 'migration.db'}", "FOOD_CATALOG_AUTO_IMPORT_CIQUAL": "false"}
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0001_initial"], cwd=root, env=env, check=True, capture_output=True)
    engine = create_engine(env["FOOD_CATALOG_DATABASE_URL"])
    with Session(engine) as db:
        food = Food(canonical_name="Existing rice", normalized_name="existing rice")
        db.add(food)
        db.flush()
        db.add(NutritionReference(food_id=food.id, source="manual", external_code="old", source_version="1", carbs_per_100g=30, raw_value="30", qualifier="exact"))
        db.commit()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, check=True, capture_output=True)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Food)) == 1
        assert db.scalar(select(func.count()).select_from(NutritionReference)) == 1
        assert db.scalar(select(func.count()).select_from(AdminAudit)) == 0
    engine.dispose()


def test_full_official_catalog_admin_correction_and_return_to_ciqual(client):
    result = client.post("/v1/admin/imports/ciqual")
    assert result.status_code == 200, result.text
    assert result.json()["rows"] == 3484
    assert client.get("/v1/admin/foods").json()["total"] == 3484
    foods = client.get("/v1/admin/foods?q=riz+basmati+cuit").json()["items"]
    food = next(item for item in foods if item["reference"]["external_code"] == "9125")
    path = f'/v1/admin/foods/{food["id"]}'
    original = client.get(path).json()["references"][0]
    assert original["carbs_per_100g"] == 32.9
    corrected = client.post(f"{path}/references", json={"source": "manual", "source_version": "1", "carbs_per_100g": 30})
    assert corrected.status_code == 201
    assert corrected.json()["reference"]["carbs_per_100g"] == 30
    assert len(corrected.json()["references"]) == 2
    assert client.post("/v1/admin/imports/ciqual").json()["duplicate"] is True
    assert client.get(path).json()["reference"]["source"] == "manual"
    assert client.post(f'{path}/references/{original["id"]}/prefer').json()["reference"]["source"] == "Ciqual"
    consumer = {"X-API-Key": get_settings().api_key}
    historical = client.get("/v1/references/Ciqual/9125?source_version=2025-11-03", headers=consumer)
    assert historical.json()["reference"]["carbs_per_100g"] == 32.9
    assert len(client.get("/v1/admin/imports").json()) == 1
    assert len(client.get("/v1/admin/audit").json()) == 4


def test_import_and_audit_are_one_transaction(client, monkeypatch):
    def pending_import(db, *, commit):
        assert commit is False
        db.add(SourceImport(source="Ciqual", source_version="test", file_sha256="b" * 64, row_count=1, status="processed"))
        db.flush()
        return {"source": "Ciqual", "source_version": "test", "rows": 1, "foods_created": 0, "foods_updated": 0, "duplicate": False}

    def fail_audit(*args):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr(main_module, "import_ciqual", pending_import)
    monkeypatch.setattr(main_module, "record_audit", fail_audit)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        client.post("/v1/admin/imports/ciqual")
    assert client.get("/v1/admin/imports").json() == []
