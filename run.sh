#!/usr/bin/env bash
# StorageIQ — First-time setup & manual sync runner
# Usage:  bash run.sh

set -e
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

header() { echo -e "\n${CYAN}══ $1 ══${NC}"; }
ok()     { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()   { echo -e "${YELLOW}  ⚠ $1${NC}"; }
err()    { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

echo -e "${CYAN}"
cat << 'LOGO'
  ____  _                          ___ ___
 / ___|| |_ ___  _ __ __ _  __ _ |_ _/ _ \
 \___ \| __/ _ \| '__/ _` |/ _` | | | | | |
  ___) | || (_) | | | (_| | (_| | | | |_| |
 |____/ \__\___/|_|  \__,_|\__, ||___\__\_\
                            |___/
LOGO
echo -e "${NC}  Google Storage Intelligence — Setup & Sync\n"

# ── 1. Python check ────────────────────────────────────────────
header "1. Python"
if ! command -v python3 &>/dev/null; then
  err "Python 3 not found. Install from https://python.org"
fi
PY=$(python3 --version)
ok "$PY found"

# ── 2. Virtualenv ──────────────────────────────────────────────
header "2. Virtual environment"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ok "Created .venv"
else
  ok ".venv already exists"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
ok "Activated"

# ── 3. Dependencies ────────────────────────────────────────────
header "3. Dependencies"
pip install -q -r requirements.txt
ok "All packages installed"

# ── 4. .env check ─────────────────────────────────────────────
header "4. Configuration"
if [ ! -f ".env" ]; then
  cp .env.example .env
  warn ".env created from template. Edit it now before continuing."
  echo ""
  echo "  Things to fill in:"
  echo "    GITHUB_TOKEN=ghp_..."
  echo "    GITHUB_REPO=youruser/storageiq-data"
  echo "    ACCOUNT_0_CREDENTIALS=credentials_account0.json"
  echo ""
  echo "  Then re-run:  bash run.sh"
  exit 0
else
  ok ".env found"
fi

# ── 5. credentials check ───────────────────────────────────────
header "5. Google credentials"
MISSING=0
for i in 0 1 2 3 4; do
  CRED=$(grep "^ACCOUNT_${i}_CREDENTIALS" .env 2>/dev/null | cut -d= -f2 | tr -d ' "'"'" )
  [ -z "$CRED" ] && continue
  if [ ! -f "$CRED" ]; then
    warn "Missing: $CRED (account $i)"
    echo "    Download from Google Cloud Console → APIs & Services → Credentials"
    MISSING=$((MISSING+1))
  else
    ok "$CRED found"
  fi
done
[ "$MISSING" -gt 0 ] && warn "$MISSING credential file(s) missing — those accounts will be skipped"

# ── 6. Run sync ────────────────────────────────────────────────
header "6. Running sync"
echo ""
echo "  Options:"
echo "    1) Sync all accounts"
echo "    2) Sync one account (by index)"
echo "    3) Dry run (print JSON, no GitHub push)"
echo "    4) Exit"
echo ""
read -rp "  Choice [1-4]: " CHOICE

case "$CHOICE" in
  1)
    python3 scripts/sync.py
    ;;
  2)
    read -rp "  Account index (0, 1, 2...): " IDX
    python3 scripts/sync.py --account "$IDX"
    ;;
  3)
    python3 scripts/sync.py --dry-run
    ;;
  4)
    echo "  Bye!"; exit 0
    ;;
  *)
    warn "Invalid choice — running full sync"
    python3 scripts/sync.py
    ;;
esac

# ── 7. Done ────────────────────────────────────────────────────
header "Done"
REPO=$(grep "^GITHUB_REPO" .env | cut -d= -f2 | tr -d ' "'"'" )
echo ""
ok "Data pushed to github.com/$REPO"
echo ""
echo "  Open dashboard/index.html in your browser."
echo "  Set GITHUB_REPO in dashboard/index.html if you haven't already."
echo ""
echo "  To auto-sync every 6 hours: push this repo to GitHub and"
echo "  the .github/workflows/sync.yml workflow will run automatically."
echo ""
