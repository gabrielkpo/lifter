#!/bin/bash
# Weekly restore test, run by launchd: a backup only counts if it restores. Restores the latest
# dump into a throwaway local database, checks that the core tables are there and not empty,
# then drops it. Needs the local Postgres server running.
set -uo pipefail
source "$(dirname "$0")/common.sh"
LIFTER_LOG="$LIFTER_LOG_DIR/restore-check.log"
BACKUP_DIR="${LIFTER_BACKUP_DIR:-$HOME/Library/Application Support/Lifter/backups}"
TARGET="lifter_restore_check"

latest=$(ls -t "$BACKUP_DIR"/lifter-*.dump 2>/dev/null | head -1)
if [[ -z "$latest" ]]; then
  log "restore-check: no backup found"
  notify_failure "Restore test: no backup found"
  exit 1
fi

log "restore-check: $(basename "$latest")"
"$PG_BIN/dropdb" --if-exists "$TARGET" 2>>"$LIFTER_LOG"
ok=1
if "$PG_BIN/createdb" "$TARGET" 2>>"$LIFTER_LOG" \
  && "$PG_BIN/pg_restore" --no-owner --no-privileges --exit-on-error --dbname="$TARGET" \
    "$latest" 2>>"$LIFTER_LOG"; then
  counts=$("$PG_BIN/psql" -d "$TARGET" -Atc \
    "select (select count(*) from raw_garmin_payload), (select count(*) from planned_session),
            (select count(*) from exercise), (select count(*) from analytics.daily_metrics)")
  log "restore-check: rows raw|sessions|exercises|metrics = $counts"
  IFS='|' read -r raw sessions exercises metrics <<<"$counts"
  [[ "$raw" -gt 0 && "$sessions" -gt 0 && "$exercises" -gt 0 && "$metrics" -gt 0 ]] || ok=0
else
  ok=0
fi
"$PG_BIN/dropdb" --if-exists "$TARGET" 2>>"$LIFTER_LOG"
if [[ "$ok" -eq 1 ]]; then
  log "restore-check: passed"
else
  log "restore-check: FAILED"
  notify_failure "Restore test failed, see ~/Library/Logs/lifter/restore-check.log"
  exit 1
fi
