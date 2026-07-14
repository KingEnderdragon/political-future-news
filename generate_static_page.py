"""
Renders a self-contained static HTML snapshot of the KapturFlow feed + digest
for sharing (e.g. via Claude Artifacts). Reads the same JSON stores the
Streamlit app uses; writes nothing back. Run manually whenever you want a
fresh snapshot: python generate_static_page.py [output_path]
"""

import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE))
CLASSIFIED_FILE = DATA_DIR / "mediaflow_classified.json"
DIGEST_FILE = DATA_DIR / "mediaflow_digest.json"

ARC_LABEL = {
    "LEGISLATION": "Legislation",
    "COMMITTEE":   "Committee",
    "DISTRICT":    "District",
    "CAMPAIGN":    "Campaign",
    "MEDIA":       "Media",
}
ARC_ORDER = list(ARC_LABEL.keys())
ITEMS_PER_ARC_CAP = 25


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


def fmt_date(dt: datetime) -> str:
    if dt == datetime.min.replace(tzinfo=timezone.utc):
        return "undated"
    return dt.strftime("%b %d, %Y &middot; %H:%M UTC")


def load_classified() -> list[dict]:
    if not CLASSIFIED_FILE.exists():
        return []
    data = json.loads(CLASSIFIED_FILE.read_text(encoding="utf-8"))
    return sorted(data, key=lambda x: parse_dt(x.get("published", "")), reverse=True)


def load_digests() -> dict:
    if not DIGEST_FILE.exists():
        return {}
    return json.loads(DIGEST_FILE.read_text(encoding="utf-8"))


def render_digest_arc(arc: str, entry: dict) -> str:
    label = ARC_LABEL.get(arc, arc)
    summary = escape(entry.get("critical_summary", ""))
    analysis = escape(entry.get("analysis", ""))
    count = entry.get("item_count", 0)
    analysis_html = f'<p class="digest-analysis">{analysis}</p>' if analysis else ""
    points = entry.get("talking_points") or []
    points_html = ""
    if points:
        items_html = "".join(f"<li>{escape(p)}</li>" for p in points)
        points_html = f"""
          <div class="talking-points">
            <span class="tp-label">Talking points</span>
            <ul>{items_html}</ul>
          </div>"""
    return f"""
        <article class="digest-card" data-arc="{arc}">
          <header class="digest-card-head">
            <span class="chip chip-{arc.lower()}">{escape(label)}</span>
            <span class="digest-count">{count} item{'s' if count != 1 else ''}</span>
          </header>
          <p class="digest-summary">{summary}</p>
          {analysis_html}
          {points_html}
        </article>"""


def render_digest_window(window_days: int, digest: dict) -> str:
    arcs_html = []
    for arc in ARC_ORDER:
        entry = (digest.get("arcs") or {}).get(arc)
        if entry:
            arcs_html.append(render_digest_arc(arc, entry))
    gen_dt = parse_dt(digest.get("generated_at", ""))
    period = "past week" if window_days <= 7 else f"past {window_days} days"
    meta = f'<p class="digest-meta">Generated {fmt_date(gen_dt)} &nbsp;&middot;&nbsp; {period}</p>' if digest else ""
    body = "\n".join(arcs_html) if arcs_html else '<p class="empty-note">No digest data for this window.</p>'
    checked = "checked" if window_days == 7 else ""
    return checked, f"""
      <section class="digest-pane" id="digest-{window_days}d">
        {meta}
        <div class="digest-grid">{body}</div>
      </section>"""


def render_feed_item(item: dict) -> str:
    arc = item.get("arc", "UNMAPPED")
    label = ARC_LABEL.get(arc, "Other")
    dt = parse_dt(item.get("published", ""))
    source = escape(item.get("source", ""))
    summary = escape(item.get("arc_summary") or item.get("title", ""))
    analysis = escape(item.get("arc_analysis") or "")
    link = escape(item.get("link", "#"), quote=True)
    conflict = item.get("conflict", False)
    conflict_mark = '<span class="conflict-mark" title="Conflicting claims reported">&#9889;</span> ' if conflict else ""
    analysis_html = f'<p class="feed-analysis">{analysis}</p>' if analysis else ""
    return f"""
        <li class="feed-item" data-arc="{arc}">
          <div class="feed-item-head">
            <span class="chip chip-sm chip-{arc.lower() if arc in ARC_LABEL else 'other'}">{escape(label)}</span>
            <time class="feed-time">{fmt_date(dt)}</time>
            <span class="feed-source">{source}</span>
          </div>
          <p class="feed-summary">{conflict_mark}{summary}</p>
          {analysis_html}
          <a class="feed-link" href="{link}" target="_blank" rel="noopener noreferrer">Read source &#8599;</a>
        </li>"""


def build_feed_html(items: list[dict]) -> str:
    per_arc_count: dict[str, int] = {}
    selected = []
    for item in items:
        arc = item.get("arc", "UNMAPPED")
        key = arc if arc in ARC_LABEL else "OTHER"
        if per_arc_count.get(key, 0) >= ITEMS_PER_ARC_CAP:
            continue
        per_arc_count[key] = per_arc_count.get(key, 0) + 1
        selected.append(item)
    selected.sort(key=lambda i: parse_dt(i.get("published", "")), reverse=True)
    return "\n".join(render_feed_item(i) for i in selected), len(selected)


def build_tabs(items: list[dict]) -> str:
    counts = {arc: 0 for arc in ARC_ORDER}
    other = 0
    for item in items:
        arc = item.get("arc", "UNMAPPED")
        if arc in counts:
            counts[arc] += 1
        else:
            other += 1
    inputs = ['<input type="radio" name="feedtab" id="tab-all" checked>']
    labels = ['<label for="tab-all" class="tab-label">All <span class="tab-count">{}</span></label>'.format(len(items))]
    for arc in ARC_ORDER:
        slug = arc.lower()
        inputs.append(f'<input type="radio" name="feedtab" id="tab-{slug}">')
        labels.append(
            f'<label for="tab-{slug}" class="tab-label">{escape(ARC_LABEL[arc])} '
            f'<span class="tab-count">{counts[arc]}</span></label>'
        )
    if other:
        inputs.append('<input type="radio" name="feedtab" id="tab-other">')
        labels.append(f'<label for="tab-other" class="tab-label">Other <span class="tab-count">{other}</span></label>')
    return "\n".join(inputs), "\n".join(labels)


def build_visibility_css(has_other: bool) -> str:
    # Hide-then-reshow: default state (#tab-all) shows everything; each
    # specific tab hides all items, then re-shows only its own arc.
    rules = []
    for arc in ARC_ORDER:
        slug = arc.lower()
        rules.append(
            f'#tab-{slug}:checked ~ .feed-list .feed-item {{ display: none; }}\n'
            f'#tab-{slug}:checked ~ .feed-list .feed-item[data-arc="{arc}"] {{ display: block; }}'
        )
    if has_other:
        nots = "".join(f':not([data-arc="{arc}"])' for arc in ARC_ORDER)
        rules.append(
            '#tab-other:checked ~ .feed-list .feed-item { display: none; }\n'
            f'#tab-other:checked ~ .feed-list .feed-item{nots} {{ display: block; }}'
        )
    return "\n".join(rules)


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "kapturflow_snapshot.html"

    items = load_classified()
    digests = load_digests()

    checked7, pane7 = render_digest_window(7, digests.get("7", {}))
    checked30, pane30 = render_digest_window(30, digests.get("30", {}))

    feed_html, feed_count = build_feed_html(items)
    tab_inputs, tab_labels = build_tabs(items)
    has_other = any(i.get("arc") not in ARC_LABEL for i in items)
    tab_visibility_css = build_visibility_css(has_other)

    total_items = len(items)
    now = datetime.now(timezone.utc)

    html = HTML_TEMPLATE.format(
        generated=fmt_date(now),
        total_items=total_items,
        feed_count=feed_count,
        pane7=pane7,
        pane30=pane30,
        tab_inputs=tab_inputs,
        tab_labels=tab_labels,
        feed_html=feed_html,
        tab_checked_css=tab_visibility_css,
    )
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes, {total_items} items, {feed_count} shown in feed)")


HTML_TEMPLATE = """<title>KapturFlow — Rep. Marcy Kaptur (OH-9) News Digest</title>
<style>
:root {{
  --paper: #eef1ee;
  --paper-raised: #ffffff;
  --ink: #1c2420;
  --ink-muted: #52605a;
  --rule: #cfd6cd;
  --accent: #1f6f6b;
  --accent-soft: #e0edea;

  --c-legislation: #2f5f8a;
  --c-legislation-soft: #e2ebf2;
  --c-committee: #6b4d8a;
  --c-committee-soft: #ece4f2;
  --c-district: #2f7a52;
  --c-district-soft: #e1f0e6;
  --c-campaign: #a13d3d;
  --c-campaign-soft: #f3e2e2;
  --c-media: #b06a24;
  --c-media-soft: #f4e9db;
  --c-other: #6b7570;
  --c-other-soft: #e6e9e6;

  --font-display: Georgia, 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', serif;
  --font-body: Georgia, 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', serif;
  --font-mono: ui-monospace, 'SF Mono', 'Cascadia Mono', 'Consolas', monospace;
}}

@media (prefers-color-scheme: dark) {{
  :root {{
    --paper: #14181a;
    --paper-raised: #1c2224;
    --ink: #e7ece8;
    --ink-muted: #9aa6a0;
    --rule: #2b3234;
    --accent: #59c2ba;
    --accent-soft: #1c3230;

    --c-legislation: #7fa8d1;
    --c-legislation-soft: #202c37;
    --c-committee: #b795d6;
    --c-committee-soft: #29222f;
    --c-district: #6fbf8f;
    --c-district-soft: #1c2c22;
    --c-campaign: #d68080;
    --c-campaign-soft: #2f2020;
    --c-media: #dba05a;
    --c-media-soft: #2f2619;
    --c-other: #9aa6a0;
    --c-other-soft: #23282a;
  }}
}}

:root[data-theme="dark"] {{
  --paper: #14181a;
  --paper-raised: #1c2224;
  --ink: #e7ece8;
  --ink-muted: #9aa6a0;
  --rule: #2b3234;
  --accent: #59c2ba;
  --accent-soft: #1c3230;

  --c-legislation: #7fa8d1;
  --c-legislation-soft: #202c37;
  --c-committee: #b795d6;
  --c-committee-soft: #29222f;
  --c-district: #6fbf8f;
  --c-district-soft: #1c2c22;
  --c-campaign: #d68080;
  --c-campaign-soft: #2f2020;
  --c-media: #dba05a;
  --c-media-soft: #2f2619;
  --c-other: #9aa6a0;
  --c-other-soft: #23282a;
}}

:root[data-theme="light"] {{
  --paper: #eef1ee;
  --paper-raised: #ffffff;
  --ink: #1c2420;
  --ink-muted: #52605a;
  --rule: #cfd6cd;
  --accent: #1f6f6b;
  --accent-soft: #e0edea;

  --c-legislation: #2f5f8a;
  --c-legislation-soft: #e2ebf2;
  --c-committee: #6b4d8a;
  --c-committee-soft: #ece4f2;
  --c-district: #2f7a52;
  --c-district-soft: #e1f0e6;
  --c-campaign: #a13d3d;
  --c-campaign-soft: #f3e2e2;
  --c-media: #b06a24;
  --c-media-soft: #f4e9db;
  --c-other: #6b7570;
  --c-other-soft: #e6e9e6;
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-body);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}

.wrap {{
  max-width: 880px;
  margin: 0 auto;
  padding: 2.5rem 1.5rem 5rem;
}}

/* ── masthead ─────────────────────────────────────────────────────── */

.masthead {{
  border-bottom: 3px double var(--rule);
  padding-bottom: 1.25rem;
  margin-bottom: 2rem;
}}

.masthead-eyebrow {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
}}

.masthead h1 {{
  font-family: var(--font-display);
  font-size: clamp(1.9rem, 4vw, 2.6rem);
  font-weight: 700;
  margin: 0.2rem 0 0.3rem;
  text-wrap: balance;
}}

.masthead-sub {{
  color: var(--ink-muted);
  font-size: 1.02rem;
  margin: 0 0 0.9rem;
}}

.masthead-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.1rem;
  font-family: var(--font-mono);
  font-size: 0.74rem;
  color: var(--ink-muted);
}}

.masthead-meta strong {{
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}}

.snapshot-note {{
  margin-top: 0.9rem;
  padding: 0.6rem 0.85rem;
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  font-size: 0.84rem;
  color: var(--ink-muted);
}}

/* ── sections ─────────────────────────────────────────────────────── */

section.block {{
  margin-bottom: 2.6rem;
}}

.block-head {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.9rem;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 0.4rem;
}}

.block-head h2 {{
  font-family: var(--font-display);
  font-size: 1.3rem;
  margin: 0;
}}

.block-head .block-note {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}

/* ── digest window toggle ─────────────────────────────────────────── */

.window-toggle {{
  display: inline-flex;
  gap: 2px;
  background: var(--rule);
  padding: 2px;
  border-radius: 6px;
  margin-bottom: 1rem;
}}

.window-toggle input {{ position: absolute; opacity: 0; pointer-events: none; }}

.window-toggle label {{
  font-family: var(--font-mono);
  font-size: 0.76rem;
  font-weight: 600;
  padding: 0.35rem 0.8rem;
  border-radius: 4px;
  cursor: pointer;
  color: var(--ink-muted);
  background: transparent;
}}

#win-7:checked ~ .window-toggle label[for="win-7"],
#win-30:checked ~ .window-toggle label[for="win-30"] {{
  background: var(--paper-raised);
  color: var(--ink);
}}

.digest-pane {{ display: none; }}
#win-7:checked ~ #digest-7d {{ display: block; }}
#win-30:checked ~ #digest-30d {{ display: block; }}

.digest-meta {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--ink-muted);
  margin: 0 0 0.9rem;
}}

.digest-grid {{
  display: grid;
  gap: 0.9rem;
}}

.digest-card {{
  background: var(--paper-raised);
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 1rem 1.15rem;
}}

.digest-card-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.55rem;
}}

.digest-count {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}}

.digest-summary {{
  margin: 0 0 0.4rem;
  font-size: 1rem;
  max-width: 65ch;
}}

.digest-analysis {{
  margin: 0;
  font-style: italic;
  color: var(--ink-muted);
  font-size: 0.94rem;
  max-width: 65ch;
}}

.empty-note {{
  color: var(--ink-muted);
  font-style: italic;
  font-size: 0.9rem;
}}

.talking-points {{
  margin-top: 0.6rem;
  padding-top: 0.55rem;
  border-top: 1px dashed var(--rule);
}}

.tp-label {{
  font-family: var(--font-mono);
  font-size: 0.66rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-muted);
}}

.talking-points ul {{
  margin: 0.35rem 0 0;
  padding-left: 1.15rem;
}}

.talking-points li {{
  font-size: 0.9rem;
  margin-bottom: 0.2rem;
  max-width: 65ch;
}}

/* ── chips ────────────────────────────────────────────────────────── */

.chip {{
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
}}

.chip-sm {{ font-size: 0.63rem; padding: 0.14rem 0.4rem; }}

.chip-legislation {{ color: var(--c-legislation); background: var(--c-legislation-soft); }}
.chip-committee    {{ color: var(--c-committee);    background: var(--c-committee-soft); }}
.chip-district     {{ color: var(--c-district);     background: var(--c-district-soft); }}
.chip-campaign     {{ color: var(--c-campaign);     background: var(--c-campaign-soft); }}
.chip-media        {{ color: var(--c-media);        background: var(--c-media-soft); }}
.chip-other        {{ color: var(--c-other);        background: var(--c-other-soft); }}

/* ── feed tabs ────────────────────────────────────────────────────── */

.feed-tabs {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-bottom: 1rem;
}}

.feed-tabs input {{ position: absolute; opacity: 0; pointer-events: none; }}

.tab-label {{
  font-family: var(--font-mono);
  font-size: 0.76rem;
  font-weight: 600;
  padding: 0.32rem 0.7rem;
  border-radius: 5px;
  border: 1px solid var(--rule);
  cursor: pointer;
  color: var(--ink-muted);
  background: var(--paper-raised);
}}

.tab-count {{ font-variant-numeric: tabular-nums; opacity: 0.75; }}

{tab_checked_css}

.feed-list {{
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}}

.feed-item {{
  background: var(--paper-raised);
  border: 1px solid var(--rule);
  border-left-width: 3px;
  border-radius: 6px;
  padding: 0.75rem 1rem;
}}

.feed-item[data-arc="LEGISLATION"] {{ border-left-color: var(--c-legislation); }}
.feed-item[data-arc="COMMITTEE"]   {{ border-left-color: var(--c-committee); }}
.feed-item[data-arc="DISTRICT"]    {{ border-left-color: var(--c-district); }}
.feed-item[data-arc="CAMPAIGN"]    {{ border-left-color: var(--c-campaign); }}
.feed-item[data-arc="MEDIA"]       {{ border-left-color: var(--c-media); }}
.feed-item:not([data-arc="LEGISLATION"]):not([data-arc="COMMITTEE"]):not([data-arc="DISTRICT"]):not([data-arc="CAMPAIGN"]):not([data-arc="MEDIA"]) {{ border-left-color: var(--c-other); }}

.feed-item-head {{
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}}

.feed-time {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}}

.feed-source {{
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--ink-muted);
}}

.feed-source::before {{ content: "· "; }}

.feed-summary {{
  margin: 0 0 0.3rem;
  max-width: 68ch;
}}

.conflict-mark {{ color: var(--c-campaign); }}

.feed-analysis {{
  margin: 0 0 0.4rem;
  font-style: italic;
  color: var(--ink-muted);
  font-size: 0.92rem;
  max-width: 68ch;
}}

.feed-link {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--accent);
  text-decoration: none;
}}
.feed-link:hover {{ text-decoration: underline; }}
.feed-link:focus-visible, .tab-label:focus-visible, label:focus-visible {{
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}}

footer.colophon {{
  margin-top: 3rem;
  padding-top: 1rem;
  border-top: 1px solid var(--rule);
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--ink-muted);
}}

footer.colophon p {{ margin: 0 0 0.5rem; }}
footer.colophon p:last-child {{ margin-bottom: 0; }}
footer.colophon strong {{ color: var(--c-campaign); }}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
</style>

<div class="wrap">
  <header class="masthead">
    <div class="masthead-eyebrow">KapturFlow &middot; Local news intelligence</div>
    <h1>Rep. Marcy Kaptur &mdash; Ohio's 9th District</h1>
    <p class="masthead-sub">A running monitor of legislation, committee work, district activity, campaign coverage, and media appearances.</p>
    <div class="masthead-meta">
      <span>Snapshot generated <strong>{generated}</strong></span>
      <span><strong>{total_items}</strong> items tracked</span>
      <span><strong>{feed_count}</strong> shown below</span>
    </div>
    <p class="snapshot-note">This is a static snapshot, not a live feed &mdash; it reflects the data available at generation time and won't update on its own.</p>
  </header>

  <section class="block">
    <div class="block-head">
      <h2>Digest &mdash; critical summary &amp; analysis by category</h2>
      <span class="block-note">By arc</span>
    </div>
    <input type="radio" name="digestwin" id="win-7" checked>
    <input type="radio" name="digestwin" id="win-30">
    <div class="window-toggle">
      <label for="win-7">Last 7 days</label>
      <label for="win-30">Last 30 days</label>
    </div>
    {pane7}
    {pane30}
  </section>

  <section class="block">
    <div class="block-head">
      <h2>Live feed</h2>
      <span class="block-note">Newest first</span>
    </div>
    {tab_inputs}
    <div class="feed-tabs">
      {tab_labels}
    </div>
    <ul class="feed-list">
      {feed_html}
    </ul>
  </section>

  <footer class="colophon">
    <p>KapturFlow tracks public reporting on Rep. Marcy Kaptur (D&ndash;OH-9) from wire, local, and official sources. Summaries, analysis, and talking points are generated by a local language model.</p>
    <p><strong>Verify before you repeat anything, especially talking points:</strong> the model can and does state specific numbers, dates, or vote outcomes that are not actually in the source reporting. Treat every figure here as unverified until you've checked the linked source.</p>
  </footer>
</div>
"""

if __name__ == "__main__":
    main()
