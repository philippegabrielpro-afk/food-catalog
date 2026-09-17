from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_api_has_access_network_but_database_and_backup_remain_internal():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = config["services"]
    assert services["api"]["ports"] == ["127.0.0.1:8080:8080"]
    assert set(services["api"]["networks"]) == {"private", "access"}
    assert services["db"]["networks"] == ["private"]
    assert services["backup"]["networks"] == ["private"]
    assert "ports" not in services["db"] and "ports" not in services["backup"]
    assert config["networks"]["private"]["internal"] is True
    assert config["networks"]["access"]["internal"] is False
    # The existing PostgreSQL volume declaration is unchanged.
    assert config["volumes"] == {"catalog_postgres_data": None}
    assert services["db"]["volumes"] == ["catalog_postgres_data:/var/lib/postgresql/data"]


def test_backup_service_uses_separate_host_storage_and_does_not_mount_database():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    backup = config["services"]["backup"]
    assert backup["image"] == "postgres:17-alpine"
    assert backup["read_only"] is True and backup["cap_drop"] == ["ALL"]
    assert backup["environment"]["CATALOG_BACKUP_INTERVAL_SECONDS"] == "86400"
    assert backup["depends_on"]["api"]["condition"] == "service_healthy"
    assert "FOOD_CATALOG_ADMIN_API_KEY" not in backup["environment"]
    assert backup["healthcheck"]["test"] == ["CMD", "/bin/sh", "/usr/local/bin/catalog-backup-healthcheck.sh"]
    assert {volume["target"] for volume in backup["volumes"]} == {
        "/backups", "/usr/local/bin/catalog-backup.sh", "/usr/local/bin/catalog-backup-healthcheck.sh",
    }
    assert all(volume["bind"]["create_host_path"] is False for volume in backup["volumes"])
    assert all(volume["read_only"] for volume in backup["volumes"][1:])


def test_scripts_have_lf_endings_and_git_and_docker_ignore_backups_and_secrets():
    for name in ("backup.sh", "backup-healthcheck.sh"):
        content = (ROOT / "scripts" / name).read_bytes()
        assert content.startswith(b"#!/bin/sh\n") and b"\r" not in content
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert "/backups/" in gitignore and "*.dump" in gitignore and ".env" in gitignore
    assert ".env" in dockerignore and "*.dump" in dockerignore and "backups" in dockerignore


def test_ci_runs_docker_network_backup_and_isolated_restore_integration():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["tests"]["steps"]
    assert any(step.get("run") == "python scripts/verify-compose.py" for step in steps)
