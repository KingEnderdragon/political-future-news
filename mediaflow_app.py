"""
KapturFlow dashboard — live news monitor for tracked political figures.
Run with: streamlit run mediaflow_app.py
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import streamlit as st

import subjects

DIGEST_WINDOWS = [(7, "Last 7 days"), (30, "Last 30 days")]

AUTO_COLLECT_INTERVAL_SECONDS = 300     # 5 minutes
AUTO_DIGEST_INTERVAL_SECONDS  = 3600    # 1 hour — digest generation is heavier than classification

SLOT_COLORS = ["#2980b9", "#8e44ad", "#27ae60", "#c0392b", "#d35400", "#4a6572"]
OTHER_COLOR = "#999"


def arc_colors(subject: dict) -> dict[str, str]:
    return {arc: SLOT_COLORS[i % len(SLOT_COLORS)] for i, arc in enumerate(subject["arc_label"])}


# ── date helpers ──────────────────────────────────────────────────────────────

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


def fmt_dt_utc(s: str) -> tuple[str, str]:
    dt = parse_dt(s)
    if dt == datetime.min.replace(tzinfo=timezone.utc):
        return "—", ""
    return dt.strftime("%b %d  %H:%M UTC"), dt.strftime("%Y-%m-%dT%H:%M:%SZ")


DISPLAY_RELOAD_INTERVAL_MS = 2 * 60 * 1000  # 2 minutes


def inject_tz_converter() -> None:
    """Renders once per full page load. Handles timezone conversion and
    periodic page reload so backgrounded tabs stay current."""
    st.iframe(
        f"""
        <script>
        function convertTimestamps() {{
            try {{
                var els = window.parent.document.querySelectorAll('[data-utc]');
                els.forEach(function(el) {{
                    var utc = el.getAttribute('data-utc');
                    if (!utc || el.getAttribute('data-converted')) return;
                    var dt = new Date(utc);
                    if (isNaN(dt)) return;
                    el.textContent = dt.toLocaleString('en-US', {{
                        month: 'short', day: 'numeric',
                        hour: '2-digit', minute: '2-digit',
                        timeZoneName: 'short'
                    }});
                    el.setAttribute('data-converted', '1');
                }});
            }} catch(e) {{}}
        }}
        convertTimestamps();
        var observer = new MutationObserver(convertTimestamps);
        observer.observe(window.parent.document.body, {{childList: true, subtree: true}});

        // Reload every 2 minutes regardless of tab focus state.
        // Page reloads pick up fresh data from the background collector.
        setInterval(function() {{
            window.parent.location.reload();
        }}, {DISPLAY_RELOAD_INTERVAL_MS});
        </script>
        """,
        height=1,
    )


# ── data ──────────────────────────────────────────────────────────────────────

def load_classified(classified_file: Path) -> list[dict]:
    if not classified_file.exists():
        return []
    data = json.loads(classified_file.read_text(encoding="utf-8"))
    return sorted(data, key=lambda x: parse_dt(x.get("published", "")), reverse=True)


# ── rendering ─────────────────────────────────────────────────────────────────

def render_item(item: dict, subject: dict, colors: dict[str, str], show_arc_tag: bool = False) -> None:
    arc      = item.get("arc", "")
    color    = colors.get(arc, OTHER_COLOR)
    conflict = item.get("conflict", False)
    ts_display, ts_iso = fmt_dt_utc(item.get("published", ""))
    source   = item.get("source", "")
    author   = item.get("author", "")
    title    = item.get("title", "")
    summary  = item.get("arc_summary") or title
    analysis = item.get("arc_analysis") or ""

    arc_tag = ""
    if show_arc_tag and arc:
        label = subject["arc_label"].get(arc, arc)
        arc_tag = f'<span class="arc-label" style="font-size:0.83em;color:{color};font-weight:800;text-transform:uppercase;letter-spacing:0.04em">{label}&ensp;</span>'

    conflict_mark = (
        '<span style="color:#c0392b;font-weight:700" title="Conflicting claims reported">⚡</span> '
        if conflict else ""
    )

    analysis_html = (
        f'<br><span class="analysis-text" style="color:#666;font-size:0.9em;font-style:italic">{analysis}</span>'
        if analysis else ""
    )

    byline = f"{author}, {source}" if author else source
    citation = f'&ldquo;{title}&rdquo; &mdash; {byline}' if title else byline

    leg_note = item.get("legislative_note", "")
    leg_html = ""
    if leg_note and leg_note != "No clear connection":
        leg_html = (
            f'<div style="margin-top:6px;padding:5px 8px;background:#fdf3e3;border-left:2px solid #d3912b;">'
            f'<span style="font-size:0.65em;font-weight:800;color:#a06a1c;text-transform:uppercase;letter-spacing:0.04em">'
            f'⚠ Experimental — legislative context, unverified, may hallucinate</span><br>'
            f'<span style="font-size:0.82em;color:#7a5a2a">{leg_note}</span>'
            f'</div>'
        )

    ts_attr = f'data-utc="{ts_iso}"' if ts_iso else ""

    st.markdown(
        f"""<div style="border-left:3px solid {color};padding:7px 12px;margin-bottom:10px;">
{arc_tag}<span class="meta-text" style="color:#999;font-size:0.72em"><span {ts_attr}>{ts_display}</span> &nbsp;·&nbsp; {source}</span><br>
{conflict_mark}<span class="main-text">{summary}</span>{analysis_html}<br>
<span class="meta-text" style="font-size:0.72em;color:#999">{citation}</span>
{leg_html}
</div>""",
        unsafe_allow_html=True,
    )


def load_digests(digest_file: Path) -> dict:
    if not digest_file.exists():
        return {}
    return json.loads(digest_file.read_text(encoding="utf-8"))


def render_digest_window(digest: dict, subject: dict, colors: dict[str, str]) -> None:
    arc_keys = list(subject["arc_label"].keys())

    if not digest or not digest.get("arcs"):
        st.caption("No digest yet for this window. Click 'Generate digest' to build one.")
        return
    if digest.get("error"):
        st.error(digest["error"])
        return

    gen_dt, gen_iso = fmt_dt_utc(digest.get("generated_at", ""))
    window_days = digest.get("window_days", 7)
    period = "past week" if window_days <= 7 else f"past {window_days} days"
    st.markdown(
        f'<span class="meta-text" style="color:#999;font-size:0.72em">'
        f'generated <span data-utc="{gen_iso}">{gen_dt}</span> &nbsp;·&nbsp; {period}</span>',
        unsafe_allow_html=True,
    )
    for arc in arc_keys:
        entry = digest["arcs"].get(arc)
        if not entry:
            continue
        color = colors.get(arc, OTHER_COLOR)
        label = subject["arc_label"].get(arc, arc)
        summary = entry.get("critical_summary", "")
        analysis = entry.get("analysis", "")
        count = entry.get("item_count", 0)
        analysis_html = (
            f'<div class="analysis-text" style="color:#666;font-size:0.92em;font-style:italic;margin-top:4px">{analysis}</div>'
            if analysis else ""
        )
        points = entry.get("talking_points") or []
        points_html = ""
        if points:
            li_parts = []
            for p in points:
                text = p.get("text", "") if isinstance(p, dict) else str(p)
                title = p.get("title", "") if isinstance(p, dict) else ""
                source = p.get("source", "") if isinstance(p, dict) else ""
                author = p.get("author", "") if isinstance(p, dict) else ""
                byline = f"{author}, {source}" if author else source
                cite = f'&ldquo;{title}&rdquo; &mdash; {byline}' if title else byline
                cite_html = (
                    f' <span style="font-size:0.85em;color:#999">{cite}</span>'
                    if cite else ""
                )
                li_parts.append(f"<li>{text}{cite_html}</li>")
            items_html = "".join(li_parts)
            points_html = (
                f'<div style="margin-top:8px">'
                f'<span class="meta-text" style="color:#999;font-size:0.68em;text-transform:uppercase;letter-spacing:0.04em">Talking points</span>'
                f'<ul style="margin:4px 0 0 0;padding-left:1.2em">{items_html}</ul>'
                f'</div>'
            )
        st.markdown(
            f"""<div style="border-left:3px solid {color};padding:8px 14px;margin-bottom:14px;">
<span class="arc-label" style="font-size:0.85em;color:{color};font-weight:800;text-transform:uppercase;letter-spacing:0.04em">{label}</span>
<span class="meta-text" style="color:#999;font-size:0.72em">&nbsp;·&nbsp; {count} items</span>
<div class="main-text" style="margin-top:4px">{summary}</div>
{analysis_html}
{points_html}
</div>""",
            unsafe_allow_html=True,
        )


def render_weekly_digest(subject_slug: str, subject: dict, colors: dict[str, str]) -> None:
    paths = subjects.paths_for(subject_slug)
    digests = load_digests(paths["digest"])

    with st.expander("Digest — critical summary & analysis by category", expanded=True):
        st.caption(
            "⚠️ Generated by a local language model. Talking points in particular can state "
            "specific numbers, dates, or vote outcomes not actually present in the source "
            "reporting — verify against the cited article before repeating anything."
        )
        tabs = st.tabs([label for _, label in DIGEST_WINDOWS])
        for tab, (window_days, _) in zip(tabs, DIGEST_WINDOWS):
            with tab:
                render_digest_window(digests.get(str(window_days), {}), subject, colors)

        if st.button("Generate digest", key=f"gen_digest_{subject_slug}"):
            with st.spinner("Analyzing recent coverage…"):
                run_digest(subject_slug)
            st.rerun()


# ── pipeline triggers ─────────────────────────────────────────────────────────

def run_collect(subject_slug: str) -> None:
    import rss_collect
    rss_collect.run(subject_slug)


def run_classify(subject_slug: str) -> int:
    import mediaflow_classify
    return mediaflow_classify.run(subject_slug)


def run_digest(subject_slug: str) -> dict:
    import weekly_digest
    return weekly_digest.generate(subject_slug)


_digest_last: dict[str, float] = {}


def _collect_loop() -> None:
    global _digest_last
    # collect immediately on startup, then on interval, cycling every tracked subject
    while True:
        for slug in subjects.SUBJECT_ORDER:
            lock_file = subjects.paths_for(slug)["lock"]
            if lock_file.exists():
                continue
            try:
                lock_file.touch()
                run_collect(slug)
                run_classify(slug)
                if time.time() - _digest_last.get(slug, 0) >= AUTO_DIGEST_INTERVAL_SECONDS:
                    run_digest(slug)
                    _digest_last[slug] = time.time()
            except Exception as e:
                print(f"[collector:{slug}] error: {e}")
            finally:
                lock_file.unlink(missing_ok=True)
        time.sleep(AUTO_COLLECT_INTERVAL_SECONDS)


@st.cache_resource
def start_background_collector() -> None:
    """Starts once per server process — runs collect regardless of browser sessions."""
    t = threading.Thread(target=_collect_loop, daemon=True)
    t.start()


# ── live feed fragment ────────────────────────────────────────────────────────

ITEMS_PER_ARC = 40

@st.fragment(run_every=30)
def live_feed(subject_slug: str) -> None:
    """Display-only fragment. Polls for new data every 30s."""
    subject = subjects.get_subject(subject_slug)
    colors = arc_colors(subject)
    paths = subjects.paths_for(subject_slug)
    items = load_classified(paths["classified"])

    if not items:
        st.info("No classified items yet. Click 'Update' to seed the feed.")
        return

    arc_keys = list(subject["arc_label"].keys())
    other_items = [i for i in items if i.get("arc") not in subject["arc_label"]]
    all_limit = ITEMS_PER_ARC * len(arc_keys)

    main_items = [i for i in items if i.get("arc") in subject["arc_label"]]

    tab_labels = ["All"] + list(subject["arc_label"].values())
    if other_items:
        tab_labels.append("Other")
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        for item in main_items[:all_limit]:
            render_item(item, subject, colors, show_arc_tag=True)

    for tab, arc in zip(tabs[1:], arc_keys):
        with tab:
            arc_items = [i for i in items if i.get("arc") == arc]
            if not arc_items:
                st.caption("No items.")
            for item in arc_items[:ITEMS_PER_ARC]:
                render_item(item, subject, colors, show_arc_tag=False)

    if other_items:
        with tabs[-1]:
            for item in other_items[:ITEMS_PER_ARC]:
                render_item(item, subject, colors, show_arc_tag=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="KapturFlow: Ohio Political News Intelligence",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    start_background_collector()

    # Rendered once per full page load — MutationObserver stays alive
    # for the entire session, converting timestamps as the fragment adds them.
    inject_tz_converter()

    st.markdown(
        """<style>
        @import url('https://fonts.googleapis.com/css2?family=Crimson+Text:ital,wght@0,400;0,600;1,400&family=Oxanium:wght@700&display=swap');
        :root { color-scheme: light; }
        [data-testid="stAppViewContainer"] { background: #fff; }
        [data-testid="stSidebar"] { display: none; }
        [data-testid="collapsedControl"] { display: none; }
        [data-testid="stHeader"] { display: none; }
        [data-testid="stToolbar"] { display: none; }
        .block-container { padding-top: 0.4rem !important; padding-bottom: 0 !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 4px; margin-top: 0 !important; }
        .stTabs [data-baseweb="tab"] { padding: 6px 14px; }
        .stTabs [data-baseweb="tab"] *,
        .stTabs [data-baseweb="tab"] { font-family: 'Crimson Text', Georgia, serif !important; font-size: 0.98em !important; }
        hr { margin: 0.3rem 0 !important; }
        .stCaption { margin-bottom: 0 !important; }
        h1, h2, h3 { margin-top: 0 !important; margin-bottom: 0 !important; }
        body, .stMarkdown, .stCaption, button { font-family: 'Crimson Text', Georgia, serif !important; }
        .main-text { font-family: 'Crimson Text', Georgia, serif; font-size: 1.05em; line-height: 1.5; }
        .arc-label { font-family: 'Crimson Text', Georgia, serif; }
        .meta-text { font-family: 'Oxanium', monospace; font-weight: 700; }
        div[data-testid="stButton"] > button,
        div[data-testid="stButton"] > button > div,
        div[data-testid="stButton"] > button p {
            font-family: 'Oxanium', monospace !important;
            font-weight: 700 !important;
            font-size: 1.35em !important;
        }
        div[data-testid="stRadio"] > label { display: none; }
        div[data-testid="stRadio"] div[role="radiogroup"] { gap: 4px; }
        </style>""",
        unsafe_allow_html=True,
    )

    # ── group + subject toggle ───────────────────────────────────────────────
    group_labels = {"politicians": "Politicians", "issues": "Ohio Issues"}
    group = st.radio(
        "Group",
        options=list(subjects.SUBJECT_GROUPS.keys()),
        format_func=lambda g: group_labels[g],
        horizontal=True,
        key="group",
        label_visibility="collapsed",
    )
    group_slugs = subjects.SUBJECT_GROUPS[group]
    subject_names = {slug: subjects.get_subject(slug)["name"] for slug in group_slugs}
    subject_slug = st.radio(
        "Subject",
        options=group_slugs,
        format_func=lambda s: subject_names[s],
        horizontal=True,
        key=f"subject_slug_{group}",
        label_visibility="collapsed",
    )
    subject = subjects.get_subject(subject_slug)
    colors = arc_colors(subject)
    paths = subjects.paths_for(subject_slug)

    # ── header ────────────────────────────────────────────────────────────────
    updated_display = "—"
    updated_iso = ""
    if paths["classified"].exists():
        mtime = datetime.fromtimestamp(paths["classified"].stat().st_mtime, tz=timezone.utc)
        updated_display = mtime.strftime("%H:%M UTC")
        updated_iso = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")

    ts_attr = f'data-utc="{updated_iso}"' if updated_iso else ""

    col1, col2 = st.columns([7.8, 1.775])
    with col1:
        st.markdown(
            f"<h2 style='margin:0'>{subject['name']}</h2>"
            f"<div style='color:#999;font-size:0.9em'>{subject['subtitle']}</div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"<div style='text-align:center;font-size:0.58em;color:#999;font-family:\"Oxanium\",monospace;font-weight:700;white-space:nowrap;padding:1px 0 3px'>updated <span {ts_attr}>{updated_display}</span></div>",
            unsafe_allow_html=True,
        )
        if st.button("Update", type="secondary", use_container_width=True):
            with st.spinner("…"):
                run_collect(subject_slug)
                classified = run_classify(subject_slug)
            st.toast(f"{classified} new items classified.")
            st.rerun()

    # ── weekly digest ─────────────────────────────────────────────────────────
    render_weekly_digest(subject_slug, subject, colors)

    # ── live feed ─────────────────────────────────────────────────────────────
    live_feed(subject_slug)


if __name__ == "__main__":
    main()
