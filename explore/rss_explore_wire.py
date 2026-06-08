"""
Wire service probe — testing all accessible wire/news API options.
Covers: alternative Reuters/AP RSS paths, no-key free APIs,
and assessment of how much wire content we already have via aggregators.
"""

import feedparser
import requests
import re
from datetime import datetime, timezone

KEYWORDS = [
    "iran", "hormuz", "irgc", "tehran", "strait", "sanctions",
    "nuclear", "missile", "oil", "crude", "tanker", "hezbollah",
    "ceasefire", "gulf", "barrel", "opec", "brent", "wti",
]
KEYWORD_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)


def is_relevant(entry):
    text = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(t.get("term", "") for t in entry.get("tags", [])),
    ])
    return bool(KEYWORD_RE.search(text))


def clean(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()[:180]


def probe_rss(name, url):
    f = feedparser.parse(url)
    status = f.get("status", "no-status")
    entries = f.get("entries", [])
    rel = [e for e in entries if is_relevant(e)]
    fields = set()
    for e in entries:
        fields.update(e.keys())
    key = {"title", "summary", "content", "published", "updated", "author", "source"}
    return {
        "name": name, "url": url, "status": status,
        "total": len(entries), "relevant": rel,
        "fields": sorted(key & fields),
        "has_body": any(e.get("content") for e in entries),
        "error": None,
    }


def print_result(r):
    status = f"HTTP {r['status']}" if r["status"] else f"ERROR: {r.get('error')}"
    print(f"\n{'='*68}")
    print(f"  {r['name']}")
    print(f"  {r['url'][:75]}")
    print(f"  {status}  |  Total: {r['total']}  |  Relevant: {len(r['relevant'])}")
    if r["total"] == 0:
        return
    print(f"  Fields: {r['fields']}  |  Full body: {r['has_body']}")
    for i, a in enumerate(r["relevant"][:4]):
        src = a.get("source", {}).get("title", "")
        src_str = f"[{src}] " if src else ""
        print(f"  [{i+1}] {a.get('published', a.get('updated','?'))[:22]}")
        print(f"       {src_str}{a.get('title','')[:80]}")
        s = clean(a.get("summary", ""))
        if s and s[:50] != a.get("title","")[:50]:
            print(f"       {s[:110]}")


# ── SECTION 1: Alternative Reuters/AP RSS paths ──────────────────────────────
REUTERS_AP = {
    "Reuters /rssFeed/topNews":     "https://www.reuters.com/rssFeed/topNews",
    "Reuters /rssFeed/worldNews":   "https://www.reuters.com/rssFeed/worldNews",
    "Reuters new path /rss/world":  "https://feeds.reuters.com/reuters/world",
    "AP apnews.com/rss/world":      "https://apnews.com/rss/world",
    "AP apnews.com/rss/topnews":    "https://apnews.com/rss/topnews",
    "AP hub/world-news":            "https://apnews.com/hub/world-news?rss=true",
}

# ── SECTION 2: No-key free wire APIs ─────────────────────────────────────────
# GNews API (different from Google News RSS) — free tier 100/day
GNEWS_API = "https://gnews.io/api/v4/search?q=iran+hormuz&lang=en&country=any&max=10&apikey=free"

# Mediastack — free tier 500/month
MEDIASTACK = "http://api.mediastack.com/v1/news?access_key=free&keywords=iran+hormuz&languages=en"

# TheNewsAPI — free tier
THENEWSAPI = "https://api.thenewsapi.com/v1/news/all?search=iran+hormuz&language=en&api_token=free"

# Currents API — free
CURRENTS = "https://api.currentsapi.services/v1/search?keywords=iran+hormuz&language=en&apiKey=free"

# ── SECTION 3: Wire content already in our feed via aggregators ───────────────
# Check what wire sources are appearing in our existing Google News + Bing feeds
WIRE_CHECK = {
    "GNews iran strait oil":    "https://news.google.com/rss/search?q=iran+strait+oil&hl=en-US&gl=US&ceid=US:en",
    "GNews hormuz tanker":      "https://news.google.com/rss/search?q=hormuz+tanker&hl=en-US&gl=US&ceid=US:en",
}
WIRE_SOURCES = ["Reuters", "AP", "Associated Press", "Bloomberg", "Agence France",
                "AFP", "Dow Jones", "MarketWatch", "Financial Times", "WSJ",
                "Wall Street Journal"]


if __name__ == "__main__":
    print(f"Wire Service Probe  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("="*68)

    # Section 1
    print("\n\n--- SECTION 1: Reuters / AP alternative RSS paths ---")
    for name, url in REUTERS_AP.items():
        r = probe_rss(name, url)
        print_result(r)

    # Section 2 — test whether no-key calls are accepted or rejected
    print("\n\n--- SECTION 2: No-key free wire APIs (expect rejection, checking error type) ---")
    for name, url in [("GNews API (no key)", GNEWS_API),
                      ("Mediastack (no key)", MEDIASTACK),
                      ("TheNewsAPI (no key)", THENEWSAPI),
                      ("Currents (no key)", CURRENTS)]:
        try:
            r = requests.get(url, timeout=10)
            print(f"\n  {name}")
            print(f"  HTTP {r.status_code}  content-type: {r.headers.get('content-type','?')[:50]}")
            if r.status_code == 200:
                data = r.json()
                print(f"  Response keys: {list(data.keys())[:8]}")
                articles = data.get("articles", data.get("data", data.get("news", [])))
                print(f"  Articles returned: {len(articles)}")
                if articles:
                    print(f"  First article keys: {list(articles[0].keys())[:8]}")
                    print(f"  First title: {articles[0].get('title','?')[:70]}")
            else:
                print(f"  Body preview: {r.text[:200]}")
        except Exception as e:
            print(f"\n  {name}  ERROR: {e}")

    # Section 3 — wire source audit of existing feeds
    print("\n\n--- SECTION 3: Wire sources already in our Google News / Bing feeds ---")
    wire_found = {}
    for name, url in WIRE_CHECK.items():
        f = feedparser.parse(url)
        entries = f.get("entries", [])
        for e in entries:
            src = e.get("source", {}).get("title", "")
            for w in WIRE_SOURCES:
                if w.lower() in src.lower():
                    wire_found[src] = wire_found.get(src, 0) + 1
        print(f"  {name}: {len(entries)} entries")

    print(f"\n  Wire sources detected across Google News queries:")
    for src, count in sorted(wire_found.items(), key=lambda x: -x[1]):
        print(f"    {src:<30}  {count} articles")

    print("\n\nDone.")
