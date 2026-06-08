"""
MediaFlow worker — runs collect + classify on a fixed interval,
and commits a daily data snapshot to GitHub for archival.

Deploy as a second Railway service from the same repo with:
  start command: python worker.py

Environment variables:
  DATA_DIR               path to shared Railway volume (default: repo dir)
  COLLECT_INTERVAL_SECONDS  collect+classify cadence in seconds (default: 900)
  GITHUB_TOKEN           personal access token for daily snapshot commits
"""

import os
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

import rss_collect
import mediaflow_classify

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE))
INTERVAL = int(os.environ.get("COLLECT_INTERVAL_SECONDS", 900))

_last_snapshot_date: date | None = None
_git_ready = False


def git_setup() -> bool:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("[snapshot] GITHUB_TOKEN not set — daily snapshots disabled")
        return False
    try:
        subprocess.run(["git", "config", "user.name", "MediaFlow Worker"], cwd=HERE, check=True)
        subprocess.run(["git", "config", "user.email", "worker@mediaflow.local"], cwd=HERE, check=True)
        subprocess.run(
            ["git", "remote", "set-url", "origin",
             f"https://x-token:{token}@github.com/OwenTanzer/oil-futures.git"],
            cwd=HERE, check=True,
        )
        print("[snapshot] git configured")
        return True
    except Exception as e:
        print(f"[snapshot] git setup failed: {e}")
        return False


def daily_snapshot() -> None:
    global _last_snapshot_date
    today = date.today()
    if _last_snapshot_date == today:
        return

    snapshot_dir = HERE / "snapshots" / today.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    data_files = [
        "mediaflow_items.json",
        "mediaflow_classified.json",
        "mediaflow_seen.json",
        "mediaflow_log.txt",
    ]
    for fname in data_files:
        src = DATA_DIR / fname
        if src.exists():
            shutil.copy2(src, snapshot_dir / fname)

    add = subprocess.run(
        ["git", "add", f"snapshots/{today.isoformat()}/"],
        cwd=HERE, capture_output=True, text=True,
    )
    commit = subprocess.run(
        ["git", "commit", "-m", f"snapshot: {today.isoformat()}"],
        cwd=HERE, capture_output=True, text=True,
    )
    if commit.returncode == 0:
        subprocess.run(["git", "push"], cwd=HERE, check=True)
        print(f"[snapshot] pushed {today.isoformat()}")
        _last_snapshot_date = today
    elif "nothing to commit" in commit.stdout:
        print(f"[snapshot] nothing new for {today.isoformat()}")
        _last_snapshot_date = today
    else:
        print(f"[snapshot] commit failed: {commit.stderr.strip()}")


def run_cycle() -> None:
    print("--- collect ---")
    rss_collect.run()
    print("--- classify ---")
    mediaflow_classify.run()
    if _git_ready:
        daily_snapshot()


if __name__ == "__main__":
    print(f"Worker started. Interval: {INTERVAL}s  DATA_DIR: {DATA_DIR}")
    _git_ready = git_setup()
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[ERROR] cycle failed: {e}")
        time.sleep(INTERVAL)
