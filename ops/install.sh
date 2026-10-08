#!/bin/sh
# Install (or reinstall) Squint as a per-user launchd service on 127.0.0.1:8017.
# Usage: ops/install.sh          install + start
#        ops/install.sh remove   stop + uninstall (the server and its files are left alone)
set -eu

LABEL=com.nickymolina.squint
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

if [ ! -x "$PROJECT/server/.venv/bin/squint-server" ]; then
	echo "missing $PROJECT/server/.venv — run: cd server && uv sync" >&2
	exit 1
fi
if [ ! -f "$PROJECT/web/dist/index.html" ]; then
	echo "warning: web/dist is not built; the API will run without the UI (cd web && npm run build)" >&2
fi

mkdir -p "$HOME/Library/Logs/squint" "$HOME/Library/LaunchAgents"
sed -e "s|__PROJECT__|$PROJECT|g" -e "s|__HOME__|$HOME|g" "$PROJECT/ops/$LABEL.plist" > "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $LABEL → http://127.0.0.1:8017 (logs: ~/Library/Logs/squint/)"
