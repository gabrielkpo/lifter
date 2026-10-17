#!/bin/bash
# Installs (or removes, with --uninstall) the scheduled jobs on this Mac, for the current user:
#   com.lifter.sync           07:30 and 21:00  Garmin sync to the hosted database
#   com.lifter.backup         13:00            backup of the hosted database
#   com.lifter.restore-check  Sunday 13:30     restore test of the latest backup
# A job missed while the Mac sleeps runs when it wakes up. The scripts are copied out of the
# repository first, so checking out another branch never changes what runs.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
# The jobs' own settings (ops.env): the logs and backups go where the jobs will put them.
# shellcheck source=common.sh
source "$SRC/common.sh"
OPS_DIR="$HOME/.local/share/lifter/ops"
LOG_DIR="$LIFTER_LOG_DIR"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.lifter.sync com.lifter.backup com.lifter.restore-check)

for label in "${LABELS[@]}"; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$AGENTS/$label.plist"
done
if [[ "${1:-}" == "--uninstall" ]]; then
  echo "removed: ${LABELS[*]}"
  exit 0
fi

mkdir -p "$OPS_DIR" "$LOG_DIR" "$AGENTS"
install -m 755 "$SRC"/lifter-*.sh "$OPS_DIR"/
install -m 644 "$SRC"/common.sh "$OPS_DIR"/
for label in "${LABELS[@]}"; do
  sed -e "s#__OPS_DIR__#$OPS_DIR#g" -e "s#__LOG_DIR__#$LOG_DIR#g" \
    "$SRC/launchd/$label.plist" >"$AGENTS/$label.plist"
  plutil -lint "$AGENTS/$label.plist" >/dev/null
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
done
# The dumps hold the whole database, health included, unencrypted: never in Time Machine. A
# sticky exclusion is stored on the folder (it follows a move, not a deletion): every install
# sets it again (see docs/operations.md).
mkdir -p "$LIFTER_BACKUP_DIR"
chmod 700 "$LIFTER_BACKUP_DIR"
tmutil addexclusion "$LIFTER_BACKUP_DIR" || echo "warning: could not exclude $LIFTER_BACKUP_DIR from Time Machine" >&2
echo "installed: ${LABELS[*]}"
