import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "scripts" / "backup.sh"
HEALTH = ROOT / "scripts" / "backup-healthcheck.sh"


@pytest.fixture
def context(tmp_path):
    if os.name != "posix" or not shutil.which("sh"):
        pytest.skip("Shell backup tests run on Linux in CI; portable config tests still run on Windows")
    tools = tmp_path / "bin"
    tools.mkdir()
    backups = tmp_path / "backups"
    backups.mkdir(mode=0o700)
    dump = tools / "pg_dump"
    dump.write_text('''#!/bin/sh
set -eu
test "$PGPASSWORD" = "isolated-test-password"
for value in "$@"; do
  case "$value" in --file=*) output="${value#--file=}" ;; esac
done
if [ "${FAKE_DUMP_FAIL:-0}" = 1 ]; then
  printf 'partial' > "$output"
  echo 'Simulated dump failure' >&2
  exit 7
fi
if [ "${FAKE_EMPTY_DUMP:-0}" = 1 ]; then exit 0; fi
printf 'simulated-custom-archive' > "$output"
''', encoding="utf-8")
    restore = tools / "pg_restore"
    restore.write_text('''#!/bin/sh
set -eu
if [ "${FAKE_RESTORE_FAIL:-0}" = 1 ]; then exit 8; fi
test "$1" = --list
test -s "$2"
printf 'simulated-table-of-contents'
''', encoding="utf-8")
    for item in (dump, restore):
        item.chmod(0o755)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
           "CATALOG_BACKUP_DIR": str(backups), "POSTGRES_PASSWORD": "isolated-test-password",
           "POSTGRES_USER": "food_catalog", "POSTGRES_DB": "food_catalog"}
    return backups, env


def run(script, env, *args):
    return subprocess.run(["sh", str(script), *args], env=env, capture_output=True, text=True, timeout=10)


def test_backup_publishes_checked_unique_private_files_without_purge(context):
    backups, env = context
    old = backups / "food-catalog-20000101T000000Z.dump"
    old.write_bytes(b"previous-backup")
    os.utime(old, (1, 1))
    for _ in range(2):
        result = run(BACKUP, env, "--once")
        assert result.returncode == 0, result.stderr
        assert "BACKUP_OK=" in result.stdout
        assert env["POSTGRES_PASSWORD"] not in result.stdout + result.stderr
    dumps = [item for item in backups.glob("*.dump") if item != old]
    assert len(dumps) == 2
    assert all(item.read_bytes() == b"simulated-custom-archive" for item in dumps)
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in dumps)
    assert old.read_bytes() == b"previous-backup"  # No age-based purge.
    assert not list(backups.glob(".food-catalog-*"))
    assert stat.S_IMODE((backups / ".last-success").stat().st_mode) == 0o600
    assert run(HEALTH, env).returncode == 0


@pytest.mark.parametrize("failure,code", [("FAKE_DUMP_FAIL", 7), ("FAKE_RESTORE_FAIL", 8), ("FAKE_EMPTY_DUMP", 74)])
def test_failed_or_unreadable_dump_is_not_published_and_marker_is_not_changed(context, failure, code):
    backups, env = context
    marker = backups / ".last-success"
    marker.write_text("123456", encoding="ascii")
    sentinel = backups / "food-catalog-existing.dump"
    sentinel.write_bytes(b"good-existing-archive")
    result = run(BACKUP, {**env, failure: "1"}, "--once")
    assert result.returncode == code, result.stderr
    assert marker.read_text() == "123456"
    assert list(backups.glob("*.dump")) == [sentinel]
    assert sentinel.read_bytes() == b"good-existing-archive"
    assert not list(backups.glob(".food-catalog-*"))
    assert "BACKUP_OK=" not in result.stdout
    assert env["POSTGRES_PASSWORD"] not in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["", "abc", "0", "1", "-5"])
def test_invalid_interval_is_rejected_before_dump(context, value):
    backups, env = context
    assert run(BACKUP, {**env, "CATALOG_BACKUP_INTERVAL_SECONDS": value}, "--once").returncode == 64
    assert list(backups.iterdir()) == []


def test_missing_directory_and_secret_are_rejected(context):
    backups, env = context
    assert run(BACKUP, {**env, "CATALOG_BACKUP_DIR": str(backups / "missing")}, "--once").returncode == 73
    assert run(BACKUP, {**env, "POSTGRES_PASSWORD": ""}, "--once").returncode != 0
    assert list(backups.iterdir()) == []


@pytest.mark.parametrize("marker", [None, "", "not-a-time", "1", "9999999999"])
def test_health_rejects_missing_invalid_old_or_future_success(context, marker):
    backups, env = context
    if marker is not None:
        (backups / ".last-success").write_text(marker, encoding="ascii")
    assert run(HEALTH, env).returncode != 0


def test_health_accepts_recent_success_and_rejects_over_26_hours(context):
    backups, env = context
    marker = backups / ".last-success"
    marker.write_text(str(int(time.time()) - 90000), encoding="ascii")
    assert run(HEALTH, env).returncode == 0
    marker.write_text(str(int(time.time()) - 93610), encoding="ascii")
    assert run(HEALTH, env).returncode != 0


def test_loop_sleeps_daily_after_success_and_no_secret_in_logs(context):
    backups, env = context
    sleep = Path(env["PATH"].split(os.pathsep)[0]) / "sleep"
    sleep.write_text('#!/bin/sh\ntest "$1" = 86400\nexit 9\n', encoding="ascii")
    sleep.chmod(0o755)
    result = run(BACKUP, env)
    assert result.returncode == 9
    assert len(list(backups.glob("*.dump"))) == 1
    assert "BACKUP_OK=" in result.stdout
    assert env["POSTGRES_PASSWORD"] not in result.stdout + result.stderr


def test_bad_arguments_are_rejected(context):
    backups, env = context
    assert run(BACKUP, env, "unexpected").returncode == 64
    assert run(BACKUP, env, "--once", "extra").returncode == 64
    assert list(backups.iterdir()) == []
