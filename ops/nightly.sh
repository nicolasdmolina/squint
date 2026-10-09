#!/bin/sh
# Squint's overnight classifier run (launched by launchd at 00:30; see ops/install-nightly.sh).
# Keeps the Mac awake (caffeinate -i) only while classifier/nightly.py runs, forwards
# SIGTERM/SIGINT/SIGHUP to it so every stage checkpoints, and logs to ~/Library/Logs/squint/.
# The window, guards and stages are classifier/nightly.py's; its docstring lists the
# SQUINT_NIGHTLY_* settings, which can be exported here or set in the plist.
# Usage: ops/nightly.sh [--stub --state-dir DIR ...]   (arguments go to nightly.py)
set -eu

PROJECT=$(cd "$(dirname "$0")/.." && pwd)
LOG_DIR="${SQUINT_NIGHTLY_LOG_DIR:-$HOME/Library/Logs/squint}"
PY="$PROJECT/classifier/.venv/bin/python"
: "${SQUINT_NIGHTLY_START:=00:30}"
: "${SQUINT_NIGHTLY_END:=07:30}"
export SQUINT_NIGHTLY_START SQUINT_NIGHTLY_END PYTHONUNBUFFERED=1

mkdir -p "$LOG_DIR"
exec >>"$LOG_DIR/nightly.log" 2>&1

if [ ! -x "$PY" ]; then
	echo "$(date '+%Y-%m-%d %H:%M:%S') nightly.sh: missing $PROJECT/classifier/.venv — run: cd classifier && uv sync"
	exit 1
fi

cd "$PROJECT"
"$PY" -u classifier/nightly.py "$@" &
pid=$!
trap 'kill -TERM "$pid" 2>/dev/null || true' TERM INT HUP
/usr/bin/caffeinate -i -w "$pid" &

rc=0
wait "$pid" || rc=$?
# a trapped signal interrupts wait before nightly.py has finished stopping its children
while kill -0 "$pid" 2>/dev/null; do
	rc=0
	wait "$pid" || rc=$?
done
echo "$(date '+%Y-%m-%d %H:%M:%S') nightly.sh: nightly.py exited $rc"
exit "$rc"
