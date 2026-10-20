#!/bin/bash
# Scheduled Garmin sync, run by launchd (ops/launchd): reads the local MCP server
# (127.0.0.1, never exposed) and writes to the hosted database as lifter_sync, which may not
# change the schema (`--no-migrate` only checks it). The last 3 days are fetched again, so a
# missed run or a late watch upload is caught up by the next one.
# With --catch-up (com.lifter.sync-catchup, hourly), it syncs only when the Mac is in use and the
# last successful sync is more than 12 hours old: a scheduled run that fell in a dark wake on
# battery, where macOS puts the Mac back to sleep within seconds, is made up at the next use.
set -uo pipefail
source "$(dirname "$0")/common.sh"
stay_awake "$@"
LIFTER_LOG="$LIFTER_LOG_DIR/sync.log"

# The last "sync: done" of the log is less than $1 hours old.
synced_within() {
  local last
  last=$(grep ' sync: done$' "$LIFTER_LOG" 2>/dev/null | tail -1 | cut -c1-19)
  [[ -n "$last" ]] || return 1
  (($(date +%s) - $(date -j -f '%Y-%m-%d %H:%M:%S' "$last" +%s) < $1 * 3600))
}

if [[ "${1:-}" == "--catch-up" ]] && { ! user_active || synced_within 12; }; then
  exit 0
fi
# One sync at a time: the scheduled run and the catch-up can start together at 21:00.
LOCK="$LIFTER_LOG_DIR/sync.lock"
if ! /usr/bin/shlock -f "$LOCK" -p $$; then
  log "sync: another sync is running, this one is skipped"
  exit 0
fi
trap '/bin/rm -f "$LOCK"' EXIT

load_env sync.env
log "sync: start"
if "$LIFTER_BIN" sync --days "${LIFTER_SYNC_DAYS:-3}" --no-migrate >>"$LIFTER_LOG" 2>&1; then
  log "sync: done"
  # The agents' audit keeps its full context 90 days (ADR 0002): purge what is older.
  if ! "$LIFTER_BIN" audit-purge >>"$LIFTER_LOG" 2>&1; then
    log "audit-purge: failed"
    notify_failure "Audit purge failed, see $LIFTER_LOG"
    exit 1
  fi
else
  code=$?
  log "sync: failed (exit $code)"
  # Unattended (the Mac asleep again in a dark wake), nobody would see it: the hourly catch-up
  # syncs at the next use, and the app's banner warns past 36 hours.
  if user_active; then
    notify_failure "Garmin sync failed (exit $code), see $LIFTER_LOG"
  else
    log "sync: the Mac was not in use, the catch-up retries at the next use"
  fi
  exit "$code"
fi
