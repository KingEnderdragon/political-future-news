"""
Plain-assert tests for breaking_news.py — no pytest, no test framework
dependency (this repo has none). Run with: python breaking_news_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from breaking_news import (
    BreakingNewsAccessError,
    build_export_url,
    fetch_doc_text,
    parse_reports,
)

_failures = 0
_total = 0


def check(desc: str, cond: bool) -> None:
    global _failures, _total
    _total += 1
    if cond:
        print(f"ok   {desc}")
    else:
        _failures += 1
        print(f"FAIL {desc}")


# ── fixtures: current template (Source links:) ────────────────────────────

CURRENT_TEMPLATE = """\
# HFW-20260701-1200 — Tanker Diversions Accelerate Off Fujairah — 2026-07-01 12:00 EDT

# Report ID: HFW-20260701-1200

# Timestamp: 2026-07-01 12:00 EDT

# Source links:

# • Reuters, July 1, 2026 — Tanker diversions: https://example.com/a

# Physical-balance facts:

# • Three VLCCs diverted around Fujairah anchorage overnight.
# • Loading schedules slipped by 48 hours at two terminals.

# Market-pricing facts:

# • Brent settled at $80.10/bbl, up $1.20 on the session.

# Interpretation:

The diversions are the first physical confirmation of routing stress
this week, though volumes remain small relative to total Gulf throughput.

# Watch items:

# • Whether diversions persist into next week's loading cycle.
"""

# ── fixtures: historical template (Title:/Alert judgment:) ─────────────────

HISTORICAL_TEMPLATE = """\
HFW-20260620-0800 — Strikes Widen Beyond Initial Targets — 2026-06-20 08:00 EDT

Report ID: HFW-20260620-0800

Timestamp: 2026-06-20 08:00 EDT

Title: Strikes Widen Beyond Initial Targets

Alert judgment: ALERT-WORTHY. Strikes have expanded to a second province.

Physical-balance facts:

• Strikes reported near two additional refineries overnight.
• No confirmed production loss yet.

Market-pricing facts:

• WTI briefly spiked $3/bbl intraday before fading.

Interpretation:

The expansion in target set matters more than the price spike, which
has already partly reversed.

Watch items:

• Whether strikes continue into a third day.
"""

# ── malformed: missing required section ────────────────────────────────────

MISSING_INTERPRETATION = """\
HFW-20260701-0900 — Missing Interpretation Section — 2026-07-01 09:00 EDT

Report ID: HFW-20260701-0900

Physical-balance facts:

• Some fact.

Market-pricing facts:

• Some price fact.
"""

# ── malformed: duplicate report id (two blocks, same id) ────────────────────

DUPLICATE_ID = """\
HFW-20260701-0900 — First Copy — 2026-07-01 09:00 EDT

Report ID: HFW-20260701-0900

Physical-balance facts:

• Fact one.

Market-pricing facts:

• Price one.

Interpretation:

First copy interpretation.

HFW-20260701-0900 — Second Copy — 2026-07-01 09:05 EDT

Report ID: HFW-20260701-0900

Physical-balance facts:

• Fact two.

Market-pricing facts:

• Price two.

Interpretation:

Second copy interpretation.
"""

# ── malformed: duplicated optional label ────────────────────────────────────

DUPLICATE_OPTIONAL_LABEL = """\
HFW-20260701-1000 — Duplicate Watch Items — 2026-07-01 10:00 EDT

Report ID: HFW-20260701-1000

Physical-balance facts:

• A fact.

Market-pricing facts:

• A price fact.

Interpretation:

Some interpretation text.

Watch items:

• First watch item.

Watch items:

• Second watch item, duplicated label.
"""

# ── unknown section between two known ones ──────────────────────────────────

UNKNOWN_SECTION_BETWEEN_KNOWN = """\
HFW-20260701-1100 — Unknown Section Present — 2026-07-01 11:00 EDT

Report ID: HFW-20260701-1100

Physical-balance facts:

• A fact.

Analyst Aside:

This is a section the parser doesn't know about and should not treat
as a boundary or required label.

Market-pricing facts:

• A price fact.

Interpretation:

Final interpretation text.
"""

# ── unknown labels with digits/parens/ampersand/abbreviation punctuation ────
# Reproduces the specific label shapes flagged in review: a plain title-case-
# words heuristic would miss all four of these as boundaries.

HARDER_UNKNOWN_SECTIONS = """\
HFW-20260701-1200 — Harder Unknown Section Shapes — 2026-07-01 12:00 EDT

Report ID: HFW-20260701-1200

Physical-balance facts:

• A physical fact.

Next 6h:

Watch for a possible update within the next six hours.

Market-pricing facts:

• A market fact.

Risk assessment (provisional):

This is provisional and subject to revision.

Shipping & insurance:

War risk premiums remain elevated.

U.S. response:

No official statement yet.

Interpretation:

Final interpretation text, unaffected by any of the sections above.
"""

# ── a long but realistic future label (near the 80-char bound) ─────────────

LONG_UNKNOWN_LABEL = """\
HFW-20260701-1400 — Long Unknown Label — 2026-07-01 14:00 EDT

Report ID: HFW-20260701-1400

Physical-balance facts:

• A physical fact.

Preliminary Non-Confirmed Field Assessment Pending Further Verification:

This section is long but still well under the 80-character bound.

Market-pricing facts:

• A market fact.

Interpretation:

Final interpretation text, unaffected by the long label above.
"""

# ── mid-line label mention inside a bullet (must not be treated as boundary) ─

MIDLINE_LABEL_MENTION = """\
HFW-20260701-1300 — Midline Label Mention — 2026-07-01 13:00 EDT

Report ID: HFW-20260701-1300

Physical-balance facts:

• As noted in Interpretation: above, this should not split here.
• Second fact line.

Market-pricing facts:

• A price fact.

Interpretation:

Real interpretation text goes here.
"""

# ── truncated last block (no trailing content after final label) ───────────

TRUNCATED_LAST_BLOCK = """\
HFW-20260701-1400 — Truncated Last Block — 2026-07-01 14:00 EDT

Report ID: HFW-20260701-1400

Physical-balance facts:

• A fact.

Market-pricing facts:

• A price fact.

Interpretation:
"""

EMPTY_DOC = "There are no reports in this document at all."


def run() -> None:
    # current template
    reports, errors = parse_reports(CURRENT_TEMPLATE)
    check("current template: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        r = reports[0]
        check("current template: report_id", r.report_id == "HFW-20260701-1200")
        check("current template: headline excludes id/timestamp", r.headline == "Tanker Diversions Accelerate Off Fujairah")
        check("current template: timestamp_display verbatim", r.timestamp_display == "2026-07-01 12:00 EDT")
        check("current template: physical facts count", len(r.physical_facts) == 2)
        check("current template: market facts count", len(r.market_facts) == 1)
        check("current template: bullets stripped of markers", not r.physical_facts[0].startswith("•"))
        check("current template: interpretation non-empty", "physical confirmation" in r.interpretation)
        check("current template: watch items not exposed", not hasattr(r, "watch_items"))

    # historical template
    reports, errors = parse_reports(HISTORICAL_TEMPLATE)
    check("historical template: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        r = reports[0]
        check("historical template: report_id", r.report_id == "HFW-20260620-0800")
        check("historical template: physical facts count", len(r.physical_facts) == 2)
        check("historical template: interpretation captured", "expansion in target set" in r.interpretation)

    # missing required section -> visible error, not silent skip
    reports, errors = parse_reports(MISSING_INTERPRETATION)
    check("missing section: 0 reports", len(reports) == 0)
    check("missing section: 1 error", len(errors) == 1)
    if errors:
        check("missing section: names the report id", errors[0].report_id == "HFW-20260701-0900")
        check("missing section: kind is missing_section", errors[0].kind == "missing_section")
        check("missing section: names Interpretation", "Interpretation:" in errors[0].detail)

    # duplicate report id -> first kept, second flagged as error
    reports, errors = parse_reports(DUPLICATE_ID)
    check("duplicate id: 1 report kept", len(reports) == 1)
    check("duplicate id: first occurrence kept", reports[0].headline == "First Copy" if reports else False)
    check("duplicate id: 1 error", len(errors) == 1 and errors[0].kind == "duplicate_id")

    # duplicated optional label -> error, no report
    reports, errors = parse_reports(DUPLICATE_OPTIONAL_LABEL)
    check("duplicate optional label: 0 reports", len(reports) == 0)
    check("duplicate optional label: 1 error", len(errors) == 1)
    if errors:
        check("duplicate optional label: kind duplicate_section", errors[0].kind == "duplicate_section")
        check("duplicate optional label: names Watch items", "Watch items:" in errors[0].detail)

    # unknown section between known ones -> parses fine, unknown section ignored
    reports, errors = parse_reports(UNKNOWN_SECTION_BETWEEN_KNOWN)
    check("unknown section: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        r = reports[0]
        check("unknown section: physical facts unaffected", len(r.physical_facts) == 1)
        check("unknown section: market facts unaffected", len(r.market_facts) == 1)
        check("unknown section: interpretation unaffected", r.interpretation == "Final interpretation text.")

    # harder unknown label shapes: digits, parens, ampersand, abbreviation punctuation
    reports, errors = parse_reports(HARDER_UNKNOWN_SECTIONS)
    check("harder unknown labels: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        r = reports[0]
        check("harder unknown labels: physical facts unaffected (not swallowed by 'Next 6h:')", len(r.physical_facts) == 1)
        check("harder unknown labels: market facts unaffected (not swallowed by parens/ampersand/abbrev labels)", len(r.market_facts) == 1)
        check(
            "harder unknown labels: interpretation unaffected",
            r.interpretation == "Final interpretation text, unaffected by any of the sections above.",
        )

    # a long (72-char) but realistic future label, near the 80-char bound
    reports, errors = parse_reports(LONG_UNKNOWN_LABEL)
    check("long unknown label: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        r = reports[0]
        check("long unknown label: physical facts unaffected", len(r.physical_facts) == 1)
        check("long unknown label: market facts unaffected", len(r.market_facts) == 1)
        check(
            "long unknown label: interpretation unaffected",
            r.interpretation == "Final interpretation text, unaffected by the long label above.",
        )

    # mid-line label mention inside a bullet must not split the section
    reports, errors = parse_reports(MIDLINE_LABEL_MENTION)
    check("midline label mention: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        r = reports[0]
        check("midline label mention: both physical bullets kept", len(r.physical_facts) == 2)
        check(
            "midline label mention: bullet text preserved",
            any("should not split here" in f for f in r.physical_facts),
        )
        check("midline label mention: interpretation not swallowed", r.interpretation == "Real interpretation text goes here.")

    # truncated last block (Interpretation: has no body) -> counts as present but empty
    reports, errors = parse_reports(TRUNCATED_LAST_BLOCK)
    check("truncated last block: 1 report, 0 errors", len(reports) == 1 and len(errors) == 0)
    if reports:
        check("truncated last block: interpretation is empty string", reports[0].interpretation == "")

    # both heading styles (# prefixed and bare) in one fixture
    mixed = CURRENT_TEMPLATE + "\n" + HISTORICAL_TEMPLATE
    reports, errors = parse_reports(mixed)
    check("mixed heading styles: 2 reports, 0 errors", len(reports) == 2 and len(errors) == 0)
    check(
        "mixed heading styles: doc order preserved (newest first)",
        [r.report_id for r in reports] == ["HFW-20260701-1200", "HFW-20260620-0800"] if len(reports) == 2 else False,
    )

    # zero heading matches at all -> empty result, no crash
    reports, errors = parse_reports(EMPTY_DOC)
    check("empty doc: ([], [])", reports == [] and errors == [])

    # ── compatibility baseline: the actual live document ────────────────────
    live_fixture = Path(__file__).parent / "breaking_news_fixture_live.txt"
    if live_fixture.exists():
        live_text = live_fixture.read_text(encoding="utf-8")
        reports, errors = parse_reports(live_text)
        check("live doc baseline: all 18 reports parse", len(reports) == 18)
        check("live doc baseline: zero errors", len(errors) == 0)
        ids = [r.report_id for r in reports]
        check("live doc baseline: no duplicate ids in output", len(ids) == len(set(ids)))
    else:
        check("live doc baseline fixture present", False)

    # ── fetch_doc_text: stubbed requests.get, no real network calls ─────────

    class _FakeResp:
        def __init__(self, status_code=200, url="https://docs.google.com/document/d/x/export?format=txt",
                     headers=None, content=b""):
            self.status_code = status_code
            self.url = url
            self.headers = headers or {"content-type": "text/plain; charset=UTF-8"}
            self.content = content

    with mock.patch("breaking_news.requests.get") as m:
        m.return_value = _FakeResp(content="HFW-1 — h — 2026-01-01 00:00 EDT\n".encode("utf-8"))
        text = fetch_doc_text("https://docs.google.com/document/d/x/export?format=txt")
        check("fetch_doc_text: happy path returns text", "HFW-1" in text)

    with mock.patch("breaking_news.requests.get") as m:
        # requests follows redirects internally when allow_redirects=True, so a
        # login-wall redirect lands here as a 200 at the new (accounts.google.com) URL.
        m.return_value = _FakeResp(status_code=200, url="https://accounts.google.com/ServiceLogin")
        try:
            fetch_doc_text("https://docs.google.com/document/d/x/export?format=txt")
            check("fetch_doc_text: login redirect raises", False)
        except BreakingNewsAccessError as e:
            check("fetch_doc_text: login redirect raises", "accounts.google.com" in str(e))

    with mock.patch("breaking_news.requests.get") as m:
        m.return_value = _FakeResp(status_code=404)
        try:
            fetch_doc_text("https://docs.google.com/document/d/x/export?format=txt")
            check("fetch_doc_text: non-200 raises", False)
        except BreakingNewsAccessError as e:
            check("fetch_doc_text: non-200 raises", "404" in str(e))

    with mock.patch("breaking_news.requests.get") as m:
        m.return_value = _FakeResp(headers={"content-type": "text/html; charset=UTF-8"}, content=b"<html>nope</html>")
        try:
            fetch_doc_text("https://docs.google.com/document/d/x/export?format=txt")
            check("fetch_doc_text: html content-type raises", False)
        except BreakingNewsAccessError as e:
            check("fetch_doc_text: html content-type raises", "HTML" in str(e))

    check("build_export_url: shape", build_export_url("abc123").endswith("/d/abc123/export?format=txt"))

    print()
    print(f"{_total - _failures}/{_total} passed")
    if _failures:
        sys.exit(1)


if __name__ == "__main__":
    run()
