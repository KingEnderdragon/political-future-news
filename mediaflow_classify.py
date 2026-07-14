"""
KapturFlow classifier: assigns arc, factual summary, and short analysis to
each collected item via a local Ollama model. Runs incrementally and only
sends unclassified items to the model. No external API calls or keys.
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE))
ITEMS_FILE = DATA_DIR / "mediaflow_items.json"
CLASSIFIED_FILE = DATA_DIR / "mediaflow_classified.json"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

# llama3.1:8b reliably classifies one item at a time but silently drops all
# but the first item when given a batch, even with array-output instructions
# and format=json enforcement. One item per request is the reliable mode; a
# local Ollama server largely serializes requests against one model anyway
# so a little request-level concurrency just overlaps network/JSON overhead.
BATCH_SIZE = 1
MAX_CONCURRENT_BATCHES = 3
MAX_RETRIES = 2
REQUEST_TIMEOUT = 120

ARCS = [
    "LEGISLATION",
    "COMMITTEE",
    "DISTRICT",
    "CAMPAIGN",
    "MEDIA",
    "UNMAPPED",
]


def build_system_prompt(arcs: list[str] = ARCS) -> str:
    arc_str = " | ".join(arcs)
    return f"""Classify one news article about US Representative Marcy Kaptur (D-Ohio, 9th District, Toledo).

Input: a JSON object with id, source, title, summary.
Output: a single JSON object with exactly these keys:
  id       - same as input
  arc      - one of: {arc_str}
  summary  - one sentence, <=100 chars, present tense, factual, written in your own words (not copied from the title)
  analysis - one sentence, <=140 chars, explains why it matters (political significance, district impact, or context) — not a restatement of the summary
  conflict - true if the item reports a denial or contradictory claim, else false

Arc guide:
  LEGISLATION - bills she sponsors/cosponsors, floor votes, floor statements
  COMMITTEE   - her committee/subcommittee work (e.g. Appropriations), hearings, oversight
  DISTRICT    - local Ohio 9th District news, events, federal funding/projects for the district
  CAMPAIGN    - her campaign, elections, opponents, endorsements, fundraising
  MEDIA       - interviews, op-eds, press statements not tied to a specific bill or hearing
Use UNMAPPED only when the article is unrelated noise or cannot be assigned to any arc above.
Never omit a key or return null. Output ONLY the JSON object, no other text.

Example:
Input:  {{"id":"x1","source":"Toledo Blade","title":"Kaptur secures funding for Toledo port dredging","summary":"Rep. Kaptur announced $12M in federal funding for Toledo-Lucas County Port Authority dredging."}}
Output: {{"id":"x1","arc":"DISTRICT","summary":"Kaptur secures $12M in federal port dredging funds for Toledo.","analysis":"Reinforces her long-standing focus on Great Lakes shipping infrastructure ahead of reelection.","conflict":false}}

Return only the JSON object."""


def parse_response(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    data = json.loads(text)
    if isinstance(data, dict):
        if "id" in data:
            return [data]
        for value in data.values():
            if isinstance(value, list):
                return value
        return []
    return data


def fallback_arc(item: dict, arcs: list[str] = ARCS) -> str:
    text = f"{item.get('source', '')} {item.get('title', '')} {item.get('summary', '')}".lower()
    rules = [
        ("LEGISLATION", r"\b(bill|act|vote|floor|cosponsor|resolution|amendment)\b"),
        ("COMMITTEE",   r"\b(committee|subcommittee|hearing|appropriations|oversight|ranking member)\b"),
        ("CAMPAIGN",    r"\b(campaign|election|primary|opponent|endorse|fundrais|reelect|challenger)\b"),
        ("DISTRICT",    r"\b(toledo|lucas county|ohio|district|port|shipline|great lakes|grant|funding)\b"),
        ("MEDIA",       r"\b(interview|op-ed|statement|says|said|press release)\b"),
    ]
    for arc, pattern in rules:
        if arc in arcs and re.search(pattern, text):
            return arc
    return "UNMAPPED" if "UNMAPPED" in arcs else arcs[0]


def normalize_result(result: dict, item: dict, arcs: list[str] = ARCS) -> dict:
    arc = result.get("arc")
    if arc not in arcs:
        arc = fallback_arc(item, arcs)

    summary = result.get("summary") or item.get("title", "")
    summary = re.sub(r"\s+", " ", str(summary)).strip()[:140]

    analysis = result.get("analysis") or ""
    analysis = re.sub(r"\s+", " ", str(analysis)).strip()[:180]

    conflict = result.get("conflict", False)
    if not isinstance(conflict, bool):
        conflict = str(conflict).lower() == "true"

    return {
        "id": item["id"],
        "arc": arc,
        "summary": summary,
        "analysis": analysis,
        "conflict": conflict,
    }


def ollama_chat(system: str, user_content: str) -> str:
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def classify_batch(batch: list[dict], arcs: list[str] = ARCS) -> list[dict]:
    item = batch[0]
    payload = {
        "id": item["id"],
        "source": item["source"],
        "title": item["title"],
        "summary": item.get("summary", ""),
    }
    text = ollama_chat(
        build_system_prompt(arcs),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return parse_response(text)


def classify_batch_with_retries(batch: list[dict], arcs: list[str] = ARCS) -> list[dict]:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            raw_results = classify_batch(batch, arcs)
            by_id = {r.get("id"): r for r in raw_results if isinstance(r, dict)}
            return [
                normalize_result(by_id.get(item["id"], {}), item, arcs)
                for item in batch
            ]
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_error)


def load_items() -> list[dict]:
    if not ITEMS_FILE.exists():
        return []
    return json.loads(ITEMS_FILE.read_text(encoding="utf-8"))


def load_classified(items_by_id: dict[str, dict], arcs: list[str]) -> tuple[dict[str, dict], int]:
    classified_by_id: dict[str, dict] = {}
    repaired = 0
    if not CLASSIFIED_FILE.exists():
        return classified_by_id, repaired

    for c in json.loads(CLASSIFIED_FILE.read_text(encoding="utf-8")):
        item = items_by_id.get(c["id"], c)
        if (
            c.get("arc") not in arcs
            or not c.get("arc_summary")
            or not isinstance(c.get("conflict"), bool)
        ):
            normalized = normalize_result({
                "id": c["id"],
                "arc": c.get("arc"),
                "summary": c.get("arc_summary") or c.get("summary") or c.get("title"),
                "analysis": c.get("arc_analysis") or c.get("analysis") or "",
                "conflict": c.get("conflict", False),
            }, item, arcs)
            c = {
                **item,
                "arc": normalized["arc"],
                "arc_summary": normalized["summary"],
                "arc_analysis": normalized["analysis"],
                "conflict": normalized["conflict"],
            }
            repaired += 1
        classified_by_id[c["id"]] = c
    return classified_by_id, repaired


def write_ordered(items: list[dict], classified_by_id: dict[str, dict]) -> None:
    ordered = [
        classified_by_id[item["id"]]
        for item in items
        if item["id"] in classified_by_id
    ]
    CLASSIFIED_FILE.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def check_ollama_available() -> str:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(m.split(":")[0] == OLLAMA_MODEL.split(":")[0] for m in models):
            return f"Model '{OLLAMA_MODEL}' not found in Ollama. Run: ollama pull {OLLAMA_MODEL}"
        return ""
    except Exception as e:
        return f"Ollama not reachable at {OLLAMA_URL}: {e}"


def run(arcs: list[str] = ARCS) -> int:
    """Classify all unclassified items. Returns number of newly classified items."""
    items = load_items()
    if not items:
        print("No items file - run rss_collect.py first.")
        return 0

    items_by_id = {item["id"]: item for item in items}
    classified_by_id, repaired = load_classified(items_by_id, arcs)
    unclassified = [item for item in items if item["id"] not in classified_by_id]

    if not unclassified:
        if repaired:
            write_ordered(items, classified_by_id)
            print(f"Repaired {repaired} malformed classified items.")
        print(f"All {len(items)} items already classified.")
        return 0

    error = check_ollama_available()
    if error:
        print(f"[ERROR] {error}")
        return 0

    print(
        f"Classifying {len(unclassified)} items in batches of {BATCH_SIZE} "
        f"({MAX_CONCURRENT_BATCHES} concurrent, model={OLLAMA_MODEL})..."
    )
    failed = 0
    started = time.perf_counter()
    batches = [
        unclassified[i : i + BATCH_SIZE]
        for i in range(0, len(unclassified), BATCH_SIZE)
    ]

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_BATCHES) as executor:
        futures = {
            executor.submit(classify_batch_with_retries, batch, arcs): (n, batch)
            for n, batch in enumerate(batches, start=1)
        }
        total = len(futures)
        for future in as_completed(futures):
            n, batch = futures[future]
            print(f"  [{n}/{total}] {len(batch)} items...", end=" ", flush=True)
            try:
                results = future.result()
            except Exception as e:
                print(f"ERROR - {e}")
                failed += len(batch)
                continue

            for r in results:
                item = items_by_id.get(r["id"], {})
                classified_by_id[r["id"]] = {
                    **item,
                    "arc": r["arc"],
                    "arc_summary": r["summary"],
                    "arc_analysis": r["analysis"],
                    "conflict": r["conflict"],
                }
            print("ok")

    write_ordered(items, classified_by_id)

    newly_classified = len(unclassified) - failed
    elapsed = time.perf_counter() - started
    print(
        f"Done - {newly_classified} classified, {failed} failed "
        f"in {elapsed:.1f}s. Total stored: {len(classified_by_id)}"
    )
    return newly_classified


if __name__ == "__main__":
    run()
