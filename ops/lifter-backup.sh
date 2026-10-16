#!/bin/bash
# Daily backup of the hosted database, run by launchd: a full logical dump (schema and data,
# pg_dump custom format, compressed) taken with the read-only lifter_backup role, kept 30 days
# in a folder only this user can read, on a FileVault-encrypted disk. Neon's own history only
# goes back 6 hours on the free plan; this is the copy we control.
set -uo pipefail
source "$(dirname "$0")/common.sh"
LIFTER_LOG="$LIFTER_LOG_DIR/backup.log"
BACKUP_DIR="${LIFTER_BACKUP_DIR:-$HOME/Library/Application Support/Lifter/backups}"
KEEP_DAYS="${LIFTER_BACKUP_KEEP_DAYS:-30}"

load_env backup.env
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
file="$BACKUP_DIR/lifter-$(date '+%Y%m%d-%H%M%S').dump"

log "backup: start"
if "$PG_BIN/pg_dump" --format=custom --no-owner --no-privileges --file="$file.partial" \
  "$DATABASE_URL" 2>>"$LIFTER_LOG" && "$PG_BIN/pg_restore" --list "$file.partial" >/dev/null; then
  mv "$file.partial" "$file"
  log "backup: done $(basename "$file") ($(du -h "$file" | cut -f1))"
else
  rm -f "$file.partial"
  log "backup: failed"
  notify_failure "Database backup failed, see ~/Library/Logs/lifter/backup.log"
  exit 1
fi
find "$BACKUP_DIR" -name 'lifter-*.dump' -mtime +"$KEEP_DAYS" -delete
