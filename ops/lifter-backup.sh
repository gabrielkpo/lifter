#!/bin/bash
# Daily backup of the hosted database, run by launchd: a full logical dump (schema and data,
# pg_dump custom format, compressed) taken with the read-only lifter_backup role, kept 30 days
# in a folder only this user can read, on a FileVault-encrypted disk. The dumps themselves are
# not encrypted (see docs/operations.md, Backups). Neon's own history only goes back 6 hours on
# the free plan; this is the copy we control.
set -uo pipefail
source "$(dirname "$0")/common.sh"
LIFTER_LOG="$LIFTER_LOG_DIR/backup.log"
BACKUP_DIR="$LIFTER_BACKUP_DIR"

load_env backup.env
# The password goes to pg_dump through its environment, not its arguments, which any process
# on the Mac can read (ps). postgresql://user:password@host/db?options, percent-decoded.
if [[ "$DATABASE_URL" =~ ^(postgres(ql)?://)([^:@/]+):([^@]+)@(.+)$ ]]; then
  password="${BASH_REMATCH[4]}"
  PGPASSWORD="$(printf '%b' "${password//%/\\x}")"
  export PGPASSWORD
  DATABASE_URL="${BASH_REMATCH[1]}${BASH_REMATCH[3]}@${BASH_REMATCH[5]}"
fi
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
# A run killed in the middle of pg_dump (sleep, shutdown) leaves a partial file: never kept.
find "$BACKUP_DIR" -name 'lifter-*.dump.partial' -mmin +60 -delete
file="$BACKUP_DIR/lifter-$(date '+%Y%m%d-%H%M%S').dump"

log "backup: start"
# --enable-row-security: conversation_message has row-level policies (009); without it pg_dump
# refuses the table for a role that does not own it. lifter_backup reads every row through
# lifter_private (roles.sql), which the read policy covers, so the dump is complete.
if "$PG_BIN/pg_dump" --format=custom --no-owner --no-privileges --enable-row-security \
  --file="$file.partial" \
  "$DATABASE_URL" 2>>"$LIFTER_LOG" && "$PG_BIN/pg_restore" --list "$file.partial" >/dev/null; then
  mv "$file.partial" "$file"
  log "backup: done $(basename "$file") ($(du -h "$file" | cut -f1))"
else
  rm -f "$file.partial"
  log "backup: failed"
  notify_failure "Database backup failed, see $LIFTER_LOG"
  exit 1
fi
find "$BACKUP_DIR" -name 'lifter-*.dump' -mtime +"$LIFTER_BACKUP_KEEP_DAYS" -delete
