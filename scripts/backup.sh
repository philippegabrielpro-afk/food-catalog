#!/bin/sh
# PostgreSQL custom archives, published atomically after a readability check.
# No deletion of completed backups. A --once mode supports controlled tests.
set -eu
umask 077

case "${1:-}" in
  "") catalog_once=false ;;
  --once) catalog_once=true ;;
  *) echo "Usage: backup.sh [--once]" >&2; exit 64 ;;
esac
[ "$#" -le 1 ] || { echo "Unexpected arguments" >&2; exit 64; }

catalog_dir="${CATALOG_BACKUP_DIR:-/backups}"
catalog_interval="${CATALOG_BACKUP_INTERVAL_SECONDS-86400}"
case "$catalog_interval" in
  ''|*[!0-9]*) echo "Invalid backup interval" >&2; exit 64 ;;
esac
[ "$catalog_interval" -ge 60 ] || { echo "Backup interval must be at least 60 seconds" >&2; exit 64; }
[ -d "$catalog_dir" ] && [ -w "$catalog_dir" ] || {
  echo "Backup directory must already exist and be writable" >&2
  exit 73
}

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
export PGPASSWORD="$POSTGRES_PASSWORD"

catalog_partial=""
catalog_marker_partial=""
catalog_cleanup() {
  # Only freshly allocated temporary files are removed, never a completed dump.
  if [ -n "$catalog_partial" ]; then rm -f -- "$catalog_partial"; fi
  if [ -n "$catalog_marker_partial" ]; then rm -f -- "$catalog_marker_partial"; fi
}
trap catalog_cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

while :; do
  catalog_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  catalog_partial="$(mktemp "$catalog_dir/.food-catalog-${catalog_stamp}.XXXXXX")"
  catalog_final="$catalog_dir/$(basename "$catalog_partial" | cut -c 2-).dump"
  [ ! -e "$catalog_final" ] || { echo "Backup target already exists" >&2; exit 73; }

  pg_dump --host="${POSTGRES_HOST:-db}" --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges \
    --file="$catalog_partial"
  [ -s "$catalog_partial" ] || { echo "Empty dump: not published" >&2; exit 74; }
  pg_restore --list "$catalog_partial" >/dev/null
  chmod 600 "$catalog_partial"
  mv -- "$catalog_partial" "$catalog_final"
  catalog_partial=""

  catalog_marker_partial="$(mktemp "$catalog_dir/.last-success.XXXXXX")"
  date +%s > "$catalog_marker_partial"
  mv -- "$catalog_marker_partial" "$catalog_dir/.last-success"
  catalog_marker_partial=""
  printf 'BACKUP_OK=%s\n' "$(basename "$catalog_final")"

  if [ "$catalog_once" = true ]; then break; fi
  sleep "$catalog_interval"
done
