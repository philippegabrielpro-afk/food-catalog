from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.importer as importer_module
from app.catalog import list_search
from app.database import Base
from app.importer import ImportVersionConflict, import_ciqual
from app.models import Food, NutritionReference


def test_ciqual_import_search_versioning_and_idempotency(tmp_path: Path, monkeypatch):
    source = tmp_path / "ciqual.csv"
    source.write_text(
        "ciqual_code,name_fr,group_name_fr,subgroup_name_fr,carbs_raw,carbs_g_100g,carbs_qualifier\n"
        '9125,"Riz basmati, cuit, sans sel ajouté",céréales,riz,"32,9",32.9,exact\n'
        '9999,"Riz complet, cuit",céréales,riz,"25,8",25.8,exact\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(importer_module, "CIQUAL_VERSION", "test-2025")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        first = import_ciqual(db, source)
        second = import_ciqual(db, source)
        assert first == {
            "source": "Ciqual",
            "source_version": "test-2025",
            "rows": 2,
            "foods_created": 2,
            "foods_updated": 0,
            "duplicate": False,
        }
        assert second["duplicate"] is True

        matches = list_search(db, "riz basmati cuit", 5)
        assert matches[0]["canonical_name"] == "Riz basmati, cuit, sans sel ajouté"
        assert matches[0]["reference"]["source"] == "Ciqual"
        assert matches[0]["reference"]["carbs_per_100g"] == 32.9
        assert matches[0]["reference"]["source_version"] == "test-2025"

        food = db.get(Food, matches[0]["id"])
        for reference in food.references:
            reference.preferred = False
        food.references.append(
            NutritionReference(
                source="manual",
                external_code=f"manual:{food.id}",
                source_version="1",
                carbs_per_100g=31.5,
                raw_value="31.5",
                qualifier="exact",
                preferred=True,
            )
        )
        db.commit()

        monkeypatch.setattr(importer_module, "CIQUAL_VERSION", "test-2026")
        upgraded = import_ciqual(db, source)
        assert upgraded["foods_updated"] == 2
        matches = list_search(db, "riz basmati cuit", 5)
        assert matches[0]["reference"]["source"] == "manual"
        assert matches[0]["reference"]["carbs_per_100g"] == 31.5

        source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with pytest.raises(ImportVersionConflict):
            import_ciqual(db, source)

    Base.metadata.drop_all(engine)
    engine.dispose()
