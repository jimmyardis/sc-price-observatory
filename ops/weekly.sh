#!/usr/bin/env bash
# Weekly run (systemd user timer sc-price-weekly.timer, Tuesdays 03:00 local, catches up if WSL was down).
#   1. measured pipeline: collect Kroger prices -> draft snapshot (--draft until the config gates pass)
#   2. regional reconstruction: new BLS months / QCEW quarters -> draft regional snapshot
#   3. copy data/observatory.db off the WSL disk: the observations are the one thing that can't be regenerated
# Log: .tmp/logs/weekly_<date>.log. Nonzero exit if collection failed.
# Smoke test without touching this week's prices: PIPELINE_EXTRA_ARGS=--skip-collect
set -uo pipefail
cd "$(dirname "$0")/.."
PY=/home/wner/venv/bin/python
BACKUP_DIR=${OBSERVATORY_BACKUP_DIR:-/mnt/c/Users/Owner/sc-price-observatory-backups}
mkdir -p .tmp/logs
exec >> ".tmp/logs/weekly_$(date +%F).log" 2>&1

echo "== $(date -Is) run_pipeline"
$PY -m execution.run_pipeline --draft ${PIPELINE_EXTRA_ARGS:-}
pipeline=$?

echo "== $(date -Is) run_regional"
$PY -m execution.run_regional --draft
regional=$?

echo "== $(date -Is) backup"
mkdir -p "$BACKUP_DIR" && $PY - "$BACKUP_DIR" <<'PYEOF'
import sqlite3, sys, datetime, pathlib
dest = pathlib.Path(sys.argv[1]) / f"observatory_{datetime.date.today()}.db"
src = sqlite3.connect("data/observatory.db")
with sqlite3.connect(dest) as out:
    src.backup(out)
for old in sorted(pathlib.Path(sys.argv[1]).glob("observatory_*.db"))[:-12]:
    old.unlink()
print("backup:", dest)
PYEOF

echo "== $(date -Is) done: pipeline=$pipeline regional=$regional"
# 1 = QA halted (expected while weights/basket are drafts); 2 = collector blocked
[ "$pipeline" -eq 2 ] && exit 2
exit 0
