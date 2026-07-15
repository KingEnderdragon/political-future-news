"""
EXPERIMENTAL: for each classified item (any arc), tries to connect it to a
REAL bill or resolution - Ohio General Assembly or US Congress - via the
LegiScan API (api.legiscan.com), then asks the local model to write one
sentence explaining the connection.

This is retrieval-grounded, not pure model recall: the model never invents
a bill number or title. It can only (a) propose a search query, and (b)
pick one bill - by id - out of real candidates actually found in LegiScan's
own bill data, or decline all of them. If nothing plausible is found, no
note is generated at all - we'd rather show nothing than show an
unverifiable claim. The model's one-sentence *explanation* of why the item
and the bill are related is still its own interpretation and can still be
wrong, so notes are still marked "experimental" - but the bill identifier,
title, and link a reader can click through to are always real, current
LegiScan records, never hallucinated.

Why local search over LegiScan's own getSearch API: LegiScan's full-text
search ranks by document length/content density, which badly under-ranks
short bills and constitutional-amendment resolutions - a search for "voter
identification" failed to surface SJR 10 ("Require identification to
vote") at all, even though it's a near-perfect topical match, just because
its indexed text is sparse. Instead, this module fetches each session's
full master bill list once (cached to disk, refreshed periodically) and
searches it locally: an exact bill-number match when the article names one
directly (e.g. "SJR 10"), else keyword overlap against titles. Both are
crude compared to a real search index, but neither has that blind spot,
and the model verification step is the real filter against false
positives either way.

Usage: python legislative_context_notes.py [subject_slug]   (defaults to "kaptur")
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import mediaflow_classify as classify
import subjects

REQUEST_TIMEOUT = 90
MAX_CONCURRENT = 3
MAX_RETRIES = 2

HERE = Path(__file__).parent
KEYS_FILE = HERE / "keys.env"
LEGISCAN_URL = "https://api.legiscan.com/"
LEGISCAN_STATES = ("OH", "US")  # Ohio General Assembly + US Congress
MASTER_LIST_CACHE_DIR = HERE / ".legiscan_cache"
MASTER_LIST_MAX_AGE_SECONDS = 24 * 3600
CANDIDATES_PER_QUERY = 8

_BILL_NUMBER_RE = re.compile(r"^(H|S)(B|J?R|CR)\s*0*(\d+)$", re.IGNORECASE)

STATE_LABEL = {"OH": "Ohio General Assembly", "US": "US Congress"}


def load_env_key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name):
                return line.split("=", 1)[1].strip()
    return ""


def normalize_bill_number(raw: str) -> str | None:
    """'SJR 10', 'sjr10', 'SJR-10' all normalize to 'SJR10' so a
    model-proposed query can be matched exactly against the master list's
    own number format regardless of how the model or the source article
    happened to space/punctuate it."""

    compact = re.sub(r"[\s\-.]", "", raw or "").upper()
    if _BILL_NUMBER_RE.match(compact):
        return compact
    return None


def fetch_master_list(state: str, api_key: str) -> dict[str, dict]:
    """Returns {normalized_bill_number: {number, title, url, last_action,
    state}}, cached to disk per state and refreshed once a day - a full
    session's bill list is a few thousand rows and doesn't change on a
    per-item basis, so there's no reason to re-fetch it for every item in
    a run, let alone every run."""

    MASTER_LIST_CACHE_DIR.mkdir(exist_ok=True)
    cache_path = MASTER_LIST_CACHE_DIR / f"{state}.json"
    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < MASTER_LIST_MAX_AGE_SECONDS:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    response = requests.get(
        LEGISCAN_URL,
        params={"key": api_key, "op": "getMasterList", "state": state},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "OK":
        # Stale cache beats no data at all if LegiScan hiccups.
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        return {}

    raw_list = data.get("masterlist", {})
    indexed: dict[str, dict] = {}
    for key, bill in raw_list.items():
        if key == "session" or not isinstance(bill, dict):
            continue
        number = bill.get("number", "")
        normalized = normalize_bill_number(number)
        if not normalized:
            continue
        indexed[normalized] = {
            "number": number,
            "title": bill.get("title", ""),
            "url": bill.get("url", ""),
            "last_action": bill.get("last_action", ""),
            "state": state,
        }

    cache_path.write_text(json.dumps(indexed, ensure_ascii=False), encoding="utf-8")
    return indexed


def load_all_master_lists(api_key: str) -> dict[str, dict]:
    combined: dict[str, dict] = {}
    for state in LEGISCAN_STATES:
        for normalized, bill in fetch_master_list(state, api_key).items():
            combined[f"{state}:{normalized}"] = bill
    return combined


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset("a an the and or but is are was were to of in on for with that this act bill".split())


def _significant_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def search_master_lists(query: str, master_lists: dict[str, dict]) -> list[dict]:
    """Exact bill-number match first (deterministic, handles the common
    case where the article names the bill directly); falls back to
    keyword-overlap scoring against titles otherwise."""

    normalized_query = normalize_bill_number(query)
    if normalized_query:
        hits = [bill for key, bill in master_lists.items() if key.endswith(f":{normalized_query}")]
        if hits:
            return hits[:CANDIDATES_PER_QUERY]

    query_words = _significant_words(query)
    if not query_words:
        return []

    scored = []
    for bill in master_lists.values():
        title_words = _significant_words(bill["title"])
        overlap = len(query_words & title_words)
        if overlap:
            scored.append((overlap, bill))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [bill for _score, bill in scored[:CANDIDATES_PER_QUERY]]


def build_query_prompt(subject_context: str) -> str:
    return f"""You are proposing a search query to look up a news item about {subject_context} against real Ohio General Assembly and US Congress bill records. This is just a search query proposal, not a citation - a later step verifies whatever the search actually finds, so it is safe and encouraged to search whenever there's a plausible legislative angle, even a loose one. Er on the side of proposing a query.

Input: a JSON object with id, title, summary.
Output: a single JSON object with exactly these keys:
  id            - same as input
  has_candidate - true unless this item has genuinely nothing to do with government, policy, or legislation (e.g. pure campaign horse-race coverage, a candidate's personal biography)
  search_query  - if has_candidate is true, EITHER the exact bill/resolution number if one is stated (e.g. "SJR 10", "HB 233", "HR 1") OR 2-6 keywords for the underlying policy topic if no specific bill is named (e.g. "SNAP work requirements", "voter identification"); empty string otherwise

If the title or summary explicitly names a bill or resolution number, always use that exact number as the search_query - do not paraphrase it into keywords. Output ONLY the JSON object, no other text."""


def build_selection_prompt(subject_context: str) -> str:
    return f"""You are given a news item about {subject_context} and a list of REAL candidate bills/resolutions (Ohio General Assembly or US Congress) found by searching LegiScan's official records. At most one of these candidates may actually be what the news item is about - full-text/keyword search returns plenty of false positives.

Input: a JSON object with id, title, summary, and candidates (a list of {{bill_index, identifier, jurisdiction, title, latest_action}}).
Output: a single JSON object with exactly these keys:
  id          - same as input
  bill_index  - the bill_index of the ONE candidate that is genuinely, specifically relevant to this news item, or -1 if none of the candidates are actually relevant (do not force a match)
  note        - if bill_index is not -1: ONE sentence (<=200 chars) explaining the connection, and it MUST reference the bill by its real identifier (e.g. "HB 233") somewhere in the sentence. Empty string if bill_index is -1.
  confidence  - "low", "medium", or "high" - your honest confidence that the connection you described is accurate (not whether the bill exists - it does; this is about whether your explanation of the link is right)

Be skeptical - a bill merely sharing a keyword with the article is not enough; the topic must genuinely match. Output ONLY the JSON object, no other text."""


def ollama_chat(system: str, user_content: str) -> str:
    response = requests.post(
        f"{classify.OLLAMA_URL}/api/chat",
        json={
            "model": classify.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.3},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def parse_response(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def propose_query(item: dict, subject_context: str) -> str | None:
    payload = {"id": item["id"], "title": item.get("title", ""), "summary": item.get("arc_summary") or item.get("summary", "")}
    system = build_query_prompt(subject_context)
    for attempt in range(MAX_RETRIES + 1):
        try:
            text = ollama_chat(system, json.dumps(payload, ensure_ascii=False))
            data = parse_response(text)
            if data.get("has_candidate") and str(data.get("search_query", "")).strip():
                return str(data["search_query"]).strip()[:120]
            return None
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    return None


def select_bill(item: dict, candidates: list[dict], subject_context: str) -> dict | None:
    payload = {
        "id": item["id"],
        "title": item.get("title", ""),
        "summary": item.get("arc_summary") or item.get("summary", ""),
        "candidates": [
            {
                "bill_index": i,
                "identifier": c["number"],
                "jurisdiction": STATE_LABEL.get(c["state"], c["state"]),
                "title": c["title"],
                "latest_action": c["last_action"],
            }
            for i, c in enumerate(candidates)
        ],
    }
    system = build_selection_prompt(subject_context)
    for attempt in range(MAX_RETRIES + 1):
        try:
            text = ollama_chat(system, json.dumps(payload, ensure_ascii=False))
            data = parse_response(text)
            bill_index = data.get("bill_index", -1)
            if not isinstance(bill_index, int) or bill_index < 0 or bill_index >= len(candidates):
                return None
            note = re.sub(r"\s+", " ", str(data.get("note", ""))).strip()[:220]
            if not note:
                return None
            confidence = data.get("confidence", "low")
            if confidence not in ("low", "medium", "high"):
                confidence = "low"
            bill = candidates[bill_index]
            return {
                "note": note,
                "confidence": confidence,
                "source_bill": bill["number"],
                "source_title": bill["title"],
                "source_url": bill["url"],
                "source_state": bill["state"],
            }
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    return None


def generate_note(item: dict, subject_context: str, master_lists: dict[str, dict]) -> dict:
    """Two real model calls plus a local lookup against real LegiScan data
    per item that gets a note at all - more expensive than the old
    pure-recall version, but every citation this produces is a bill that
    genuinely exists."""

    query = propose_query(item, subject_context)
    if not query:
        return {"note": "", "confidence": "low"}

    candidates = search_master_lists(query, master_lists)
    if not candidates:
        return {"note": "", "confidence": "low"}

    result = select_bill(item, candidates, subject_context)
    if not result:
        return {"note": "", "confidence": "low"}
    return result


def run(subject_slug: str = "kaptur") -> int:
    subject = subjects.get_subject(subject_slug)
    paths = subjects.paths_for(subject_slug)
    if not paths["classified"].exists():
        print(f"No classified file for '{subject_slug}' - run mediaflow_classify.py {subject_slug} first.")
        return 0

    api_key = load_env_key("LEGISCAN_API_KEY")
    if not api_key:
        print("[ERROR] LEGISCAN_API_KEY not set (env var or keys.env). Get a free key at https://legiscan.com/legiscan")
        return 0

    items = json.loads(paths["classified"].read_text(encoding="utf-8"))
    todo = [i for i in items if "legislative_note" not in i]
    if not todo:
        print(f"All {len(items)} items already have legislative-context notes.")
        return 0

    error = classify.check_ollama_available()
    if error:
        print(f"[ERROR] {error}")
        return 0

    print(f"Loading LegiScan master bill lists ({', '.join(LEGISCAN_STATES)})...")
    master_lists = load_all_master_lists(api_key)
    print(f"  {len(master_lists)} bills/resolutions indexed locally.")

    print(
        f"Generating EXPERIMENTAL, LegiScan-grounded legislative-context notes for {len(todo)} items "
        f"({subject['name']}, model={classify.OLLAMA_MODEL})..."
    )
    started = time.perf_counter()
    done = 0
    grounded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        futures = {executor.submit(generate_note, item, subject["context"], master_lists): item for item in todo}
        total = len(futures)
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as e:
                failed += 1
                print(f"  [{done + failed}/{total}] ERROR: {e}")
                continue
            item["legislative_note"] = result["note"]
            item["legislative_note_confidence"] = result["confidence"]
            item["legislative_note_experimental"] = True
            if result["note"]:
                item["legislative_note_source_bill"] = result["source_bill"]
                item["legislative_note_source_title"] = result["source_title"]
                item["legislative_note_source_url"] = result["source_url"]
                item["legislative_note_source_state"] = result["source_state"]
                grounded += 1
            done += 1
            status = f"grounded: {result['source_bill']} ({result.get('source_state', '')})" if result["note"] else "no verified match"
            print(f"  [{done + failed}/{total}] {item.get('title', '')[:50]} -> {status}")

    paths["classified"].write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    elapsed = time.perf_counter() - started
    print(
        f"Done - {done} items processed ({grounded} grounded to a real bill, "
        f"{done - grounded} had no verified match), {failed} failed, in {elapsed:.1f}s."
    )
    return done


if __name__ == "__main__":
    # Usage: python legislative_context_notes.py [subject_slug] [model]
    # model defaults to qwen2.5:14b (fast, less detailed); pass mistral-small
    # for slower but more detailed/thorough connection explanations. Same
    # toggle as the dashboard's model selector.
    slug = sys.argv[1] if len(sys.argv) > 1 else "kaptur"
    if len(sys.argv) > 2:
        classify.OLLAMA_MODEL = sys.argv[2]
    run(slug)
