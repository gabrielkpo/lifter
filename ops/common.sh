# shellcheck shell=bash
# Shared by the scheduled jobs: settings, log file, failure notification. Sourced, not run.
# Files outside the repository (chmod 600), in ~/.config/lifter:
#   ops.env     optional, settings shared by every job (paths, retention), never a secret
#   sync.env    DATABASE_URL (lifter_sync role), GARMIN_MCP_URL, GARMIN_MCP_TOKEN
#   backup.env  DATABASE_URL (lifter_backup role)
# Settings are documented in docs/operations.md.

# Logs hold full tracebacks and dumps hold the whole database: nothing the jobs create is
# readable by another user.
umask 077

LIFTER_CONFIG_DIR="${LIFTER_CONFIG_DIR:-$HOME/.config/lifter}"
if [[ -r "$LIFTER_CONFIG_DIR/ops.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$LIFTER_CONFIG_DIR/ops.env"
  set +a
fi
LIFTER_LOG_DIR="${LIFTER_LOG_DIR:-$HOME/Library/Logs/lifter}"
# The `lifter` command installed apart from any working copy (uv tool install, see
# docs/operations.md), so a checkout on another branch never changes what runs at night.
LIFTER_BIN="${LIFTER_BIN:-$HOME/.local/bin/lifter}"
# Postgres 18 client tools from Homebrew, Apple silicon or Intel prefix.
if [[ -z "${PG_BIN:-}" ]]; then
  for prefix in /opt/homebrew /usr/local; do
    if [[ -x "$prefix/opt/postgresql@18/bin/pg_dump" ]]; then
      PG_BIN="$prefix/opt/postgresql@18/bin"
      break
    fi
  done
  PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@18/bin}"
fi
LIFTER_BACKUP_DIR="${LIFTER_BACKUP_DIR:-$HOME/Library/Application Support/Lifter/backups}"
LIFTER_BACKUP_KEEP_DAYS="${LIFTER_BACKUP_KEEP_DAYS:-30}"

mkdir -p "$LIFTER_LOG_DIR"
chmod 700 "$LIFTER_LOG_DIR"

# A scheduled job often starts in a dark wake: on battery, macOS puts the Mac back to sleep within
# seconds, the connection to the hosted database dies there, and the job fails a quarter of an
# hour later. Each job runs itself again under caffeinate, which holds the Mac
# awake (idle sleep, and system sleep on power) until the job ends.
stay_awake() {
  if [[ -z "${LIFTER_AWAKE:-}" ]]; then
    export LIFTER_AWAKE=1
    exec /usr/bin/caffeinate -i -s /bin/bash "$0" "$@"
  fi
}

# Someone used the keyboard or the trackpad in the last 10 minutes: the Mac is fully awake, not in
# a dark wake that macOS ends within seconds on battery, whatever caffeinate asks.
user_active() {
  local idle
  idle=$(ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print int($NF / 1000000000); exit}')
  [[ -n "$idle" && "$idle" -lt 600 ]]
}

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LIFTER_LOG"; }

# A macOS notification: the scheduled jobs run unattended, a failure must be seen.
notify_failure() {
  osascript -e "display notification \"$1\" with title \"Lifter\" sound name \"Basso\"" || true
}

# A job that hangs keeps its lock and caffeinate (the Mac never sleeps again) until someone
# notices. Each job command runs under a time limit: TERM when it is reached, KILL 30 s later.
# Returns the command's exit code, 124 when the limit stopped it. (macOS has no timeout command.)
run_with_timeout() {
  local limit=$1
  shift
  "$@" &
  local pid=$!
  # The watchdog's sleeps run in the background behind `wait`, which a signal interrupts at
  # once: stopped when the command ends, it leaves no sleep behind and the job ends with it.
  # Its output goes nowhere, so a sleep left behind never holds the job's log or pipe open; the
  # mark that the limit was reached is written before the command is stopped.
  (
    trap 'kill "$nap" 2>/dev/null; exit 0' TERM
    sleep "$limit" &
    nap=$!
    wait "$nap"
    : >"$LIFTER_LOG_DIR/.timed-out-$pid"
    if ! kill -TERM "$pid" 2>/dev/null; then
      rm -f "$LIFTER_LOG_DIR/.timed-out-$pid"
      exit 0
    fi
    sleep 30 &
    nap=$!
    wait "$nap"
    kill -KILL "$pid" 2>/dev/null
  ) </dev/null >/dev/null 2>&1 &
  local watchdog=$!
  # The job itself stopped from outside (launchd, a kill) takes its command with it, instead of
  # leaving it running without its lock.
  trap 'kill -TERM "$pid" "$watchdog" 2>/dev/null; exit 143' TERM INT HUP
  wait "$pid"
  local code=$?
  trap - TERM INT HUP
  kill "$watchdog" 2>/dev/null
  wait "$watchdog" 2>/dev/null
  if [[ -e "$LIFTER_LOG_DIR/.timed-out-$pid" ]]; then
    rm -f "$LIFTER_LOG_DIR/.timed-out-$pid"
    return 124
  fi
  return "$code"
}

# The libpq client tools (pg_dump) take TCP keepalives and a connect timeout from the URL only:
# a dead network path then fails within about a minute instead of hanging (see lifter.db).
with_keepalives() {
  local url=$1 sep="?"
  [[ "$url" == *"?"* ]] && sep="&"
  printf '%s%sconnect_timeout=10&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3' \
    "$url" "$sep"
}

load_env() {
  local file="$LIFTER_CONFIG_DIR/$1"
  if [[ ! -r "$file" ]]; then
    log "missing $file"
    notify_failure "Missing $file"
    exit 2
  fi
  # Exported for the command, never printed.
  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
}
