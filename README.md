# StorageIQ — Google Account Storage Intelligence

> Multi-account Google storage dashboard backed by GitHub as a version-controlled data store.
> Every sync run commits a snapshot — full audit trail, no database needed.

```
storageiq/
├── dashboard/
│   └── index.html          ← open this in any browser (reads live from GitHub)
├── scripts/
│   └── sync.py             ← fetches Google APIs → pushes JSON to GitHub
├── data/
│   └── accounts.json       ← live data file (committed by sync.py)
├── .github/
│   └── workflows/
│       └── sync.yml        ← GitHub Action: auto-sync every 6 hours
├── .env.example            ← copy → .env and fill in
├── requirements.txt
└── run.sh                  ← interactive setup wizard
```

---

## Quick Start (5 minutes)

### 1 — Clone & configure

```bash
git clone https://github.com/YOUR_USER/storageiq-data   # create this repo first
cd storageiq-data
cp .env.example .env
```

Edit `.env`:
```
GITHUB_TOKEN=ghp_...          # Personal Access Token (repo scope)
GITHUB_REPO=youruser/storageiq-data
ACCOUNT_0_CREDENTIALS=credentials_account0.json
ACCOUNT_0_TOKEN=token_account0.json
ACCOUNT_0_LABEL=Personal

ACCOUNT_1_CREDENTIALS=credentials_account1.json
ACCOUNT_1_TOKEN=token_account1.json
ACCOUNT_1_LABEL=Work
```

### 2 — Get Google credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create/select a project
3. **Enable APIs**: Google Drive API · Gmail API · Photos Library API
4. **Credentials** → Create OAuth 2.0 Client ID → Desktop app
5. Download JSON → rename to `credentials_account0.json`
6. **OAuth consent screen** → add your email as a Test User

Repeat steps 4–6 for each additional account.

### 3 — Run the sync

```bash
bash run.sh
```

On first run a browser tab opens for each account — sign in, and the token is saved automatically. After that, syncs run silently.

This pushes `data/accounts.json` to your GitHub repo.

### 4 — Open the dashboard

Open `dashboard/index.html` in your browser.
Enter your `username/repo` in the config banner and click **Connect →**.

The dashboard reads the raw JSON from GitHub on every load and auto-refreshes every 10 minutes.

---

## How the version control works

Every sync run commits a new version of `data/accounts.json`:

```
commit a3f91bc  chore: sync storage data 2025-06-10 09:00 UTC
commit b7e42d1  chore: sync storage data 2025-06-09 15:00 UTC
commit c1d88fa  chore: sync storage data 2025-06-09 09:00 UTC
```

The dashboard shows a **commit history strip** at the top. Click any commit to load that historical snapshot — see exactly how your storage looked at any point in the past.

---

## Auto-sync with GitHub Actions

Push this repo to GitHub. The included workflow auto-runs every 6 hours:

```yaml
# .github/workflows/sync.yml
on:
  schedule:
    - cron: '0 */6 * * *'
  workflow_dispatch:  # manual trigger from GitHub UI
```

**Add these secrets** in your repo Settings → Secrets:

| Secret | Value |
|--------|-------|
| `STORAGEIQ_GITHUB_TOKEN` | Your PAT with repo write access |
| `TOKEN_ACCOUNT_0_B64` | `base64 -i token_account0.json` |
| `TOKEN_ACCOUNT_1_B64` | `base64 -i token_account1.json` |
| `ACCOUNT_0_LABEL` | e.g. `Personal` |
| `ACCOUNT_1_LABEL` | e.g. `Work` |

The tokens are base64-encoded because GitHub Secrets can't store raw JSON safely.

```bash
# Encode your token files
base64 -i token_account0.json | pbcopy   # macOS — pastes to clipboard
base64 -i token_account0.json            # Linux
```

---

## Manual sync commands

```bash
# Sync all accounts
python scripts/sync.py

# Sync only account 0
python scripts/sync.py --account 0

# Dry run — print JSON output, don't push to GitHub
python scripts/sync.py --dry-run
```

---

## Dashboard features

- **Account Slicer** — switch between individual accounts or Combined view
- **Storage Galaxy** — animated donut showing Gmail / Drive / Photos split
- **KPI Strip** — storage used, spam, recoverable space, health score, days until full
- **Service Cards** — real stats from Gmail labels, Drive file list, Photos item count
- **AI Recommendations** — generated from live data (spam count, duplicates, days left)
- **GitHub Commit Strip** — click any past commit to load that historical snapshot
- **Version History modal** — full list of all past syncs with load buttons
- **Auto-refresh** — dashboard re-fetches from GitHub every 10 minutes

---

## Data schema (data/accounts.json)

```json
{
  "schema_version": 2,
  "generated_at": "2025-06-10T09:00:00Z",
  "accounts": [
    {
      "id": "acc0",
      "email": "you@gmail.com",
      "name": "Your Name",
      "used_gb": 11.4,
      "total_gb": 15,
      "pct_used": 76,
      "health_pct": 62,
      "health_grade": "C+",
      "spam_gb": 2.1,
      "recover_gb": 4.8,
      "days_left": 94,
      "junk_mb": 847,
      "dup_gb": 1.3,
      "services": {
        "gmail":  { "used_gb": 6.2, "spam_count": 12401, "inbox_count": 4231 },
        "drive":  { "used_gb": 3.1, "file_count": 2847, "duplicate_count": 94 },
        "photos": { "used_gb": 1.8, "total_items": 3421, "video_count": 38 },
        "other":  { "used_gb": 0.3 }
      },
      "synced_at": "2025-06-10T09:00:00Z"
    }
  ]
}
```

---

## Security notes

- `.env`, `credentials_*.json`, and `token_*.json` are in `.gitignore` — never committed
- `data/accounts.json` contains only storage stats — no emails, no file names, no personal content
- The GitHub token used by the dashboard only needs `contents: read` (public repos need no token at all)
- Tokens stored as GitHub Action Secrets are encrypted at rest

---

## License

MIT
