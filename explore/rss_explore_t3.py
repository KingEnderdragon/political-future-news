"""
Tier 3 RSS feed probe — Israeli press, Gulf, European, regional.
Same methodology as T1/T2 probes.
"""

import feedparser
import re
from datetime import datetime, timezone

FEEDS = {
    "Times of Israel":  "https://www.timesofisrael.com/feed",
    "Haaretz":          "https://www.haaretz.com/cmlink/1.628765",
    "Gulf News":        "https://gulfnews.com/rss",
    "Rudaw":            "https://www.rudaw.net/english/rss",
    "DW World":         "https://rss.dw.com/rdf/rss-en-all",
    "RFE/RL":           "https://www.rferl.org/api/epiqq",
}

KEYWORDS = [
    "iran", "hormuz", "irgc", "tehran", "persian gulf",
    "strait", "khamenei", "pezeshkian", "nuclear deal",
    "jcpoa", "enrichment", "sanctions", "arabian sea",
    "gulf of oman", "ballistic missile", "tanker",
    "operation epic fury", "oil", "crude", "shipping",
    "hezbollah", "israel", "beirut", "ceasefire",
]
KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)


def is_relevant(entry: dict) -> bool:
    text = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(t.get("term", "") for t in entry.get("tags", [])),
    ])
    return bool(KEYWORD_RE.search(text))


def clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()[:200]


def probe(name: str, url: str) -> dict:
    r = {
        "name": name, "url": url,
        "status": None, "total": 0, "relevant": [],
        "fields": set(), "has_summary": False,
        "has_content": False, "has_tags": False, "error": None,
    }
    try:
        feed = feedparser.parse(url)
        r["status"] = feed.get("status", "no-status")
        entries = feed.get("entries", [])
        r["total"] = len(entries)
        for entry in entries:
            r["fields"].update(entry.keys())
            if entry.get("summary"):  r["has_summary"] = True
            if entry.get("content"):  r["has_content"] = True
            if entry.get("tags"):     r["has_tags"]    = True
            if is_relevant(entry):
                r["relevant"].append({
                    "title":     entry.get("title", "(no title)").strip(),
                    "published": entry.get("published", entry.get("updated", "?")),
                    "summary":   clean(entry.get("summary", "")),
                    "link":      entry.get("link", ""),
                    "has_body":  bool(entry.get("content")),
                })
    except Exception as e:
        r["error"] = str(e)
    r["fields"] = sorted(r["fields"])
    return r


def print_result(r: dict) -> None:
    status = f"HTTP {r['status']}" if r["status"] else f"ERROR: {r['error']}"
    print(f"\n{'='*68}")
    print(f"  {r['name']}")
    print(f"  {r['url']}")
    print(f"  {status}  |  Total: {r['total']}  |  Relevant: {len(r['relevant'])}")

    if r["error"] and not r["status"]:
        return

    key = {"title", "summary", "content", "published", "updated", "tags", "author"}
    print(f"  Present: {sorted(key & set(r['fields']))}")
    print(f"  Absent:  {sorted(key - set(r['fields']))}")
    print(f"  Summary: {r['has_summary']}  |  Full body: {r['has_content']}  |  Tags: {r['has_tags']}")

    if not r["relevant"]:
        print("  [no relevant entries]")
        return

    for i, a in enumerate(r["relevant"][:5]):
        print(f"\n  [{i+1}] {a['published'][:25]}")
        print(f"       {a['title'][:85]}")
        if a["summary"] and a["summary"] != a["title"]:
            print(f"       {a['summary'][:120]}")
        print(f"       {a['link'][:80]}")


if __name__ == "__main__":
    print(f"Tier 3 RSS Probe  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    results = []
    for name, url in FEEDS.items():
        r = probe(name, url)
        results.append(r)
        print_result(r)

    print(f"\n\n{'='*68}")
    print("SUMMARY")
    print(f"{'='*68}")
    for r in results:
        status = r["status"] or "ERROR"
        print(f"  {r['name']:<22}  status={status}  total={r['total']}  relevant={len(r['relevant'])}")
    print("\nDone.")
