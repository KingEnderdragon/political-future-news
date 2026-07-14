"""
KapturFlow RSS collector — run manually or on a scheduler.
Tracks Rep. Marcy Kaptur (D-OH-9). Each run fetches all active feeds,
filters for relevance, deduplicates against previously seen URLs/article
fingerprints, and appends new items to the running log.
"""

import feedparser
import hashlib
import requests
import json
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

# ── paths ────────────────────────────────────────────────────────────────────
HERE        = Path(__file__).parent
DATA_DIR    = Path(os.environ.get("DATA_DIR", HERE))
LOG_FILE    = DATA_DIR / "mediaflow_log.txt"
STATE_FILE  = DATA_DIR / "mediaflow_seen.json"   # persists seen URLs/fingerprints
ITEMS_FILE  = DATA_DIR / "mediaflow_items.json"  # structured item store for classifier
KEYS_FILE   = HERE / "keys.env"

# ── active feeds ─────────────────────────────────────────────────────────────
FEEDS = {
    # Official
    "Kaptur House.gov":     "https://kaptur.house.gov/rss.xml",
    # Local Ohio / district press
    "Toledo Blade":         "https://www.toledoblade.com/rss/",
    "WTOL 11 Toledo":       "https://www.wtol.com/feeds/syndication/rss/news",
    "Ohio Capital Journal": "https://ohiocapitaljournal.com/feed/",
    "Cleveland.com Politics": "https://www.cleveland.com/arc/outboundfeeds/rss/category/politics/",
    # Google News search queries
    "GNews: Marcy Kaptur":          "https://news.google.com/rss/search?q=%22Marcy+Kaptur%22&hl=en-US&gl=US&ceid=US:en",
    "GNews: Kaptur Ohio 9th":       "https://news.google.com/rss/search?q=Kaptur+%22Ohio%27s+9th%22&hl=en-US&gl=US&ceid=US:en",
    "GNews: Kaptur Toledo":         "https://news.google.com/rss/search?q=Kaptur+Toledo&hl=en-US&gl=US&ceid=US:en",
    "GNews: Kaptur committee":      "https://news.google.com/rss/search?q=Kaptur+committee+appropriations&hl=en-US&gl=US&ceid=US:en",
    "GNews: Kaptur bill":           "https://news.google.com/rss/search?q=Kaptur+bill+legislation&hl=en-US&gl=US&ceid=US:en",
    "GNews: Kaptur campaign":       "https://news.google.com/rss/search?q=Kaptur+campaign+election&hl=en-US&gl=US&ceid=US:en",
    "GNews: OH-9 congressional":    "https://news.google.com/rss/search?q=%22Ohio%27s+9th+congressional+district%22&hl=en-US&gl=US&ceid=US:en",
    # Bing News search queries
    "Bing: Marcy Kaptur":       "https://www.bing.com/news/search?q=%22Marcy+Kaptur%22&format=rss",
    "Bing: Kaptur Toledo":      "https://www.bing.com/news/search?q=Kaptur+Toledo&format=rss",
    "Bing: Kaptur Ohio 9th":    "https://www.bing.com/news/search?q=Kaptur+Ohio+9th+district&format=rss",
}

# ── NewsAPI config ───────────────────────────────────────────────────────────
OFFICIAL_PAGES: dict[str, str] = {}

OFFICIAL_LINK_RE: dict[str, "re.Pattern"] = {}

NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_QUERIES = [
    "Marcy Kaptur",
    "Kaptur Ohio 9th district",
    "Kaptur Toledo",
]

MAX_WORKERS = 12
REQUEST_TIMEOUT = (4, 12)
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 MediaFlow/1.0"}


def load_env_key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name):
                return line.split("=", 1)[1].strip()
    return ""

# Low-quality sources to exclude from NewsAPI results
NEWSAPI_BLOCKLIST = {
    "freerepublic.com", "naturalnews.com", "breitbart.com",
    "infowars.com", "zerohedge.com", "sputnikglobe.com",
}

# ── relevance filter ─────────────────────────────────────────────────────────
KEYWORDS = [
    "kaptur",
    "ohio's 9th",
    "ohio 9th",
    "9th congressional district",
    "oh-9",
    "oh 9th district",
]
KEYWORD_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.IGNORECASE)

# General Toledo/Ohio local feeds carry lots of unrelated sports/weather/crime
# noise that happens to share a dateline; nothing here matches KEYWORDS anyway
# unless "Kaptur" or the district name is present, so no exclude list needed.
EXCLUDE_RE = re.compile(r"(?!x)x")  # never matches


def is_relevant(entry: dict) -> bool:
    text = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(t.get("term", "") for t in entry.get("tags", [])),
    ])
    if EXCLUDE_RE.search(text):
        return False
    return bool(KEYWORD_RE.search(text))


def load_seen() -> set:
    if STATE_FILE.exists():
        seen = set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        for item in list(seen):
            if item.startswith("article:"):
                continue
            canonical = canonical_url(item)
            if canonical:
                seen.add(f"article:url:{canonical}")
        return seen
    return set()


def save_seen(seen: set) -> None:
    STATE_FILE.write_text(
        json.dumps(sorted(seen), indent=2), encoding="utf-8"
    )


def clean_summary(raw: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:280]


def normalized_title(title: str, source: str = "") -> str:
    text = re.sub(r"<[^>]+>", " ", title or "")
    text = re.sub(r"\s+", " ", text).strip().lower()
    if source:
        source_text = re.escape(source.strip().lower())
        text = re.sub(rf"\s+[-|]\s+{source_text}$", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def make_item_id(link: str, title: str, source: str) -> str:
    canonical = canonical_url(link)
    key = canonical or f"{source.lower()}:{title.lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def resolve_article_link(raw_url: str) -> str:
    """Unwraps Bing News' apiclick.aspx tracking redirect to the real article
    URL. Those redirect links don't reliably resolve when opened directly
    (no session/referrer), so this must run before a link is stored anywhere
    it might be clicked, not just at fingerprinting time."""
    parsed = urlparse(raw_url or "")
    if parsed.netloc.lower().endswith("bing.com") and parsed.path.lower().endswith("/news/apiclick.aspx"):
        target = parse_qs(parsed.query).get("url", [""])[0]
        if target:
            return target
    return raw_url


def canonical_url(raw_url: str) -> str:
    raw_url = resolve_article_link(raw_url)
    parsed = urlparse(raw_url or "")
    if parsed.netloc.lower().endswith("news.google.com"):
        return ""
    domain = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path)
    keep_params = []
    for key, vals in parse_qs(parsed.query).items():
        if key.lower().startswith(("utm_", "fbclid", "gclid", "oc", "cmpid")):
            continue
        for val in vals:
            keep_params.append((key, val))
    query = ""
    if keep_params:
        query = "?" + "&".join(f"{k}={v}" for k, v in sorted(keep_params))
    return f"{domain}{path}{query}".lower()


def article_source(entry: dict, fallback: str) -> str:
    source = entry.get("source", {})
    if isinstance(source, dict):
        return source.get("title") or fallback
    return fallback


def article_keys(source: str, title: str, link: str) -> set[str]:
    keys = {link}
    canonical = canonical_url(link)
    if canonical:
        keys.add(f"article:url:{canonical}")
    title_key = normalized_title(title, source)
    if len(title_key) >= 35:
        keys.add(f"article:source-title:{source.lower()}:{title_key}")
        keys.add(f"article:title:{title_key}")
    return keys


def is_seen(seen: set, source: str, title: str, link: str) -> bool:
    return bool(article_keys(source, title, link) & seen)


def mark_seen(seen: set, source: str, title: str, link: str) -> None:
    seen.update(article_keys(source, title, link))


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._text).split())
        if title:
            self.links.append((title, urljoin(self.base_url, self._href)))
        self._href = None
        self._text = []


def fetch_url(source: str, url: str, params: dict | None = None) -> tuple[str, str, str, bytes | None]:
    try:
        r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return source, r.url, f"HTTP {r.status_code}", None
        return source, r.url, "", r.content
    except Exception as e:
        return source, url, str(e), None


def fetch_feed(source: str, url: str) -> tuple[str, list[dict], str]:
    source, _final_url, error, content = fetch_url(source, url)
    if error:
        return source, [], error
    feed = feedparser.parse(content)
    if feed.get("bozo_exception") and not feed.get("entries"):
        return source, [], str(feed["bozo_exception"])
    return source, list(feed.get("entries", [])), ""


def fetch_all_feeds() -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_feed, source, url): source
            for source, url in FEEDS.items()
        }
        for future in as_completed(futures):
            source, entries, error = future.result()
            if error:
                print(f"  [WARN] {source}: {error}")
            results[source] = entries
    return results


def fetch_official_pages(seen: set) -> list[dict]:
    items = []
    if not OFFICIAL_PAGES:
        return items
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pages: dict[str, tuple[str, bytes | None]] = {}

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(OFFICIAL_PAGES))) as executor:
        futures = {
            executor.submit(fetch_url, source, url): source
            for source, url in OFFICIAL_PAGES.items()
        }
        for future in as_completed(futures):
            source, final_url, error, content = future.result()
            if error:
                print(f"  [WARN] {source}: {error}")
            pages[source] = (final_url, content)

    for source in OFFICIAL_PAGES:
        final_url, content = pages.get(source, (OFFICIAL_PAGES[source], None))
        if not content:
            continue
        parser = LinkExtractor(final_url)
        parser.feed(content.decode("utf-8", errors="replace"))
        for title, link in parser.links:
            link_path = urlparse(link).path
            if not OFFICIAL_LINK_RE[source].search(link_path):
                continue
            if len(title) < 12 or is_seen(seen, source, title, link):
                continue
            if not is_relevant({"title": title, "summary": ""}):
                continue
            items.append({
                "source":    source,
                "title":     title.strip(),
                "summary":   "",
                "published": now,
                "link":      link,
                "fetched":   now,
            })
            mark_seen(seen, source, title, link)
    return items


def fetch_newsapi(seen: set) -> list[dict]:
    items = []
    api_key = load_env_key("NEWSAPI_KEY")
    if not api_key:
        print("  [WARN] NewsAPI skipped: NEWSAPI_KEY not found")
        return items
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    responses: dict[str, bytes | None] = {}

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(NEWSAPI_QUERIES))) as executor:
        futures = {}
        for query in NEWSAPI_QUERIES:
            params = {
                "q": query, "language": "en",
                "sortBy": "publishedAt", "pageSize": 20,
                "apiKey": api_key,
            }
            futures[executor.submit(fetch_url, f"NewsAPI '{query}'", NEWSAPI_URL, params)] = query
        for future in as_completed(futures):
            source, _final_url, error, content = future.result()
            query = futures[future]
            if error:
                print(f"  [WARN] {source}: {error}")
            responses[query] = content

    for query in NEWSAPI_QUERIES:
        content = responses.get(query)
        if not content:
            continue
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception as e:
            print(f"  [WARN] NewsAPI '{query}': {e}")
            continue
        for a in payload.get("articles", []):
            url = a.get("url", "")
            title = a.get("title", "") or ""
            desc  = a.get("description", "") or ""
            source = f"NewsAPI/{(a.get('source') or {}).get('name','?')}"
            if not url or is_seen(seen, source, title, url):
                continue
            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if any(domain == b or domain.endswith("." + b) for b in NEWSAPI_BLOCKLIST):
                continue
            if not KEYWORD_RE.search(title + " " + desc):
                continue
            items.append({
                "source":    source,
                "title":     title.strip(),
                "summary":   clean_summary(desc),
                "published": a.get("publishedAt", "unknown"),
                "link":      url,
                "fetched":   now,
            })
            mark_seen(seen, source, title, url)
    return items


def fetch_new(seen: set) -> list[dict]:
    new_items = []
    feeds = fetch_all_feeds()
    for source, url in FEEDS.items():
        for entry in feeds.get(source, []):
            link = resolve_article_link(entry.get("link", ""))
            title = entry.get("title", "(no title)").strip()
            item_source = article_source(entry, source)
            if not link or is_seen(seen, item_source, title, link):
                continue
            if not is_relevant(entry):
                continue
            new_items.append({
                "source":    source,
                "title":     title,
                "summary":   clean_summary(entry.get("summary", "")),
                "published": entry.get("published", entry.get("updated", "unknown")),
                "link":      link,
                "fetched":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            })
            mark_seen(seen, item_source, title, link)

    new_items += fetch_official_pages(seen)
    new_items += fetch_newsapi(seen)

    # sort oldest-first so the log reads chronologically
    new_items.sort(key=lambda x: x["published"])
    return new_items


def append_to_log(items: list[dict]) -> None:
    lines = []
    for item in items:
        lines.append(
            f"\n[{item['fetched']}]  {item['source'].upper()}\n"
            f"{item['title']}\n"
        )
        if item["summary"] and item["summary"] != item["title"]:
            lines.append(f"{item['summary']}\n")
        lines.append(f"{item['link']}\n")
        lines.append("-" * 68 + "\n")

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
            f.write("KAPTURFLOW - Marcy Kaptur (OH-9) Running News Log\n")
            f.write("=" * 68 + "\n")
        f.writelines(lines)


def run():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"MediaFlow collect — {now}")

    started = time.perf_counter()

    seen     = load_seen()
    seen_before = len(seen)

    new_items = fetch_new(seen)

    if new_items:
        # assign stable IDs
        for item in new_items:
            item["id"] = make_item_id(item["link"], item["title"], item["source"])

        append_to_log(new_items)
        save_seen(seen)

        # append to structured items store (skip any ID already present)
        existing: list[dict] = []
        if ITEMS_FILE.exists():
            existing = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
        existing_ids = {i["id"] for i in existing}
        truly_new = [i for i in new_items if i["id"] not in existing_ids]
        if truly_new:
            existing.extend(truly_new)
            ITEMS_FILE.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        elapsed = time.perf_counter() - started
        print(f"  {len(new_items)} new items logged in {elapsed:.1f}s  (seen total: {len(seen)})")
        for item in new_items:
            print(f"  + [{item['source']}] {item['title'][:70]}")
    else:
        elapsed = time.perf_counter() - started
        print(f"  No new relevant items in {elapsed:.1f}s  (seen total: {seen_before})")

    print(f"  Log: {LOG_FILE}")


if __name__ == "__main__":
    run()
