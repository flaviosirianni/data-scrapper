#!/usr/bin/env bash
# deploy.sh — Weekly UFC stats update
#
# 1. Scrape new completed fights (incremental, since 2016)
# 2. Scrape upcoming events fight cards
# 3. Rebuild SQLite
# 4. Copy ufc.db to OCI server as ufc_stats.db
# 5. Reload bot on server
#
# Usage:
#   ./deploy.sh                  # Normal weekly run
#   ./deploy.sh --skip-scrape    # Only convert + upload (no Playwright)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SSH_KEY="/Users/flaviosirianniv2/Documents/ssh-key-2026-03-20 (1).key"
SERVER="ubuntu@163.176.189.11"
REMOTE_PATH="/home/ubuntu/ufc-orchestrator-data/ufc_stats.db"
LOCAL_DB="data/ufc/ufc.db"
VENV="$SCRIPT_DIR/.venv/bin/python"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

SKIP_SCRAPE=false
for arg in "$@"; do
  [[ "$arg" == "--skip-scrape" ]] && SKIP_SCRAPE=true
done

if [[ "$SKIP_SCRAPE" == "false" ]]; then
  log "Scraping completed fights (incremental, since 2016)..."
  "$VENV" run_ufc.py scrape --since-year 2016

  log "Scraping upcoming events fight cards..."
  "$VENV" run_ufc.py scrape-upcoming
fi

log "Converting to SQLite..."
"$VENV" convert_to_sqlite.py

log "Uploading to server..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
  "$LOCAL_DB" "${SERVER}:${REMOTE_PATH}"

log "Done. ufc_stats.db deployed to server."
log "Bot will pick up new data on next request (reads SQLite live)."
