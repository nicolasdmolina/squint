#!/bin/sh
# Install (or reinstall) Squint's overnight classifier run as a per-user launchd agent (23:00).
# Usage: ops/install-nightly.sh          install (runs tonight at 23:00; nothing starts now)
#        ops/install-nightly.sh remove   uninstall (data, runs and reports are left alone)
# A run in progress is stopped by bootout (SIGTERM; stages checkpoint) on reinstall or remove.
set -eu

LABEL=com.nickymolina.squint-nightly
PROJECT=$(cd "$(dirname "$0")/.." && pwd)
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
	launchctl bootout "$DOMAIN/$LABEL"
fi

if [ "${1:-}" = remove ]; then
	rm -f "$DEST"
	echo "removed $LABEL"
	exit 0
fi

if [ ! -x "$PROJECT/classifier/.venv/bin/python" ]; then
	echo "missing $PROJECT/classifier/.venv — run: cd classifier && uv sync" >&2
	exit 1
fi

mkdir -p "$HOME/Library/Logs/squint" "$HOME/Library/LaunchAgents"
sed -e "s|__PROJECT__|$PROJECT|g" -e "s|__HOME__|$HOME|g" "$PROJECT/ops/$LABEL.plist" > "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $LABEL → nightly 23:00-09:30 (log: ~/Library/Logs/squint/nightly.log, reports: classifier/reports/)"
