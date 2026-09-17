#!/bin/sh
# Healthy only if a completed, checked dump was recorded within 26 hours.
set -eu
catalog_marker="${CATALOG_BACKUP_DIR:-/backups}/.last-success"
catalog_max_age="${CATALOG_BACKUP_MAX_AGE_SECONDS-93600}"
[ -f "$catalog_marker" ] || exit 1
catalog_last="$(cat "$catalog_marker")"
case "$catalog_last:$catalog_max_age" in
  *[!0-9:]*|:*|*:) exit 1 ;;
esac
catalog_now="$(date +%s)"
catalog_age="$((catalog_now - catalog_last))"
[ "$catalog_age" -ge 0 ] && [ "$catalog_age" -le "$catalog_max_age" ]
