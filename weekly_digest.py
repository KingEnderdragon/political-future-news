"""
KapturFlow digest: for each arc, generates a critical summary and an analysis
grounded in a recent window of classified items, via the same local Ollama
model used for item classification. No external API calls.

Two windows are supported: a strict 7-day "weekly" digest, and a 30-day
digest for when the collector hasn't yet accumulated a full week of fresh
items (a first backfill run mostly surfaces archival search results, not
things published in the last 7 days).
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import mediaflow_classify as classify

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE))
CLASSIFIED_FILE = DATA_DIR / "mediaflow_classified.json"
DIGEST_FILE = DATA_DIR / "mediaflow_digest.json"

WINDOWS = [7, 30]
MAX_ITEMS_PER_ARC = 30  # keeps the prompt within a small local model's context
REQUEST_TIMEOUT = 180
DIGEST_NUM_CTX = 8192  # a week of headlines for a busy arc exceeds Ollama's small default

ARC_LABEL = {
    "LEGISLATION": "Legislation",
    "COMMITTEE":   "Committee",
    "DISTRICT":    "District",
    "CAMPAIGN":    "Campaign",
    "MEDIA":       "Media",
}


def parse_dt(s: str) -> datetime:
    if not s or s == "unknown":
        return datetime.min.replace(tzinfo=timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        pass
    return datetime.min.replace(tzinfo=timezone.utc)


def load_classified() -> list[dict]:
    if not CLASSIFIED_FILE.exists():
        return []
    return json.loads(CLASSIFIED_FILE.read_text(encoding="utf-8"))


def items_in_window(items: list[dict], arc: str, window_start: datetime) -> list[dict]:
    arc_items = [i for i in items if i.get("arc") == arc]
    arc_items = [i for i in arc_items if parse_dt(i.get("published", "")) >= window_start]
    arc_items.sort(key=lambda i: parse_dt(i.get("published", "")), reverse=True)
    return arc_items[:MAX_ITEMS_PER_ARC]


def build_digest_prompt(arc_label: str, items: list[dict], window_days: int) -> str:
    period = "week" if window_days <= 7 else f"{window_days} days"
    lines = [f"- {i.get('arc_summary') or i.get('title', '')}" for i in items]
    return (
        f'Arc: "{arc_label}" for US Rep. Marcy Kaptur (D-Ohio, 9th District).\n'
        f"Here are {len(items)} news items from the past {period} in this arc:\n"
        + "\n".join(lines)
    )


def digest_system_prompt(window_days: int) -> str:
    period = "weekly" if window_days <= 7 else f"{window_days}-day"
    span = "week" if window_days <= 7 else f"{window_days} days"
    return f"""You are a political analyst producing a {period} digest for Rep. Marcy Kaptur (D-Ohio, 9th District, Toledo).

You will be given one arc's worth of recent news items as a bulleted list.
Output a single JSON object with exactly these keys:
  critical_summary - 2-3 sentences, present tense, factual, naming the concrete events/developments. Not a list restatement — synthesize into a coherent narrative of what happened in the past {span} in this arc.
  analysis          - 2-3 sentences of critical analysis: political significance, trends across the items, tensions/contradictions if any, and what it signals about her position (district, reelection, party, or policy standing). Go beyond restating the summary.
  talking_points    - a JSON array of 3-5 short strings (each <=110 chars), the specific points someone briefing on this arc would want on hand.

CRITICAL GROUNDING RULE for talking_points: only state a number, date, dollar amount, vote count, or named bill/act if that exact figure appears in the input bullets below. If the input bullet is vague (e.g. "Kaptur announces funding for X" with no dollar figure), write the talking point just as vaguely — do NOT invent a specific number, date, or citation to fill the gap. A vague-but-true point is required; a precise-but-fabricated one is not acceptable.

Be direct and specific. Do not hedge with "it appears" or "some may say." Output ONLY the JSON object, no other text."""


def ollama_chat_digest(system_prompt: str, user_content: str) -> str:
    response = requests.post(
        f"{classify.OLLAMA_URL}/api/chat",
        json={
            "model": classify.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": DIGEST_NUM_CTX},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def parse_digest_response(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def normalize_talking_points(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    points = []
    for p in raw:
        p = re.sub(r"\s+", " ", str(p)).strip().lstrip("-•* ").strip()
        if p:
            points.append(p[:160])
    return points[:6]


def generate_arc_digest(arc_label: str, items: list[dict], window_days: int) -> dict:
    period = "week" if window_days <= 7 else f"{window_days} days"
    if not items:
        return {
            "item_count": 0,
            "critical_summary": f"No items in the past {period}.",
            "analysis": "",
            "talking_points": [],
        }
    prompt = build_digest_prompt(arc_label, items, window_days)
    system_prompt = digest_system_prompt(window_days)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            text = ollama_chat_digest(system_prompt, prompt)
            data = parse_digest_response(text)
            return {
                "item_count": len(items),
                "critical_summary": str(data.get("critical_summary", "")).strip(),
                "analysis": str(data.get("analysis", "")).strip(),
                "talking_points": normalize_talking_points(data.get("talking_points")),
            }
        except Exception as e:
            last_error = e
            time.sleep(1.5 * (attempt + 1))
    return {
        "item_count": len(items),
        "critical_summary": f"[digest generation failed: {last_error}]",
        "analysis": "",
        "talking_points": [],
    }


def generate_window(window_days: int, arcs: dict[str, str] = ARC_LABEL) -> dict:
    error = classify.check_ollama_available()
    if error:
        return {"error": error}

    items = load_classified()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)

    digest = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": window_days,
        "arcs": {},
    }
    for arc, label in arcs.items():
        arc_items = items_in_window(items, arc, window_start)
        digest["arcs"][arc] = generate_arc_digest(label, arc_items, window_days)

    return digest


def generate(windows: list[int] = WINDOWS, arcs: dict[str, str] = ARC_LABEL) -> dict:
    """Generates a digest for each window and persists all of them together."""
    all_digests = load()
    for window_days in windows:
        all_digests[str(window_days)] = generate_window(window_days, arcs)
    DIGEST_FILE.write_text(json.dumps(all_digests, indent=2, ensure_ascii=False), encoding="utf-8")
    return all_digests


def load() -> dict:
    if not DIGEST_FILE.exists():
        return {}
    return json.loads(DIGEST_FILE.read_text(encoding="utf-8"))


def load_window(window_days: int) -> dict:
    return load().get(str(window_days), {})


if __name__ == "__main__":
    result = generate()
    print(json.dumps(result, indent=2))
