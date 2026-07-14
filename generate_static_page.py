"""
Renders a self-contained static HTML snapshot covering every tracked
subject (see subjects.py), with a top-level toggle to switch between them,
for sharing (e.g. via Claude Artifacts / GitHub Pages). Reads the same JSON
stores the Streamlit app uses; writes nothing back.

Run manually whenever you want a fresh snapshot: python generate_static_page.py [output_path]
"""

import json
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
from pathlib import Path

import subjects

HERE = Path(__file__).parent
ITEMS_PER_ARC_CAP = 25

# Reused across every subject regardless of their specific arc names — each
# subject's arcs (subjects.py, "arc_label" dict order) map positionally onto
# these five slots, so the same validated light/dark palette works for all
# of them without a combinatorial explosion of per-subject CSS variables.
SLOT_COUNT = 5


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


def load_classified(classified_file: Path) -> list[dict]:
    if not classified_file.exists():
        return []
    data = json.loads(classified_file.read_text(encoding="utf-8"))
    return sorted(data, key=lambda x: parse_dt(x.get("published", "")), reverse=True)


def load_digests(digest_file: Path) -> dict:
    if not digest_file.exists():
        return {}
    return json.loads(digest_file.read_text(encoding="utf-8"))


def arc_slots(subject: dict) -> dict[str, int]:
    return {arc: i % SLOT_COUNT for i, arc in enumerate(subject["arc_label"])}


def render_digest_arc(arc: str, entry: dict, subject: dict, slots: dict[str, int]) -> str:
    label = subject["arc_label"].get(arc, arc)
    slot = slots.get(arc, 0)
    summary = escape(entry.get("critical_summary", ""))
    analysis = escape(entry.get("analysis", ""))
    count = entry.get("item_count", 0)
    analysis_html = f'<p class="digest-analysis">{analysis}</p>' if analysis else ""
    points = entry.get("talking_points") or []
    points_html = ""
    if points:
        li_parts = []
        for p in points:
            text = p.get("text", "") if isinstance(p, dict) else str(p)
            link = p.get("link", "") if isinstance(p, dict) else ""
            source = p.get("source", "") if isinstance(p, dict) else ""
            link_html = (
                f' <a class="tp-link" href="{escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">'
                f'&#8594; {escape(source) or "source"}</a>'
                if link else ""
            )
            li_parts.append(f"<li>{escape(text)}{link_html}</li>")
        items_html = "".join(li_parts)
        points_html = f"""
          <div class="talking-points">
            <span class="tp-label">Talking points</span>
            <ul>{items_html}</ul>
          </div>"""
    return f"""
        <article class="digest-card" data-arc="{arc}">
          <header class="digest-card-head">
            <span class="chip chip-slot{slot}">{escape(label)}</span>
            <span class="digest-count">{count} item{'s' if count != 1 else ''}</span>
          </header>
          <p class="digest-summary">{summary}</p>
          {analysis_html}
          {points_html}
        </article>"""


def render_digest_window(slug: str, window_days: int, digest: dict, subject: dict, slots: dict[str, int]) -> str:
    arcs_html = []
    for arc in subject["arc_label"]:
        entry = (digest.get("arcs") or {}).get(arc)
        if entry:
            arcs_html.append(render_digest_arc(arc, entry, subject, slots))
    gen_dt = parse_dt(digest.get("generated_at", ""))
    period = "past week" if window_days <= 7 else f"past {window_days} days"
    meta = f'<p class="digest-meta">Generated {fmt_date(gen_dt)} &nbsp;&middot;&nbsp; {period}</p>' if digest else ""
    body = "\n".join(arcs_html) if arcs_html else '<p class="empty-note">No digest data for this window.</p>'
    return f"""
      <section class="digest-pane" id="digest-{window_days}d-{slug}">
        {meta}
        <div class="digest-grid">{body}</div>
      </section>"""


def render_feed_item(item: dict, subject: dict, slots: dict[str, int]) -> str:
    arc = item.get("arc", "UNMAPPED")
    label = subject["arc_label"].get(arc, "Other")
    slot = slots.get(arc)
    chip_class = f"chip-slot{slot}" if slot is not None else "chip-other"
    border_class = f"slot{slot}" if slot is not None else "other"
    dt = parse_dt(item.get("published", ""))
    source = escape(item.get("source", ""))
    summary = escape(item.get("arc_summary") or item.get("title", ""))
    analysis = escape(item.get("arc_analysis") or "")
    link = escape(item.get("link", "#"), quote=True)
    conflict = item.get("conflict", False)
    conflict_mark = '<span class="conflict-mark" title="Conflicting claims reported">&#9889;</span> ' if conflict else ""
    analysis_html = f'<p class="feed-analysis">{analysis}</p>' if analysis else ""
    return f"""
        <li class="feed-item feed-item-{border_class}" data-arc="{arc}">
          <div class="feed-item-head">
            <span class="chip chip-sm {chip_class}">{escape(label)}</span>
            <time class="feed-time">{fmt_date(dt)}</time>
            <span class="feed-source">{source}</span>
          </div>
          <p class="feed-summary">{conflict_mark}{summary}</p>
          {analysis_html}
          <a class="feed-link" href="{link}" target="_blank" rel="noopener noreferrer">Read source &#8599;</a>
        </li>"""


def build_feed_html(items: list[dict], subject: dict, slots: dict[str, int]) -> tuple[str, int]:
    per_arc_count: dict[str, int] = {}
    selected = []
    for item in items:
        arc = item.get("arc", "UNMAPPED")
        key = arc if arc in subject["arc_label"] else "OTHER"
        if per_arc_count.get(key, 0) >= ITEMS_PER_ARC_CAP:
            continue
        per_arc_count[key] = per_arc_count.get(key, 0) + 1
        selected.append(item)
    selected.sort(key=lambda i: parse_dt(i.get("published", "")), reverse=True)
    return "\n".join(render_feed_item(i, subject, slots) for i in selected), len(selected)


def build_tabs(slug: str, items: list[dict], subject: dict) -> tuple[str, str]:
    arc_order = list(subject["arc_label"])
    counts = {arc: 0 for arc in arc_order}
    other = 0
    for item in items:
        arc = item.get("arc", "UNMAPPED")
        if arc in counts:
            counts[arc] += 1
        else:
            other += 1
    inputs = [f'<input type="radio" name="feedtab-{slug}" id="tab-all-{slug}" checked>']
    labels = [f'<label for="tab-all-{slug}" class="tab-label">All <span class="tab-count">{len(items)}</span></label>']
    for arc in arc_order:
        arc_slug = arc.lower()
        inputs.append(f'<input type="radio" name="feedtab-{slug}" id="tab-{arc_slug}-{slug}">')
        labels.append(
            f'<label for="tab-{arc_slug}-{slug}" class="tab-label">{escape(subject["arc_label"][arc])} '
            f'<span class="tab-count">{counts[arc]}</span></label>'
        )
    if other:
        inputs.append(f'<input type="radio" name="feedtab-{slug}" id="tab-other-{slug}">')
        labels.append(f'<label for="tab-other-{slug}" class="tab-label">Other <span class="tab-count">{other}</span></label>')
    return "\n".join(inputs), "\n".join(labels)


def build_visibility_css(slug: str, subject: dict, has_other: bool) -> str:
    # Hide-then-reshow: default state (#tab-all-{slug}) shows everything;
    # each specific tab hides all items in this subject's feed, then
    # re-shows only its own arc.
    rules = []
    for arc in subject["arc_label"]:
        arc_slug = arc.lower()
        rules.append(
            f'#tab-{arc_slug}-{slug}:checked ~ .feed-list-{slug} .feed-item {{ display: none; }}\n'
            f'#tab-{arc_slug}-{slug}:checked ~ .feed-list-{slug} .feed-item[data-arc="{arc}"] {{ display: block; }}'
        )
    if has_other:
        nots = "".join(f':not([data-arc="{arc}"])' for arc in subject["arc_label"])
        rules.append(
            f'#tab-other-{slug}:checked ~ .feed-list-{slug} .feed-item {{ display: none; }}\n'
            f'#tab-other-{slug}:checked ~ .feed-list-{slug} .feed-item{nots} {{ display: block; }}'
        )
    return "\n".join(rules)


def render_pane(slug: str, now: datetime) -> str:
    subject = subjects.get_subject(slug)
    paths = subjects.paths_for(slug)
    slots = arc_slots(subject)

    items = load_classified(paths["classified"])
    digests = load_digests(paths["digest"])

    pane7 = render_digest_window(slug, 7, digests.get("7", {}), subject, slots)
    pane30 = render_digest_window(slug, 30, digests.get("30", {}), subject, slots)

    feed_html, feed_count = build_feed_html(items, subject, slots)
    tab_inputs, tab_labels = build_tabs(slug, items, subject)
    has_other = any(i.get("arc") not in subject["arc_label"] for i in items)
    tab_visibility_css = build_visibility_css(slug, subject, has_other)

    total_items = len(items)

    return tab_visibility_css, f"""
    <section class="subject-pane" id="pane-{slug}">
      <div class="pane-head">
        <h1>{escape(subject['name'])}</h1>
        <p class="masthead-sub">{escape(subject['subtitle'])}</p>
        <div class="masthead-meta">
          <span>Snapshot generated <strong>{fmt_date(now)}</strong></span>
          <span><strong>{total_items}</strong> items tracked</span>
          <span><strong>{feed_count}</strong> shown below</span>
        </div>
      </div>

      <section class="block">
        <div class="block-head">
          <h2>Digest &mdash; critical summary &amp; analysis by category</h2>
          <span class="block-note">By arc</span>
        </div>
        <input type="radio" name="digestwin-{slug}" id="win-7-{slug}" checked>
        <input type="radio" name="digestwin-{slug}" id="win-30-{slug}">
        <div class="window-toggle">
          <label for="win-7-{slug}">Last 7 days</label>
          <label for="win-30-{slug}">Last 30 days</label>
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
        <ul class="feed-list feed-list-{slug}">
          {feed_html}
        </ul>
      </section>
    </section>"""


GROUP_LABEL = {"politicians": "Politicians", "issues": "Ohio Issues"}


def render_group(group: str, slugs: list[str], now: datetime) -> tuple[str, str, str]:
    """Builds one group's subject toggle + panes. Returns (css, active_css, html)."""
    subject_inputs = []
    subject_labels = []
    subject_panes = []
    subject_visibility_css = []
    subject_active_css = []
    window_visibility_css = []
    all_tab_css = []

    for i, slug in enumerate(slugs):
        subject = subjects.get_subject(slug)
        checked = "checked" if i == 0 else ""
        subject_inputs.append(f'<input type="radio" name="subject-{group}" id="person-{slug}" {checked}>')
        subject_labels.append(f'<label for="person-{slug}" class="subject-label">{escape(subject["name"])}</label>')
        subject_visibility_css.append(
            f'#person-{slug}:checked ~ .subject-panes-{group} #pane-{slug} {{ display: block; }}'
        )
        subject_active_css.append(
            f'#person-{slug}:checked ~ .subject-toggle-{group} label[for="person-{slug}"] '
            '{ background: var(--paper-raised); color: var(--ink); }'
        )
        window_visibility_css.append(
            f'#win-7-{slug}:checked ~ #digest-7d-{slug} {{ display: block; }}\n'
            f'#win-30-{slug}:checked ~ #digest-30d-{slug} {{ display: block; }}'
        )
        tab_css, pane_html = render_pane(slug, now)
        all_tab_css.append(tab_css)
        subject_panes.append(pane_html)

    css = "\n".join(subject_visibility_css + subject_active_css + window_visibility_css + all_tab_css)
    html = f"""
    <div class="subject-toggle subject-toggle-{group}">
      {"".join(subject_inputs)}
      {"".join(subject_labels)}
    </div>
    <div class="subject-panes subject-panes-{group}">
      {"".join(subject_panes)}
    </div>"""
    return css, html


def main() -> None:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "kapturflow_snapshot.html"
    now = datetime.now(timezone.utc)

    group_inputs = []
    group_labels = []
    group_panes = []
    group_visibility_css = []
    group_active_css = []
    all_css = []

    for i, group in enumerate(subjects.SUBJECT_GROUPS):
        checked = "checked" if i == 0 else ""
        group_inputs.append(f'<input type="radio" name="group" id="group-{group}" {checked}>')
        group_labels.append(f'<label for="group-{group}" class="group-label">{GROUP_LABEL[group]}</label>')
        group_visibility_css.append(
            f'#group-{group}:checked ~ .group-panes #grouppane-{group} {{ display: block; }}'
        )
        group_active_css.append(
            f'#group-{group}:checked ~ .group-toggle label[for="group-{group}"] '
            '{ background: var(--paper-raised); color: var(--ink); }'
        )
        css, html = render_group(group, subjects.SUBJECT_GROUPS[group], now)
        all_css.append(css)
        group_panes.append(f'<section class="group-pane" id="grouppane-{group}">{html}</section>')

    html = HTML_TEMPLATE.format(
        generated=fmt_date(now),
        group_inputs="\n".join(group_inputs),
        group_labels="\n".join(group_labels),
        group_panes="\n".join(group_panes),
        group_visibility_css="\n".join(group_visibility_css),
        group_active_css="\n".join(group_active_css),
        subject_css="\n".join(all_css),
    )
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes, {len(subjects.SUBJECT_ORDER)} subjects across {len(subjects.SUBJECT_GROUPS)} groups)")


HTML_TEMPLATE = """<title>KapturFlow — Ohio Political News Intelligence</title>
<style>
:root {{
  --paper: #eef1ee;
  --paper-raised: #ffffff;
  --ink: #1c2420;
  --ink-muted: #52605a;
  --rule: #cfd6cd;
  --accent: #1f6f6b;
  --accent-soft: #e0edea;

  --c-slot0: #2f5f8a; --c-slot0-soft: #e2ebf2;
  --c-slot1: #6b4d8a; --c-slot1-soft: #ece4f2;
  --c-slot2: #2f7a52; --c-slot2-soft: #e1f0e6;
  --c-slot3: #a13d3d; --c-slot3-soft: #f3e2e2;
  --c-slot4: #b06a24; --c-slot4-soft: #f4e9db;
  --c-other: #6b7570;  --c-other-soft: #e6e9e6;

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

    --c-slot0: #7fa8d1; --c-slot0-soft: #202c37;
    --c-slot1: #b795d6; --c-slot1-soft: #29222f;
    --c-slot2: #6fbf8f; --c-slot2-soft: #1c2c22;
    --c-slot3: #d68080; --c-slot3-soft: #2f2020;
    --c-slot4: #dba05a; --c-slot4-soft: #2f2619;
    --c-other: #9aa6a0;  --c-other-soft: #23282a;
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

  --c-slot0: #7fa8d1; --c-slot0-soft: #202c37;
  --c-slot1: #b795d6; --c-slot1-soft: #29222f;
  --c-slot2: #6fbf8f; --c-slot2-soft: #1c2c22;
  --c-slot3: #d68080; --c-slot3-soft: #2f2020;
  --c-slot4: #dba05a; --c-slot4-soft: #2f2619;
  --c-other: #9aa6a0;  --c-other-soft: #23282a;
}}

:root[data-theme="light"] {{
  --paper: #eef1ee;
  --paper-raised: #ffffff;
  --ink: #1c2420;
  --ink-muted: #52605a;
  --rule: #cfd6cd;
  --accent: #1f6f6b;
  --accent-soft: #e0edea;

  --c-slot0: #2f5f8a; --c-slot0-soft: #e2ebf2;
  --c-slot1: #6b4d8a; --c-slot1-soft: #ece4f2;
  --c-slot2: #2f7a52; --c-slot2-soft: #e1f0e6;
  --c-slot3: #a13d3d; --c-slot3-soft: #f3e2e2;
  --c-slot4: #b06a24; --c-slot4-soft: #f4e9db;
  --c-other: #6b7570;  --c-other-soft: #e6e9e6;
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
  padding-bottom: 1.25rem;
  margin-bottom: 1.25rem;
}}

.masthead-eyebrow {{
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
}}

.masthead-tagline {{
  color: var(--ink-muted);
  font-size: 1.02rem;
  margin: 0.3rem 0 0;
}}

.snapshot-note {{
  margin-top: 0.9rem;
  padding: 0.6rem 0.85rem;
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  font-size: 0.84rem;
  color: var(--ink-muted);
}}

/* ── group toggle (Politicians / Ohio Issues) ────────────────────────── */

.group-toggle {{
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  background: var(--rule);
  padding: 3px;
  border-radius: 8px;
  margin: 1.4rem 0 1.2rem;
  max-width: 420px;
}}

.group-toggle input {{ position: absolute; opacity: 0; pointer-events: none; }}

.group-label {{
  flex: 1;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 0.86rem;
  font-weight: 700;
  padding: 0.6rem 1rem;
  border-radius: 6px;
  cursor: pointer;
  color: var(--ink-muted);
  background: transparent;
}}

{group_visibility_css}
{group_active_css}

.group-pane {{ display: none; }}

/* ── subject toggle (within a group) ─────────────────────────────────── */

.subject-toggle {{
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  background: var(--rule);
  padding: 3px;
  border-radius: 8px;
  margin: 0 0 2rem;
}}

.subject-toggle input {{ position: absolute; opacity: 0; pointer-events: none; }}

.subject-label {{
  flex: 1;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.55rem 0.9rem;
  border-radius: 6px;
  cursor: pointer;
  color: var(--ink-muted);
  background: transparent;
}}

{subject_css}

.subject-pane {{ display: none; }}

.pane-head h1 {{
  font-family: var(--font-display);
  font-size: clamp(1.8rem, 4vw, 2.4rem);
  font-weight: 700;
  margin: 0 0 0.25rem;
  text-wrap: balance;
  border-bottom: 3px double var(--rule);
  padding-bottom: 0.6rem;
}}

.masthead-sub {{
  color: var(--ink-muted);
  font-size: 1.02rem;
  margin: 0.6rem 0 0.9rem;
}}

.masthead-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.1rem;
  font-family: var(--font-mono);
  font-size: 0.74rem;
  color: var(--ink-muted);
  margin-bottom: 1.6rem;
}}

.masthead-meta strong {{
  color: var(--ink);
  font-variant-numeric: tabular-nums;
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

.digest-pane {{ display: none; }}

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

.tp-link {{
  font-family: var(--font-mono);
  font-size: 0.76rem;
  color: var(--accent);
  text-decoration: none;
  white-space: nowrap;
}}
.tp-link:hover {{ text-decoration: underline; }}

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

.chip-slot0 {{ color: var(--c-slot0); background: var(--c-slot0-soft); }}
.chip-slot1 {{ color: var(--c-slot1); background: var(--c-slot1-soft); }}
.chip-slot2 {{ color: var(--c-slot2); background: var(--c-slot2-soft); }}
.chip-slot3 {{ color: var(--c-slot3); background: var(--c-slot3-soft); }}
.chip-slot4 {{ color: var(--c-slot4); background: var(--c-slot4-soft); }}
.chip-other {{ color: var(--c-other); background: var(--c-other-soft); }}

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

.feed-item-slot0 {{ border-left-color: var(--c-slot0); }}
.feed-item-slot1 {{ border-left-color: var(--c-slot1); }}
.feed-item-slot2 {{ border-left-color: var(--c-slot2); }}
.feed-item-slot3 {{ border-left-color: var(--c-slot3); }}
.feed-item-slot4 {{ border-left-color: var(--c-slot4); }}
.feed-item-other {{ border-left-color: var(--c-other); }}

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

.conflict-mark {{ color: var(--c-slot3); }}

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
footer.colophon strong {{ color: var(--c-slot3); }}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
</style>

<div class="wrap">
  <header class="masthead">
    <div class="masthead-eyebrow">KapturFlow &middot; Ohio Political News Intelligence</div>
    <p class="masthead-tagline">Local-model-generated summaries, analysis, and talking points &mdash; switch groups and subjects with the toggles below.</p>
    <p class="snapshot-note">This is a static snapshot, not a live feed &mdash; it reflects the data available at generation time ({generated}) and won't update on its own.</p>
  </header>

  {group_inputs}
  <div class="group-toggle">
    {group_labels}
  </div>

  <div class="group-panes">
    {group_panes}
  </div>

  <footer class="colophon">
    <p>KapturFlow tracks public reporting on each figure/issue above from wire, local, and official sources. Summaries, analysis, and talking points are generated by a local language model.</p>
    <p><strong>Verify before you repeat anything, especially talking points:</strong> the model can and does state specific numbers, dates, or vote outcomes that are not actually in the source reporting. Treat every figure here as unverified until you've checked the linked source.</p>
  </footer>
</div>
"""

if __name__ == "__main__":
    main()
