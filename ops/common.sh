# Shared by the scheduled jobs: settings, log file, failure notification. Sourced, not run.
# Each job reads its own environment file, outside the repository (chmod 600):
#   ~/.config/lifter/sync.env    DATABASE_URL (lifter_sync role), GARMIN_MCP_URL, GARMIN_MCP_TOKEN
#   ~/.config/lifter/backup.env  DATABASE_URL (lifter_backup role)

LIFTER_CONFIG_DIR="${LIFTER_CONFIG_DIR:-$HOME/.config/lifter}"
LIFTER_LOG_DIR="${LIFTER_LOG_DIR:-$HOME/Library/Logs/lifter}"
# The `lifter` command installed apart from any working copy (uv tool install, see
# docs/operations.md), so a checkout on another branch never changes what runs at night.
LIFTER_BIN="${LIFTER_BIN:-$HOME/.local/bin/lifter}"
PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@18/bin}"

mkdir -p "$LIFTER_LOG_DIR"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LIFTER_LOG"; }

# A macOS notification: the scheduled jobs run unattended, a failure must be seen.
notify_failure() {
  osascript -e "display notification \"$1\" with title \"Lifter\" sound name \"Basso\"" || true
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
