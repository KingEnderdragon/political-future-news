"""
Additional feeds probe — aggregators, specialists, Reddit, financial, think tanks.
Same methodology as prior tier probes.
"""

import feedparser
import re
from datetime import datetime, timezone

KEYWORDS = [
    "iran", "hormuz", "irgc", "tehran", "strait", "sanctions",
    "nuclear", "missile", "oil", "crude", "tanker", "hezbollah",
    "ceasefire", "gulf", "persian", "barrel", "opec", "brent", "wti",
]
KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)

FEEDS = {
    # Priority 1 — Search engine aggregators
    "Bing News: iran hormuz":      "https://www.bing.com/news/search?q=iran+hormuz&format=rss",
    "Bing News: hormuz tanker":    "https://www.bing.com/news/search?q=hormuz+tanker&format=rss",
    "Bing News: IRGC missile":     "https://www.bing.com/news/search?q=IRGC+missile&format=rss",
    "Yahoo News RSS":              "https://news.yahoo.com/rss/",

    # Priority 2 — Specialists
    "gCaptain":                    "https://gcaptain.com/feed/",
    "Marine Insight":              "https://www.marineinsight.com/feed/",
    "ISW":                         "https://www.understandingwar.org/feed",

    # Priority 3 — Reddit
    "Reddit r/worldnews":          "https://www.reddit.com/r/worldnews/.rss",
    "Reddit r/geopolitics":        "https://www.reddit.com/r/geopolitics/.rss",
    "Reddit r/iran":               "https://www.reddit.com/r/iran/.rss",
    "Reddit r/energy":             "https://www.reddit.com/r/energy/.rss",

    # Priority 4 — Financial
    "MarketWatch":                 "https://feeds.marketwatch.com/marketwatch/topstories",
    "Seeking Alpha Oil&Gas":       "https://seekingalpha.com/feed/tag/oil-gas",

    # Priority 5 — Think tanks
    "RAND":                        "https://www.rand.org/feed.xml",
    "CSIS":                        "https://www.csis.org/feed",
    "Carnegie Endowment":          "https://carnegieendowment.org/rss/solr/?fa=pubs",
    "Brookings":                   "https://www.brookings.edu/feed/",
}


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
        "has_content": False, "has_tags": False,
        "has_source": False, "error": None,
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
            if entry.get("source"):   r["has_source"]  = True
            if is_relevant(entry):
                r["relevant"].append({
                    "title":     entry.get("title", "(no title)").strip(),
                    "published": entry.get("published", entry.get("updated", "?")),
                    "summary":   clean(entry.get("summary", "")),
                    "link":      entry.get("link", ""),
                    "has_body":  bool(entry.get("content")),
                    "source":    entry.get("source", {}).get("title", ""),
                })
    except Exception as e:
        r["error"] = str(e)
    r["fields"] = sorted(r["fields"])
    return r


def print_result(r: dict) -> None:
    status = f"HTTP {r['status']}" if r["status"] else f"ERROR: {r['error']}"
    print(f"\n{'='*68}")
    print(f"  {r['name']}")
    print(f"  {r['url'][:75]}")
    print(f"  {status}  |  Total: {r['total']}  |  Relevant: {len(r['relevant'])}")

    if r["error"] and not r["status"]:
        return
    if r["total"] == 0:
        return

    key = {"title", "summary", "content", "published", "updated", "tags", "author", "source"}
    print(f"  Present: {sorted(key & set(r['fields']))}")
    print(f"  Summary: {r['has_summary']}  |  Body: {r['has_content']}  |  Tags: {r['has_tags']}  |  Source field: {r['has_source']}")

    if not r["relevant"]:
        print("  [no relevant entries]")
        return

    for i, a in enumerate(r["relevant"][:4]):
        src = f"[{a['source']}] " if a["source"] else ""
        print(f"\n  [{i+1}] {a['published'][:25]}")
        print(f"       {src}{a['title'][:80]}")
        if a["summary"] and a["summary"][:60] != a["title"][:60]:
            print(f"       {a['summary'][:110]}")


if __name__ == "__main__":
    print(f"Additional Feeds Probe  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Feeds: {len(FEEDS)}")

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
        body   = "FULL-BODY" if r["has_content"] else "summary"
        print(f"  {r['name']:<30}  {status:<12}  total={r['total']:<4}  rel={len(r['relevant']):<4}  {body}")

    print("\nDone.")
