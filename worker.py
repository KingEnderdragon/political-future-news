"""
MediaFlow worker — runs collect + classify on a fixed interval.
Deploy as a second Railway service from the same repo with:
  start command: python worker.py
Shares a Railway volume with the web service via DATA_DIR env var.
"""

import os
import time
import rss_collect
import mediaflow_classify

INTERVAL = int(os.environ.get("COLLECT_INTERVAL_SECONDS", 900))  # 15 min default


def run_cycle() -> None:
    print("--- collect ---")
    rss_collect.run()
    print("--- classify ---")
    mediaflow_classify.run()


if __name__ == "__main__":
    print(f"Worker started. Interval: {INTERVAL}s")
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"[ERROR] cycle failed: {e}")
        time.sleep(INTERVAL)
