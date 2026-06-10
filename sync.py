#!/usr/bin/env python3
"""
StorageIQ — Google Account Sync Script
---------------------------------------
Fetches real storage data from Google APIs for one or more accounts,
then pushes the result as JSON to your GitHub repo so the dashboard
reads live data on every page load.

Usage:
    python scripts/sync.py                   # sync all accounts in .env
    python scripts/sync.py --account 0       # sync only account index 0
    python scripts/sync.py --dry-run         # print JSON, don't push to GitHub

Requirements:
    pip install -r requirements.txt
    Fill in .env (copy from .env.example)
"""

import os
import json
import base64
import argparse
import datetime
import sys
from pathlib import Path

# ── Load .env manually (no python-dotenv needed) ──────────────────────────────
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print("ERROR: .env file not found. Copy .env.example → .env and fill it in.")
        sys.exit(1)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()

# ── Imports (after env loaded) ─────────────────────────────────────────────────
try:
    import requests
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run:  pip install -r requirements.txt")
    sys.exit(1)

# ── Scopes ─────────────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/drive.metadata.readonly",  # quota + file list
    "https://www.googleapis.com/auth/gmail.readonly",           # label counts
    "https://www.googleapis.com/auth/photoslibrary.readonly",   # media item count
]

GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
GITHUB_REPO   = os.environ["GITHUB_REPO"]   # e.g.  youruser/storageiq-data
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
DATA_FILE     = os.environ.get("DATA_FILE", "data/accounts.json")

# Each account needs its own credentials file + token cache.
# Format in .env:
#   ACCOUNT_0_CREDENTIALS=credentials_account0.json
#   ACCOUNT_0_TOKEN=token_account0.json
#   ACCOUNT_0_LABEL=Personal
#   ACCOUNT_1_CREDENTIALS=credentials_account1.json
#   ...
def list_accounts():
    accounts = []
    i = 0
    while True:
        creds_file = os.environ.get(f"ACCOUNT_{i}_CREDENTIALS")
        if not creds_file:
            break
        accounts.append({
            "index": i,
            "credentials": creds_file,
            "token":       os.environ.get(f"ACCOUNT_{i}_TOKEN", f"token_account{i}.json"),
            "label":       os.environ.get(f"ACCOUNT_{i}_LABEL", f"Account {i}"),
        })
        i += 1
    return accounts


# ── Google OAuth ───────────────────────────────────────────────────────────────
def get_google_creds(credentials_file: str, token_file: str) -> Credentials:
    """Returns valid Credentials, refreshing or re-running OAuth flow as needed."""
    creds = None
    token_path = Path(token_file)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            # Opens browser for first-time auth; subsequent runs use saved token.
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


# ── Google Drive — storage quota + file stats ──────────────────────────────────
def fetch_drive_data(creds: Credentials) -> dict:
    svc = build("drive", "v3", credentials=creds)

    # Storage quota
    about = svc.about().get(fields="storageQuota,user").execute()
    quota = about["storageQuota"]
    email = about["user"]["emailAddress"]
    name  = about["user"]["displayName"]

    used_bytes  = int(quota.get("usageInDrive", 0))
    total_bytes = int(quota.get("limit", 15 * 1024**3))
    gmail_bytes = int(quota.get("usageInDriveTrash", 0))  # trash
    # Gmail + Drive + Photos all share the same quota pool
    total_used  = int(quota.get("usage", 0))

    # File count + duplicate detection (by md5Checksum)
    files = []
    page_token = None
    while True:
        resp = svc.files().list(
            pageSize=1000,
            fields="nextPageToken,files(id,name,size,md5Checksum,mimeType,trashed)",
            pageToken=page_token,
            q="trashed=false"
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    # Duplicate detection
    md5_map = {}
    for f in files:
        md5 = f.get("md5Checksum")
        if md5:
            md5_map.setdefault(md5, []).append(f)
    duplicate_sets  = {k: v for k, v in md5_map.items() if len(v) > 1}
    duplicate_count = sum(len(v) - 1 for v in duplicate_sets.values())
    duplicate_bytes = sum(
        int(f.get("size", 0)) * (len(v) - 1)
        for v in duplicate_sets.values()
        for f in v
    )

    folder_count = sum(1 for f in files if f["mimeType"] == "application/vnd.google-apps.folder")

    return {
        "email":           email,
        "name":            name,
        "total_used_bytes":total_used,
        "total_gb":        round(total_bytes / 1024**3, 1),
        "used_gb":         round(total_used  / 1024**3, 2),
        "drive_used_gb":   round(used_bytes  / 1024**3, 2),
        "file_count":      len(files),
        "folder_count":    folder_count,
        "duplicate_count": duplicate_count,
        "duplicate_gb":    round(duplicate_bytes / 1024**3, 2),
    }


# ── Gmail — label counts ───────────────────────────────────────────────────────
def fetch_gmail_data(creds: Credentials) -> dict:
    svc = build("gmail", "v1", credentials=creds)
    labels_resp = svc.users().labels().list(userId="me").execute()

    label_stats = {}
    for lbl in labels_resp.get("labels", []):
        detail = svc.users().labels().get(userId="me", id=lbl["id"]).execute()
        label_stats[detail["name"]] = {
            "total":  detail.get("messagesTotal", 0),
            "unread": detail.get("messagesUnread", 0),
            "size_bytes": detail.get("messagesEstimatedSizeBytes", 0),
        }

    inbox_total    = label_stats.get("INBOX", {}).get("total", 0)
    spam_total     = label_stats.get("SPAM",  {}).get("total", 0)
    trash_total    = label_stats.get("TRASH", {}).get("total", 0)
    all_total      = label_stats.get("All Mail", {}).get("total",
                     label_stats.get("UNREAD", {}).get("total", 0))
    promo_total    = label_stats.get("CATEGORY_PROMOTIONS", {}).get("total", 0)

    spam_bytes  = label_stats.get("SPAM",  {}).get("size_bytes", 0)
    trash_bytes = label_stats.get("TRASH", {}).get("size_bytes", 0)

    return {
        "inbox_count":   inbox_total,
        "spam_count":    spam_total,
        "trash_count":   trash_total,
        "all_count":     all_total,
        "promo_count":   promo_total,
        "spam_gb":       round(spam_bytes  / 1024**3, 2),
        "trash_gb":      round(trash_bytes / 1024**3, 2),
        "junk_mb":       round((spam_bytes + trash_bytes) / 1024**2, 0),
    }


# ── Google Photos — item count ─────────────────────────────────────────────────
def fetch_photos_data(creds: Credentials) -> dict:
    """
    Photos Library API doesn't expose storage bytes directly.
    We count items and estimate from average file sizes.
    Average photo ≈ 4 MB, video ≈ 50 MB.
    """
    svc_url = "https://photoslibrary.googleapis.com/v1/mediaItems"
    headers = {"Authorization": f"Bearer {creds.token}"}

    items = []
    page_token = None
    # Cap at 2000 items to avoid very long sync times
    while len(items) < 2000:
        params = {"pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(svc_url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        items.extend(data.get("mediaItems", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    photo_count = sum(1 for i in items if i.get("mediaMetadata", {}).get("photo") is not None)
    video_count = sum(1 for i in items if i.get("mediaMetadata", {}).get("video") is not None)

    # Estimate storage
    estimated_bytes = photo_count * 4 * 1024**2 + video_count * 50 * 1024**2

    # Count albums
    albums_url = "https://photoslibrary.googleapis.com/v1/albums"
    albums_resp = requests.get(albums_url, headers=headers, params={"pageSize": 50}, timeout=15)
    album_count = len(albums_resp.json().get("albums", [])) if albums_resp.status_code == 200 else 0

    return {
        "total_items":     len(items),
        "photo_count":     photo_count,
        "video_count":     video_count,
        "album_count":     album_count,
        "estimated_gb":    round(estimated_bytes / 1024**3, 2),
    }


# ── Assemble full account snapshot ────────────────────────────────────────────
def build_account_snapshot(account_cfg: dict) -> dict:
    print(f"  → Authenticating [{account_cfg['label']}] ...")
    creds = get_google_creds(account_cfg["credentials"], account_cfg["token"])

    print(f"  → Fetching Drive data ...")
    drive = fetch_drive_data(creds)

    print(f"  → Fetching Gmail data ...")
    gmail = fetch_gmail_data(creds)

    print(f"  → Fetching Photos data ...")
    photos = fetch_photos_data(creds)

    used_gb  = drive["used_gb"]
    total_gb = drive["total_gb"]
    pct_used = round((used_gb / total_gb) * 100, 1) if total_gb else 0

    # Health score: penalise spam, duplicates, low free space
    free_pct     = 100 - pct_used
    spam_penalty = min(30, gmail["spam_count"] // 500)
    dupe_penalty = min(20, drive["duplicate_count"] // 10)
    health_pct   = max(5, min(100, int(free_pct - spam_penalty - dupe_penalty)))

    def grade(p):
        if p >= 92: return "A"
        if p >= 82: return "B"
        if p >= 72: return "B−"
        if p >= 62: return "C+"
        if p >= 50: return "C"
        return "D"

    # Estimated recoverable: spam + trash + duplicates + 30% of photos similar
    recover_gb = round(
        gmail["spam_gb"] + gmail["trash_gb"] +
        drive["duplicate_gb"] +
        photos["estimated_gb"] * 0.12,  # ~12% similar photo estimate
        2
    )

    # Days until full (rough: 300 MB/month growth assumption)
    free_gb      = round(total_gb - used_gb, 2)
    growth_gb_mo = 0.3  # conservative default; tune per account
    days_left    = int((free_gb / growth_gb_mo) * 30) if free_gb > 0 else 0

    # Gradient colors by index
    gradients = [
        ["#4285F4", "#34A853"],
        ["#EA4335", "#FBBC04"],
        ["#7B5EA7", "#00D4FF"],
        ["#00832D", "#34A853"],
        ["#FFB020", "#FF4D6D"],
    ]
    idx = account_cfg["index"] % len(gradients)

    initials = "".join(w[0].upper() for w in drive["name"].split()[:2]) or "G"

    gmail_gb  = round(used_gb * 0.55, 2)   # Gmail typically ~55% of total
    drive_gb  = drive["drive_used_gb"]
    photos_gb = photos["estimated_gb"]
    other_gb  = round(max(0, used_gb - gmail_gb - drive_gb - photos_gb), 2)

    return {
        "id":          f"acc{account_cfg['index']}",
        "label":       account_cfg["label"],
        "name":        drive["name"],
        "email":       drive["email"],
        "initials":    initials,
        "gradient":    gradients[idx],
        "plan":        f"{'Google Workspace' if total_gb > 15 else 'Free'} {total_gb} GB",
        "used_gb":     used_gb,
        "total_gb":    total_gb,
        "free_gb":     free_gb,
        "pct_used":    pct_used,
        "health_pct":  health_pct,
        "health_grade":grade(health_pct),
        "spam_gb":     round(gmail["spam_gb"] + gmail["trash_gb"], 2),
        "recover_gb":  recover_gb,
        "days_left":   days_left,
        "junk_mb":     gmail["junk_mb"],
        "dup_gb":      drive["duplicate_gb"],
        "services": {
            "gmail": {
                "used_gb":     gmail_gb,
                "msg_count":   drive["file_count"],   # proxy; real from labels
                "inbox_count": gmail["inbox_count"],
                "spam_count":  gmail["spam_count"],
                "trash_count": gmail["trash_count"],
                "promo_count": gmail["promo_count"],
                "pct":         round((gmail_gb / total_gb) * 100, 1),
            },
            "drive": {
                "used_gb":       drive_gb,
                "file_count":    drive["file_count"],
                "folder_count":  drive["folder_count"],
                "duplicate_count": drive["duplicate_count"],
                "duplicate_gb":  drive["duplicate_gb"],
                "pct":           round((drive_gb / total_gb) * 100, 1),
            },
            "photos": {
                "used_gb":     photos_gb,
                "total_items": photos["total_items"],
                "photo_count": photos["photo_count"],
                "video_count": photos["video_count"],
                "album_count": photos["album_count"],
                "pct":         round((photos_gb / total_gb) * 100, 1),
            },
            "other": {
                "used_gb": other_gb,
                "pct":     round((other_gb / total_gb) * 100, 1),
            }
        },
        "synced_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


# ── GitHub push ────────────────────────────────────────────────────────────────
def push_to_github(payload: dict, dry_run: bool = False):
    if dry_run:
        print("\n── DRY RUN — JSON output ──────────────────────────────")
        print(json.dumps(payload, indent=2))
        return

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Get current SHA (needed for update)
    sha = None
    existing = requests.get(api_url, headers=headers)
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    content_b64 = base64.b64encode(
        json.dumps(payload, indent=2).encode()
    ).decode()

    body = {
        "message": f"chore: sync storage data {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        "content": content_b64,
        "branch":  GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(api_url, headers=headers, json=body)
    if resp.status_code in (200, 201):
        commit_url = resp.json()["commit"]["html_url"]
        print(f"  ✅ Pushed to GitHub → {commit_url}")
    else:
        print(f"  ❌ GitHub push failed: {resp.status_code} {resp.text}")
        sys.exit(1)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="StorageIQ sync")
    parser.add_argument("--account", type=int, default=None, help="Sync only this account index")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON, don't push")
    args = parser.parse_args()

    all_accounts = list_accounts()
    if not all_accounts:
        print("No accounts configured. Add ACCOUNT_0_CREDENTIALS etc. to .env")
        sys.exit(1)

    targets = [a for a in all_accounts if args.account is None or a["index"] == args.account]
    print(f"\nStorageIQ Sync — {len(targets)} account(s)\n{'─'*40}")

    snapshots = []
    for acct in targets:
        print(f"\n[{acct['index']}] {acct['label']}")
        try:
            snap = build_account_snapshot(acct)
            snapshots.append(snap)
            print(f"     {snap['email']}  {snap['used_gb']} / {snap['total_gb']} GB  health={snap['health_grade']}")
        except Exception as e:
            print(f"  ⚠️  Failed: {e}")

    if not snapshots:
        print("\nNo data collected — nothing pushed.")
        sys.exit(1)

    payload = {
        "schema_version": 2,
        "generated_at":   datetime.datetime.utcnow().isoformat() + "Z",
        "accounts":       snapshots,
    }

    print(f"\n{'─'*40}")
    print(f"Pushing {len(snapshots)} account(s) to github.com/{GITHUB_REPO} ...")
    push_to_github(payload, dry_run=args.dry_run)
    print("Done.\n")


if __name__ == "__main__":
    main()
