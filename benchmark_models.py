"""
One-off benchmark: runs the same digest-generation task (critical summary +
analysis + source-linked talking points) for a fixed set of arcs/windows
against several local Ollama models, so outputs can be compared side by
side. Does not touch mediaflow_digest.json or any live data.
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import weekly_digest as wd

HERE = Path(__file__).parent
OUT_FILE = HERE / "benchmark_results.json"

MODELS = ["llama3.1:8b", "qwen2.5:14b", "phi4:14b"]

# Chosen for having enough items to exercise real synthesis (not the
# "no items" trivial path) and a mix of item counts across the two windows.
TEST_CASES = [
    {"arc": "DISTRICT", "window_days": 30},
    {"arc": "CAMPAIGN", "window_days": 30},
    {"arc": "LEGISLATION", "window_days": 7},
]


def run_case(model: str, arc: str, window_days: int) -> dict:
    items = wd.load_classified()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)
    arc_items = wd.items_in_window(items, arc, window_start)

    original_model = wd.classify.OLLAMA_MODEL
    wd.classify.OLLAMA_MODEL = model
    try:
        started = time.perf_counter()
        result = wd.generate_arc_digest(wd.ARC_LABEL[arc], arc_items, window_days)
        elapsed = time.perf_counter() - started
    finally:
        wd.classify.OLLAMA_MODEL = original_model

    return {
        "model": model,
        "arc": arc,
        "window_days": window_days,
        "item_count": result.get("item_count"),
        "elapsed_sec": round(elapsed, 1),
        "critical_summary": result.get("critical_summary"),
        "analysis": result.get("analysis"),
        "talking_points": result.get("talking_points"),
    }


def main() -> None:
    models = sys.argv[1:] or MODELS
    results = []
    for model in models:
        print(f"\n=== {model} ===")
        for case in TEST_CASES:
            print(f"  {case['arc']} / {case['window_days']}d ...", end=" ", flush=True)
            try:
                r = run_case(model, case["arc"], case["window_days"])
                print(f"ok ({r['elapsed_sec']}s, {len(r['talking_points'])} points)")
            except Exception as e:
                r = {"model": model, **case, "error": str(e)}
                print(f"ERROR: {e}")
            results.append(r)

    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUT_FILE}")


if __name__ == "__main__":
    main()
