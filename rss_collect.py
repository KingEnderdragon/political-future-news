"""
KapturFlow RSS collector — run manually or on a scheduler, for a given
subject (see subjects.py). Each run fetches all of that subject's active
feeds, filters for relevance, deduplicates against previously seen
URLs/article fingerprints, and appends new items to that subject's running
log.

Usage: python rss_collect.py [subject_slug]   (defaults to "kaptur")
"""

import feedparser
import hashlib
import requests
import json
import re
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import subjects

HERE = Path(__file__).parent
KEYS_FILE = HERE / "keys.env"

NEWSAPI_URL = "https://newsapi.org/v2/everything"
MAX_WORKERS = 12
REQUEST_TIMEOUT = (4, 12)
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 MediaFlow/1.0"}

# Low-quality sources to exclude from NewsAPI results
NEWSAPI_BLOCKLIST = {
    "freerepublic.com", "naturalnews.com", "breitbart.com",
    "infowars.com", "zerohedge.com", "sputnikglobe.com",
}

# General Toledo/Ohio local feeds carry lots of unrelated sports/weather/crime
# noise that happens to share a dateline; nothing here matches KEYWORDS anyway
# unless the subject's name/keywords are present, so no exclude list needed.
EXCLUDE_RE = re.compile(r"(?!x)x")  # never matches

# msn.com syndication pages (esp. the /vi-AA... video-card format) are a
# JS-only shell with no server-rendered content and no recoverable link back
# to the original publisher — they show blank for most visitors. Drop them
# rather than store a link that won't actually work.
UNRELIABLE_LINK_DOMAINS = {"msn.com"}


def is_unreliable_link(url: str) -> bool:
    domain = urlparse(url or "").netloc.lower().removeprefix("www.")
    return domain in UNRELIABLE_LINK_DOMAINS


def load_env_key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name].strip()
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name):
                return line.split("=", 1)[1].strip()
    return ""


def build_keyword_re(keywords: list[str]) -> re.Pattern:
    return re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)


def is_relevant(entry: dict, keyword_re: re.Pattern) -> bool:
    text = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        " ".join(t.get("term", "") for t in entry.get("tags", [])),
    ])
    if EXCLUDE_RE.search(text):
        return False
    return bool(keyword_re.search(text))


def load_seen(state_file: Path) -> set:
    if state_file.exists():
        seen = set(json.loads(state_file.read_text(encoding="utf-8")))
        for item in list(seen):
            if item.startswith("article:"):
                continue
            canonical = canonical_url(item)
            if canonical:
                seen.add(f"article:url:{canonical}")
        return seen
    return set()


def save_seen(state_file: Path, seen: set) -> None:
    state_file.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


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


def decode_google_news_url(gnews_url: str) -> str:
    """Google News RSS links are a JS-only interstitial (HTTP 200, no
    redirect) that won't resolve in non-JS or restrictive in-app browsers.
    This replicates the reverse-engineered decode flow: pull the signed
    article id/timestamp/signature off the interstitial page, then ask
    Google's internal batchexecute endpoint for the real URL. Returns the
    original link unchanged if any step fails."""
    m = re.search(r"/articles/([^?]+)", gnews_url)
    if not m:
        return gnews_url
    article_id = m.group(1)
    try:
        time.sleep(0.3)  # light throttle — bursts of these have triggered rate limiting
        page = requests.get(gnews_url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT).text
        sg = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not sg or not ts:
            return gnews_url
        payload = [
            "Fbv4je",
            json.dumps([
                "garturlreq",
                [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                  None, None, None, None, None, 0, 1],
                 "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                article_id, ts.group(1), sg.group(1),
            ]),
        ]
        resp = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**HTTP_HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={"f.req": json.dumps([[payload]])},
            timeout=REQUEST_TIMEOUT,
        )
        body = resp.text.split("\n", 1)[1] if resp.text.startswith(")]}'") else resp.text
        outer = json.loads(body)
        inner = json.loads(outer[0][2])
        real_url = inner[1]
        return real_url if isinstance(real_url, str) and real_url.startswith("http") else gnews_url
    except Exception:
        return gnews_url


def resolve_article_link(raw_url: str, decode_google_news: bool = True) -> str:
    """Unwraps Bing News' apiclick.aspx tracking redirect and, optionally,
    Google News' interstitial link to their real article URLs. Those
    redirect links don't reliably resolve when opened directly (no
    session/referrer, or require JS), so this must run before a link is
    stored anywhere it might be clicked, not just at fingerprinting time."""
    parsed = urlparse(raw_url or "")
    if parsed.netloc.lower().endswith("bing.com") and parsed.path.lower().endswith("/news/apiclick.aspx"):
        target = parse_qs(parsed.query).get("url", [""])[0]
        if target:
            return target
    if decode_google_news and parsed.netloc.lower().endswith("news.google.com"):
        return decode_google_news_url(raw_url)
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


def fetch_all_feeds(feeds: dict[str, str]) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_feed, source, url): source
            for source, url in feeds.items()
        }
        for future in as_completed(futures):
            source, entries, error = future.result()
            if error:
                print(f"  [WARN] {source}: {error}")
            results[source] = entries
    return results


def fetch_newsapi(seen: set, queries: list[str], keyword_re: re.Pattern) -> list[dict]:
    items = []
    api_key = load_env_key("NEWSAPI_KEY")
    if not api_key or not queries:
        return items
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    responses: dict[str, bytes | None] = {}

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(queries))) as executor:
        futures = {}
        for query in queries:
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

    for query in queries:
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
            if not keyword_re.search(title + " " + desc):
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


def fetch_new(seen: set, subject: dict) -> list[dict]:
    feeds = subject["feeds"]
    keyword_re = build_keyword_re(subject["keywords"])

    new_items = []
    feed_results = fetch_all_feeds(feeds)
    for source, url in feeds.items():
        for entry in feed_results.get(source, []):
            raw_link = entry.get("link", "")
            title = entry.get("title", "(no title)").strip()
            item_source = article_source(entry, source)
            # Cheap checks first, on the raw (undecoded) link — canonical_url()
            # decodes internally for fingerprinting, so dedup is still accurate.
            # Only pay for the Google News/Bing decode (2 HTTP round-trips) once
            # an entry has actually cleared relevance + not-already-seen, since
            # most entries on any given run are duplicates from prior runs.
            if not raw_link or is_seen(seen, item_source, title, raw_link):
                continue
            if not is_relevant(entry, keyword_re):
                continue
            link = resolve_article_link(raw_link)
            if is_unreliable_link(link):
                continue
            new_items.append({
                "source":    item_source,  # real outlet when the feed provides one, else the feed's own label
                "feed":      source,
                "title":     title,
                "author":    (entry.get("author") or "").strip(),
                "summary":   clean_summary(entry.get("summary", "")),
                "published": entry.get("published", entry.get("updated", "unknown")),
                "link":      link,
                "fetched":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            })
            mark_seen(seen, item_source, title, link)

    new_items += fetch_newsapi(seen, subject.get("newsapi_queries", []), keyword_re)

    # sort oldest-first so the log reads chronologically
    new_items.sort(key=lambda x: x["published"])
    return new_items


def append_to_log(log_file: Path, subject_name: str, items: list[dict]) -> None:
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

    with open(log_file, "a", encoding="utf-8") as f:
        if not log_file.exists() or log_file.stat().st_size == 0:
            f.write(f"KAPTURFLOW - {subject_name} Running News Log\n")
            f.write("=" * 68 + "\n")
        f.writelines(lines)


def run(subject_slug: str = "kaptur"):
    subject = subjects.get_subject(subject_slug)
    paths = subjects.paths_for(subject_slug)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"MediaFlow collect [{subject['name']}] — {now}")

    started = time.perf_counter()

    seen = load_seen(paths["seen"])
    seen_before = len(seen)

    new_items = fetch_new(seen, subject)

    if new_items:
        for item in new_items:
            item["id"] = make_item_id(item["link"], item["title"], item["source"])

        append_to_log(paths["log"], subject["name"], new_items)
        save_seen(paths["seen"], seen)

        existing: list[dict] = []
        if paths["items"].exists():
            existing = json.loads(paths["items"].read_text(encoding="utf-8"))
        existing_ids = {i["id"] for i in existing}
        truly_new = [i for i in new_items if i["id"] not in existing_ids]
        if truly_new:
            existing.extend(truly_new)
            paths["items"].write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        elapsed = time.perf_counter() - started
        print(f"  {len(new_items)} new items logged in {elapsed:.1f}s  (seen total: {len(seen)})")
        for item in new_items:
            print(f"  + [{item['source']}] {item['title'][:70]}")
    else:
        elapsed = time.perf_counter() - started
        print(f"  No new relevant items in {elapsed:.1f}s  (seen total: {seen_before})")

    print(f"  Log: {paths['log']}")


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "kaptur"
    run(slug)
