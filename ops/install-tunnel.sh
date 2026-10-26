#!/bin/sh
# Publish Squint at https://squint.nickymolina.com through a Cloudflare Tunnel (per-user launchd).
# Refuses unless the local server requires a password, so the site is never public and open.
# Usage: ops/install-tunnel.sh          install + start
#        ops/install-tunnel.sh remove   stop + uninstall (the tunnel and DNS record stay in Cloudflare)
set -eu

LABEL=com.nickymolina.squint-tunnel
PROJECT=$(cd "$(dirname "$0")/.." && pwd)
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
	launchctl bootout "$DOMAIN/$LABEL"
fi

if [ "${1:-}" = remove ]; then
	rm -f "$DEST"
	echo "removed $LABEL; squint.nickymolina.com is offline"
	exit 0
fi

if ! curl -fsS http://127.0.0.1:8017/api/session | grep -q '"password_required":true'; then
	echo "refusing: the Squint server is not running with a password (see server/README.md)" >&2
	exit 1
fi

mkdir -p "$HOME/Library/Logs/squint" "$HOME/Library/LaunchAgents"
sed -e "s|__HOME__|$HOME|g" "$PROJECT/ops/cloudflared-squint.yml" > "$HOME/.cloudflared/squint.yml"
sed -e "s|__HOME__|$HOME|g" "$PROJECT/ops/$LABEL.plist" > "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "$DOMAIN" "$DEST"
echo "installed $LABEL → https://squint.nickymolina.com (logs: ~/Library/Logs/squint/tunnel*.log)"
