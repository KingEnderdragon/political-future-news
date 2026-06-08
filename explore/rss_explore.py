"""
Exploratory script: probe RSS feeds for Iran/Hormuz coverage.
Goal: assess field richness, update frequency, relevance signal,
and deduplication characteristics vs GDELT.
"""

import feedparser
import re
from datetime import datetime, timezone
from collections import defaultdict

FEEDS = {
    "Reuters World":       "https://feeds.reuters.com/reuters/worldNews",
    "Reuters Top News":    "https://feeds.reuters.com/reuters/topNews",
    "AP Top News":         "https://apnews.com/rss",
    "Al Jazeera":          "https://www.aljazeera.com/xml/rss/all.xml",
    "Middle East Eye":     "https://www.middleeasteye.net/rss",
    "BBC World":           "http://feeds.bbci.co.uk/news/world/rss.xml",
    "Guardian World":      "https://www.theguardian.com/world/rss",
    "France24 Middle East":"https://www.france24.com/en/middle-east/rss",
}

# keywords for relevance filtering — any match = relevant
KEYWORDS = [
    "iran", "hormuz", "irgc", "tehran", "persian gulf",
    "strait", "tanker", "khamenei", "rouhani", "pezeshkian",
    "nuclear deal", "jcpoa", "enrichment", "sanctions",
    "arabian sea", "gulf of oman",
]

KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)


def is_relevant(entry: dict) -> bool:
    text = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        entry.get("tags_flat", ""),
    ])
    return bool(KEYWORD_RE.search(text))


def parse_feed(name: str, url: str) -> dict:
    result = {
        "name":        name,
        "url":         url,
        "status":      None,
        "total":       0,
        "relevant":    [],
        "fields":      set(),
        "has_summary": False,
        "has_content": False,
        "has_tags":    False,
        "error":       None,
    }
    try:
        feed = feedparser.parse(url)
        result["status"] = feed.get("status", "no-status")
        entries = feed.get("entries", [])
        result["total"] = len(entries)

        for entry in entries:
            # collect field names across all entries
            result["fields"].update(entry.keys())

            if entry.get("summary"):
                result["has_summary"] = True
            if entry.get("content"):
                result["has_content"] = True
            if entry.get("tags"):
                result["has_tags"] = True

            # flatten tags for keyword search
            tags_flat = " ".join(t.get("term", "") for t in entry.get("tags", []))
            entry["tags_flat"] = tags_flat

            if is_relevant(entry):
                result["relevant"].append({
                    "title":     entry.get("title", "(no title)"),
                    "published": entry.get("published", entry.get("updated", "?")),
                    "link":      entry.get("link", ""),
                    "domain":    _domain(entry.get("link", "")),
                    "summary":   (entry.get("summary", "") or "")[:200].strip(),
                    "has_body":  bool(entry.get("content")),
                    "tags":      tags_flat[:80],
                })

    except Exception as e:
        result["error"] = str(e)

    result["fields"] = sorted(result["fields"])
    return result


def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url)
    return m.group(1) if m else "?"


def print_result(r: dict) -> None:
    status = r["status"]
    err    = r["error"]
    total  = r["total"]
    rel    = r["relevant"]

    status_str = f"HTTP {status}" if status else f"ERROR: {err}"
    print(f"\n{'─'*68}")
    print(f"  {r['name']}")
    print(f"  {r['url']}")
    print(f"  Status: {status_str}  |  Total entries: {total}  |  Relevant: {len(rel)}")

    if err and not status:
        return

    # field inventory
    key_fields = {"title", "summary", "content", "published", "updated", "tags", "author"}
    present    = key_fields & set(r["fields"])
    absent     = key_fields - set(r["fields"])
    print(f"  Key fields present: {sorted(present)}")
    print(f"  Key fields absent:  {sorted(absent)}")
    print(f"  Has summary: {r['has_summary']}  |  Has full content: {r['has_content']}  |  Has tags: {r['has_tags']}")

    if not rel:
        print("  [no relevant entries]")
        return

    print(f"\n  Relevant entries ({len(rel)}):")
    for i, art in enumerate(rel[:5]):
        print(f"\n  [{i+1}] {art['published'][:25]}")
        print(f"       {art['title'][:85]}")
        if art["summary"]:
            print(f"       Summary: {art['summary'][:120]}")
        if art["tags"]:
            print(f"       Tags: {art['tags']}")
        print(f"       {art['link'][:80]}")
        print(f"       Full body in feed: {art['has_body']}")


def probe_dedup(results: list) -> None:
    print(f"\n\n{'='*68}")
    print("DEDUPLICATION PROBE — cross-feed title overlap")
    print(f"{'='*68}")

    # collect all relevant titles across all feeds
    title_map = defaultdict(list)
    for r in results:
        for art in r["relevant"]:
            key = art["title"][:55].strip().lower()
            title_map[key].append(r["name"])

    cross_feed = {k: v for k, v in title_map.items() if len(v) > 1}
    all_relevant = sum(len(r["relevant"]) for r in results)

    print(f"  Total relevant articles across all feeds: {all_relevant}")
    print(f"  Unique title clusters: {len(title_map)}")
    print(f"  Cross-feed duplicates: {len(cross_feed)}")

    if cross_feed:
        print("\n  Cross-feed duplicate clusters:")
        for title, feeds in list(cross_feed.items())[:8]:
            print(f"    '{title[:52]}...'  ->  {feeds}")


def probe_freshness(results: list) -> None:
    print(f"\n\n{'='*68}")
    print("FRESHNESS PROBE — most recent entry per feed")
    print(f"{'='*68}")
    for r in results:
        if r["total"] == 0 or r["error"]:
            print(f"  {r['name']:<25} — no data")
            continue
        # published date of first (most recent) entry would need re-parse
        # use the relevant entries if any, else skip
        if r["relevant"]:
            latest = r["relevant"][0]["published"]
            print(f"  {r['name']:<25} — latest relevant: {latest[:30]}")
        else:
            print(f"  {r['name']:<25} — no relevant entries (total feed entries: {r['total']})")


if __name__ == "__main__":
    print("RSS Feed Exploratory Probe")
    print(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Feeds: {len(FEEDS)}  |  Keywords: {len(KEYWORDS)}")
    print("No rate limiting needed — RSS has no API quota.")

    results = []
    for name, url in FEEDS.items():
        r = parse_feed(name, url)
        results.append(r)
        print_result(r)

    probe_dedup(results)
    probe_freshness(results)

    print("\n\nDone.")
