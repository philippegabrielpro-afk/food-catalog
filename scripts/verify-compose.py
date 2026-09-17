"""CI-only Docker integration: host port, dump, and isolated restoration.

Creates a fresh, randomly named Compose project from a sanitized temporary
source copy. Never reads the real .env or uses existing catalog volumes.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    if os.environ.get("CI") != "true":
        raise SystemExit("This integration check runs only in CI, not on the VPS.")
    if os.name != "posix" or not shutil.which("docker"):
        raise SystemExit("Linux with Docker Compose is required.")

    source = Path(__file__).resolve().parents[1]
    project = f"food-catalog-ci-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="food-catalog-compose-ci-") as directory:
        working = Path(directory) / "source"
        shutil.copytree(source, working, ignore=shutil.ignore_patterns(
            ".git", ".venv", ".env*", "__pycache__", ".pytest_cache",
            "*.db", "*.dump", "backups", "docker-compose.override.yml",
        ))
        backups = Path(directory) / "backups"
        backups.mkdir(mode=0o700)
        password = uuid.uuid4().hex + uuid.uuid4().hex
        env_file = working / ".env"
        env_file.write_text(
            f"POSTGRES_PASSWORD={password}\n"
            f"FOOD_CATALOG_API_KEY={uuid.uuid4().hex + uuid.uuid4().hex}\n"
            f"FOOD_CATALOG_ADMIN_API_KEY={uuid.uuid4().hex + uuid.uuid4().hex}\n"
            "FOOD_CATALOG_AUTO_IMPORT_CIQUAL=true\n",
            encoding="utf-8",
        )
        env_file.chmod(0o600)
        # Allocate a dynamic loopback-only port, to avoid any unrelated service.
        override = working / "ci-compose.yml"
        override.write_text(
            "services:\n  api:\n    ports: !override\n"
            "      - target: 8080\n        published: \"0\"\n"
            "        host_ip: 127.0.0.1\n        protocol: tcp\n",
            encoding="utf-8",
        )
        env = {
            **os.environ, "POSTGRES_PASSWORD": password,
            "FOOD_CATALOG_BACKUP_DIR": str(backups),
            "FOOD_CATALOG_BACKUP_UID": str(os.getuid()),
            "FOOD_CATALOG_BACKUP_GID": str(os.getgid()),
        }
        command = ["docker", "compose", "-p", project, "--env-file", str(env_file),
                   "-f", str(working / "docker-compose.yml"), "-f", str(override)]

        def compose(*args, check=True, capture=False):
            return subprocess.run(command + list(args), cwd=working, env=env,
                                  check=check, capture_output=capture, text=True, timeout=600)

        def inspect(container, expression):
            result = subprocess.run(["docker", "inspect", "--format", expression, container],
                                    check=True, capture_output=True, text=True, env=env, timeout=30)
            return json.loads(result.stdout)

        try:
            compose("config", "--quiet")
            compose("build", "api")
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "240")
            containers = {name: compose("ps", "-q", name, capture=True).stdout.strip()
                          for name in ("api", "db", "backup")}
            assert all(containers.values()), "Required CI containers missing"
            ports = inspect(containers["api"], "{{json .NetworkSettings.Ports}}")
            bindings = ports.get("8080/tcp") or []
            assert bindings and all(item["HostIp"] == "127.0.0.1" for item in bindings)
            assert len(bindings) == 1, "CI must use exactly one dynamic loopback port"
            binding = bindings[0]
            assert int(binding["HostPort"]) > 0
            for endpoint, expected in (("health", {"status": "ok", "version": "0.2.0"}),
                                       ("ready", {"status": "ready", "foods": 3484})):
                with urlopen(f'http://127.0.0.1:{binding["HostPort"]}/{endpoint}', timeout=10) as response:
                    assert json.load(response) == expected
            for service in ("db", "backup"):
                networks = inspect(containers[service], "{{json .NetworkSettings.Networks}}")
                assert set(networks) == {f"{project}_private"}
            api_networks = inspect(containers["api"], "{{json .NetworkSettings.Networks}}")
            assert set(api_networks) == {f"{project}_private", f"{project}_access"}

            dumps = sorted(backups.glob("food-catalog-*.dump"))
            assert dumps and dumps[-1].stat().st_size > 0
            assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in dumps)
            marker = (backups / ".last-success").read_bytes()
            dump_count = len(dumps)
            failed = compose("run", "--rm", "--no-deps", "-e", "POSTGRES_PASSWORD=ci-invalid-password",
                             "backup", "--once", check=False, capture=True)
            assert failed.returncode != 0, "Invalid database credentials unexpectedly worked"
            assert len(list(backups.glob("food-catalog-*.dump"))) == dump_count
            assert not list(backups.glob(".food-catalog-*")), "Failed dump left a partial file"
            assert (backups / ".last-success").read_bytes() == marker

            compose("cp", str(dumps[-1]), "db:/tmp/ci-catalog-restore.dump")
            compose("exec", "-T", "db", "createdb", "-U", "food_catalog", "food_catalog_restore_ci")
            compose("exec", "-T", "db", "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                    "-U", "food_catalog", "-d", "food_catalog_restore_ci", "/tmp/ci-catalog-restore.dump")
            restored = compose("exec", "-T", "db", "psql", "-U", "food_catalog", "-d", "food_catalog_restore_ci",
                               "-Atc", "SELECT count(*) FROM food; SELECT count(*) FROM nutrition_reference; "
                               "SELECT count(*) FROM source_import; SELECT carbs_per_100g FROM nutrition_reference "
                               "WHERE source='Ciqual' AND external_code='9125';", capture=True)
            assert restored.stdout.splitlines() == ["3484", "3484", "1", "32.9"]
            print("COMPOSE_HOST_ACCESS_OK")
            print("BACKUP_FAILURE_PROTECTION_OK")
            print("ISOLATED_RESTORE_OK: foods=3484 references=3484 imports=1")
        finally:
            # Only this freshly generated CI project's containers/volumes.
            assert project.startswith("food-catalog-ci-")
            compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
