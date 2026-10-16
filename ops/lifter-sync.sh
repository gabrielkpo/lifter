#!/bin/bash
# Scheduled Garmin sync, run by launchd (ops/launchd): reads the local MCP server
# (127.0.0.1, never exposed) and writes to the hosted database as lifter_sync, which may not
# change the schema (`--no-migrate` only checks it). The last 3 days are fetched again, so a
# missed run or a late watch upload is caught up by the next one.
set -uo pipefail
source "$(dirname "$0")/common.sh"
LIFTER_LOG="$LIFTER_LOG_DIR/sync.log"

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
  notify_failure "Garmin sync failed (exit $code), see $LIFTER_LOG"
  exit "$code"
fi
