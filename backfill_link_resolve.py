"""
One-off backfill: resolves every Google News / Bing News redirect link
already stored for a subject's items/classified/digest files to its real
article URL, in parallel. Safe to rerun — already-resolved (non-redirect)
links are left untouched.

Usage: python backfill_link_resolve.py [subject_slug]   (defaults to "kaptur")
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import rss_collect as rc
import subjects

MAX_WORKERS = 10


def needs_resolve(url: str) -> bool:
    parsed = urlparse(url or "")
    netloc = parsed.netloc.lower()
    if netloc.endswith("news.google.com"):
        return True
    if netloc.endswith("bing.com") and parsed.path.lower().endswith("/news/apiclick.aspx"):
        return True
    return False


def collect_links(*file_paths: Path) -> set[str]:
    links: set[str] = set()
    for path in file_paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                link = item.get("link", "")
                if needs_resolve(link):
                    links.add(link)
        elif isinstance(data, dict):
            for window in data.values():
                for arc in (window.get("arcs") or {}).values():
                    for p in arc.get("talking_points", []):
                        link = p.get("link", "")
                        if needs_resolve(link):
                            links.add(link)
    return links


def resolve_all(links: set[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(rc.resolve_article_link, link): link for link in links}
        total = len(futures)
        done = 0
        for future in as_completed(futures):
            link = futures[future]
            try:
                resolved[link] = future.result()
            except Exception as e:
                print(f"  [WARN] failed to resolve {link[:80]}: {e}")
                resolved[link] = link
            done += 1
            if done % 10 == 0 or done == total:
                print(f"  {done}/{total} resolved")
    return resolved


def apply_to_items_file(path: Path, resolved: dict[str, str]) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    fixed = 0
    for item in data:
        link = item.get("link", "")
        if link in resolved and resolved[link] != link:
            item["link"] = resolved[link]
            fixed += 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return fixed


def apply_to_digest_file(path: Path, resolved: dict[str, str]) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    fixed = 0
    for window in data.values():
        for arc in (window.get("arcs") or {}).values():
            for p in arc.get("talking_points", []):
                link = p.get("link", "")
                if link in resolved and resolved[link] != link:
                    p["link"] = resolved[link]
                    fixed += 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return fixed


def main(subject_slug: str = "kaptur") -> None:
    paths = subjects.paths_for(subject_slug)
    items_file, classified_file, digest_file = paths["items"], paths["classified"], paths["digest"]

    links = collect_links(items_file, classified_file, digest_file)
    print(f"Found {len(links)} redirect links to resolve.")
    if not links:
        return

    resolved = resolve_all(links)
    still_unresolved = sum(1 for k, v in resolved.items() if k == v)
    print(f"Resolved {len(resolved) - still_unresolved}/{len(resolved)} ({still_unresolved} failed, left unchanged).")

    fixed_items = apply_to_items_file(items_file, resolved)
    fixed_classified = apply_to_items_file(classified_file, resolved)
    fixed_digest = apply_to_digest_file(digest_file, resolved)
    print(f"Patched: items={fixed_items} classified={fixed_classified} digest_talking_points={fixed_digest}")


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "kaptur"
    main(slug)
