"""
EXPERIMENTAL: for each classified item (any arc), asks the local model to
connect it to relevant Ohio or federal legislative/policy background FROM
ITS OWN KNOWLEDGE — unlike the rest of this pipeline, this is NOT grounded
in a retrieved source. It can hallucinate specific bill numbers, statute
citations, or dates. Every note is stored with an explicit "experimental"
flag and a confidence level, and must be rendered with a visible warning
wherever it's shown (see render_item()/render_feed_item() callers).

Usage: python legislative_context_notes.py [subject_slug]   (defaults to "kaptur")
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import mediaflow_classify as classify
import subjects

REQUEST_TIMEOUT = 90
MAX_CONCURRENT = 3
MAX_RETRIES = 2


def build_system_prompt(subject_context: str) -> str:
    return f"""You are connecting a news item about {subject_context} to broader legislative or policy background you know about — Ohio General Assembly process, US Congress process, relevant Ohio Revised Code sections, or historical/institutional context.

This is background knowledge, NOT a verified lookup — you have no live source confirming this specific connection.

Input: a JSON object with id, title, summary.
Output: a single JSON object with exactly these keys:
  id         - same as input
  note       - ONE sentence (<=160 chars) connecting this item to relevant legislative/policy background, OR the literal string "No clear connection" if you don't have confident background knowledge to add
  confidence - "low", "medium", or "high" — your honest confidence that the note is factually accurate

Do not invent specific bill numbers, statute citations, or dates unless you are genuinely confident they are correct. When unsure, say so or use "No clear connection." Output ONLY the JSON object, no other text."""


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


def generate_note(item: dict, subject_context: str) -> dict:
    payload = {
        "id": item["id"],
        "title": item.get("title", ""),
        "summary": item.get("arc_summary") or item.get("summary", ""),
    }
    system = build_system_prompt(subject_context)
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            text = ollama_chat(system, json.dumps(payload, ensure_ascii=False))
            data = parse_response(text)
            note = re.sub(r"\s+", " ", str(data.get("note", ""))).strip()[:200]
            confidence = data.get("confidence", "low")
            if confidence not in ("low", "medium", "high"):
                confidence = "low"
            return {"note": note, "confidence": confidence}
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    return {"note": "", "confidence": "low", "error": str(last_error)}


def run(subject_slug: str = "kaptur") -> int:
    subject = subjects.get_subject(subject_slug)
    paths = subjects.paths_for(subject_slug)
    if not paths["classified"].exists():
        print(f"No classified file for '{subject_slug}' - run mediaflow_classify.py {subject_slug} first.")
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

    print(
        f"Generating EXPERIMENTAL legislative-context notes for {len(todo)} items "
        f"({subject['name']}, model={classify.OLLAMA_MODEL})..."
    )
    started = time.perf_counter()
    done = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
        futures = {executor.submit(generate_note, item, subject["context"]): item for item in todo}
        total = len(futures)
        for future in as_completed(futures):
            item = futures[future]
            result = future.result()
            if "error" in result:
                failed += 1
                print(f"  [{done + failed}/{total}] ERROR: {result['error']}")
                continue
            item["legislative_note"] = result["note"]
            item["legislative_note_confidence"] = result["confidence"]
            item["legislative_note_experimental"] = True
            done += 1
            print(f"  [{done + failed}/{total}] {item.get('title', '')[:60]}")

    paths["classified"].write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    elapsed = time.perf_counter() - started
    print(f"Done - {done} notes generated, {failed} failed in {elapsed:.1f}s. EXPERIMENTAL — may hallucinate.")
    return done


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "kaptur"
    run(slug)
