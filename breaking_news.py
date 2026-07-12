"""
Breaking News source/parser — reads Hormuz Flow Watch reports out of the
plain-text export of the Hormuz Flow Watch Reports Google Doc.
No Streamlit dependency; invoked by breaking_news_view.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

DEFAULT_DOC_ID = "1m_t-TwVt7LzHaX1KitPpNrSxFqI-OfnbqwEa4cvyEGg"

KNOWN_LABELS = [
    "Report ID:",
    "Timestamp:",
    "Title:",
    "Alert judgment:",
    "Source links:",
    "Physical-balance facts:",
    "Market-pricing facts:",
    "Interpretation:",
    "Watch items:",
]

REQUIRED_LABELS = [
    "Physical-balance facts:",
    "Market-pricing facts:",
    "Interpretation:",
]

# The doc's plain-text export inconsistently prefixes structural lines (headings,
# labels, bullets) with markdown ATX "#" markers depending on how that line was
# styled in the source doc — sometimes every line in a report, sometimes none.
# Stripped up front in parse_reports() so the regexes below never need to care.
ATX_PREFIX_RE = re.compile(r"(?m)^#{1,6}[ \t]*")

HEADING_RE = re.compile(
    r"^(HFW-[\w-]+)\s*—\s*(.+?)\s*—\s*"
    r"(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\s+[A-Za-z]{2,5})\s*$",
    re.MULTILINE,
)

_LABEL_ALTERNATION = "|".join(re.escape(label) for label in KNOWN_LABELS)

# Matches a known label, OR a generic "Title-ish Words:" line (never a bullet
# line, since those start with a marker) — the generic branch exists purely so
# that a future/unforeseen section added to the doc still ends the preceding
# known section instead of bleeding into it. Only known-label matches
# participate in required/duplicate-label checks below.
LABEL_RE = re.compile(
    rf"^(?:({_LABEL_ALTERNATION})|([A-Z][A-Za-z]+(?:[ '/-][A-Za-z]+){{0,5}}:))\s*(.*)$",
    re.MULTILINE,
)

BULLET_RE = re.compile(r"^\s*[•\-\*]\s*")


@dataclass
class BreakingNewsReport:
    report_id: str
    headline: str
    timestamp_display: str
    physical_facts: list[str] = field(default_factory=list)
    market_facts: list[str] = field(default_factory=list)
    interpretation: str = ""


@dataclass
class BreakingNewsError:
    report_id: str | None
    kind: str  # "missing_section" | "duplicate_section" | "duplicate_id"
    detail: str


class BreakingNewsAccessError(Exception):
    """Raised when the document can't be reached/read as expected (not a parse issue)."""


def build_export_url(doc_id: str = DEFAULT_DOC_ID) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"


def fetch_doc_text(url: str, timeout: float = 10.0) -> str:
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
    except requests.exceptions.RequestException as e:
        raise BreakingNewsAccessError(f"request failed: {e}") from e

    if resp.status_code != 200:
        raise BreakingNewsAccessError(f"HTTP {resp.status_code}")

    host = urlparse(resp.url).netloc
    if host != "docs.google.com":
        raise BreakingNewsAccessError(f"redirected to {host} (document may not be public)")

    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type:
        raise BreakingNewsAccessError("received HTML instead of plain-text export")

    # requests defaults an undeclared-charset text/plain response to Latin-1,
    # which mojibakes this doc's em dashes and bullet points — decode as UTF-8 explicitly.
    return resp.content.decode("utf-8", errors="replace")


def _bullets_from_section(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    bullets = [BULLET_RE.sub("", line).strip() for line in lines if line.strip()]
    return [b for b in bullets if b]


def _parse_block(report_id: str, headline: str, timestamp_display: str, block: str) -> tuple[BreakingNewsReport | None, BreakingNewsError | None]:
    matches = list(LABEL_RE.finditer(block))

    # group(1) is a known label, group(2) is a generic "unrecognized label-shaped
    # line" that still ends the preceding section — only known labels count
    # toward required/duplicate checks.
    known_counts: dict[str, int] = {}
    for m in matches:
        label = m.group(1)
        if label:
            known_counts[label] = known_counts.get(label, 0) + 1

    duplicated = [label for label, count in known_counts.items() if count > 1]
    if duplicated:
        return None, BreakingNewsError(
            report_id=report_id,
            kind="duplicate_section",
            detail=f"duplicate label(s): {', '.join(sorted(duplicated))}",
        )

    missing_required = [label for label in REQUIRED_LABELS if label not in known_counts]
    if missing_required:
        return None, BreakingNewsError(
            report_id=report_id,
            kind="missing_section",
            detail=f"missing required label(s): {', '.join(missing_required)}",
        )

    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1)
        if not label:
            continue  # unrecognized label-shaped line: only serves as a boundary
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        # include any inline content on the label's own line, plus everything after
        inline = m.group(3)
        content = (inline + "\n" + block[start:end]) if inline else block[start:end]
        sections[label] = content

    report = BreakingNewsReport(
        report_id=report_id,
        headline=headline,
        timestamp_display=timestamp_display,
        physical_facts=_bullets_from_section(sections["Physical-balance facts:"]),
        market_facts=_bullets_from_section(sections["Market-pricing facts:"]),
        interpretation=sections["Interpretation:"].strip(),
    )
    return report, None


def parse_reports(text: str) -> tuple[list[BreakingNewsReport], list[BreakingNewsError]]:
    text = text.replace("\r\n", "\n")
    text = ATX_PREFIX_RE.sub("", text)

    headings = list(HEADING_RE.finditer(text))

    reports: list[BreakingNewsReport] = []
    errors: list[BreakingNewsError] = []
    seen_ids: set[str] = set()

    for i, h in enumerate(headings):
        report_id = h.group(1)
        headline = h.group(2)
        timestamp_display = h.group(3)
        block_start = h.end()
        block_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[block_start:block_end]

        if report_id in seen_ids:
            errors.append(BreakingNewsError(
                report_id=report_id,
                kind="duplicate_id",
                detail=f"duplicate report_id '{report_id}' (first occurrence kept)",
            ))
            continue
        seen_ids.add(report_id)

        try:
            report, error = _parse_block(report_id, headline, timestamp_display, block)
        except Exception as e:
            errors.append(BreakingNewsError(
                report_id=report_id,
                kind="missing_section",
                detail=f"unexpected parse failure: {e}",
            ))
            continue

        if report is not None:
            reports.append(report)
        if error is not None:
            errors.append(error)

    return reports, errors
