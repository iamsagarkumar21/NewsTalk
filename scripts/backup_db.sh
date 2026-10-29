#!/usr/bin/env bash
# Consistent online backup of the SQLite database, keeping the newest 14 copies.
#   scripts/backup_db.sh [db_path] [backup_dir]
# Cron (nightly 03:00):  0 3 * * * /path/to/NewsTalk/scripts/backup_db.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${1:-$ROOT/newtalk.db}"
DEST="${2:-$ROOT/backups}"
KEEP=14

[ -f "$DB" ] || { echo "database not found: $DB" >&2; exit 1; }
mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/newtalk-$STAMP.db"

# the .backup API is safe while the server is writing; plain `cp` is not
python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
chmod 600 "$OUT"
# prune: keep the newest $KEEP
ls -1t "$DEST"/newtalk-*.db 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f -- "$old"; done
echo "backup written: $OUT"
