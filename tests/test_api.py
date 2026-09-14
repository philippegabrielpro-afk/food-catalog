from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.config import get_settings
from app.database import Base, get_db


def test_api_auth_manual_catalog_and_no_health_payload():
    settings = get_settings()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as db:
            yield db

    main_module.app.dependency_overrides[get_db] = override_get_db
    client = TestClient(main_module.app)
    try:
        assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}
        assert client.get("/ready").json() == {"status": "ready", "foods": 0}
        assert client.get("/v1/foods/search", params={"q": "riz"}).status_code == 401

        created = client.post(
            "/v1/admin/foods",
            headers={"X-API-Key": settings.admin_api_key},
            json={
                "canonical_name": "Riz familial cuit",
                "aliases": ["riz maison"],
                "tags": ["cuit", "fÃ©culent"],
                "carbs_per_100g": 30.5,
                "source": "manual",
                "external_code": "family-rice",
                "source_version": "1",
            },
        )
        assert created.status_code == 201
        food_id = created.json()["id"]
        assert client.get("/ready").json() == {"status": "ready", "foods": 1}

        changed_same_version = client.put(
            f"/v1/admin/foods/{food_id}",
            headers={"X-API-Key": settings.admin_api_key},
            json={
                "canonical_name": "Riz familial cuit",
                "aliases": ["riz maison"],
                "tags": ["cuit", "fÃ©culent"],
                "carbs_per_100g": 31.0,
                "source": "manual",
                "external_code": "family-rice",
                "source_version": "1",
            },
        )
        assert changed_same_version.status_code == 409

        changed_new_version = client.put(
            f"/v1/admin/foods/{food_id}",
            headers={"X-API-Key": settings.admin_api_key},
            json={
                "canonical_name": "Riz familial cuit",
                "aliases": ["riz maison"],
                "tags": ["cuit", "fÃ©culent"],
                "carbs_per_100g": 31.0,
                "source": "manual",
                "external_code": "family-rice",
                "source_version": "2",
            },
        )
        assert changed_new_version.status_code == 200

        latest_reference = client.get(
            "/v1/references/manual/family-rice",
            headers={"X-API-Key": settings.api_key},
        )
        assert latest_reference.status_code == 200
        assert latest_reference.json()["reference"]["source_version"] == "2"
        assert latest_reference.json()["reference"]["carbs_per_100g"] == 31.0

        historical_reference = client.get(
            "/v1/references/manual/family-rice",
            params={"source_version": "1"},
            headers={"X-API-Key": settings.api_key},
        )
        assert historical_reference.status_code == 200
        assert historical_reference.json()["reference"]["carbs_per_100g"] == 30.5

        missing_reference = client.get(
            "/v1/references/manual/unknown",
            headers={"X-API-Key": settings.api_key},
        )
        assert missing_reference.status_code == 404

        search = client.get(
            "/v1/foods/search",
            params={"q": "riz maison"},
            headers={"X-API-Key": settings.api_key},
        )
        assert search.status_code == 200
        assert search.json()[0]["id"] == food_id

        forbidden = client.post(
            "/v1/admin/foods",
            headers={"X-API-Key": settings.admin_api_key},
            json={
                "canonical_name": "Riz patient",
                "carbs_per_100g": 30,
                "patient_id": "Fleur",
            },
        )
        assert forbidden.status_code == 422
    finally:
        client.close()
        main_module.app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
