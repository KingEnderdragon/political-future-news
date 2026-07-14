"""
KapturFlow dashboard — Rep. Marcy Kaptur (D-OH-9) live news monitor.
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

HERE            = Path(__file__).parent
DATA_DIR        = Path(os.environ.get("DATA_DIR", HERE))
CLASSIFIED_FILE = DATA_DIR / "mediaflow_classified.json"
ITEMS_FILE      = DATA_DIR / "mediaflow_items.json"
DIGEST_FILE     = DATA_DIR / "mediaflow_digest.json"
LOCK_FILE       = DATA_DIR / ".collect_lock"

DIGEST_WINDOWS = [(7, "Last 7 days"), (30, "Last 30 days")]

AUTO_COLLECT_INTERVAL_SECONDS = 300     # 5 minutes
AUTO_DIGEST_INTERVAL_SECONDS  = 3600    # 1 hour — digest generation is heavier than classification

ARC_COLOR = {
    "LEGISLATION": "#2980b9",
    "COMMITTEE":   "#8e44ad",
    "DISTRICT":    "#27ae60",
    "CAMPAIGN":    "#c0392b",
    "MEDIA":       "#d35400",
}

ARC_LABEL = {
    "LEGISLATION": "Legislation",
    "COMMITTEE":   "Committee",
    "DISTRICT":    "District",
    "CAMPAIGN":    "Campaign",
    "MEDIA":       "Media",
}


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

def load_classified() -> list[dict]:
    if not CLASSIFIED_FILE.exists():
        return []
    data = json.loads(CLASSIFIED_FILE.read_text(encoding="utf-8"))
    return sorted(data, key=lambda x: parse_dt(x.get("published", "")), reverse=True)


def item_counts() -> tuple[int, int]:
    n_items = 0
    n_classified = 0
    if ITEMS_FILE.exists():
        n_items = len(json.loads(ITEMS_FILE.read_text(encoding="utf-8")))
    if CLASSIFIED_FILE.exists():
        n_classified = len(json.loads(CLASSIFIED_FILE.read_text(encoding="utf-8")))
    return n_items, n_classified


# ── rendering ─────────────────────────────────────────────────────────────────

def render_item(item: dict, show_arc_tag: bool = False) -> None:
    arc      = item.get("arc", "")
    color    = ARC_COLOR.get(arc, "#999")
    conflict = item.get("conflict", False)
    ts_display, ts_iso = fmt_dt_utc(item.get("published", ""))
    source   = item.get("source", "")
    summary  = item.get("arc_summary") or item.get("title", "")
    analysis = item.get("arc_analysis") or ""
    link     = item.get("link", "#")

    arc_tag = ""
    if show_arc_tag and arc:
        label = ARC_LABEL.get(arc, arc)
        arc_tag = f'<span class="arc-label" style="font-size:0.83em;color:{color};font-weight:800;text-transform:uppercase;letter-spacing:0.04em">{label}&ensp;</span>'

    conflict_mark = (
        '<span style="color:#c0392b;font-weight:700" title="Conflicting claims reported">⚡</span> '
        if conflict else ""
    )

    analysis_html = (
        f'<br><span class="analysis-text" style="color:#666;font-size:0.9em;font-style:italic">{analysis}</span>'
        if analysis else ""
    )

    ts_attr = f'data-utc="{ts_iso}"' if ts_iso else ""

    st.markdown(
        f"""<div style="border-left:3px solid {color};padding:7px 12px;margin-bottom:10px;">
{arc_tag}<span class="meta-text" style="color:#999;font-size:0.72em"><span {ts_attr}>{ts_display}</span> &nbsp;·&nbsp; {source}</span><br>
{conflict_mark}<span class="main-text">{summary}</span>{analysis_html}<br>
<a href="{link}" target="_blank" class="meta-text" style="font-size:0.72em;color:#999;text-decoration:none">→ source</a>
</div>""",
        unsafe_allow_html=True,
    )


def load_digests() -> dict:
    if not DIGEST_FILE.exists():
        return {}
    return json.loads(DIGEST_FILE.read_text(encoding="utf-8"))


def render_digest_window(digest: dict) -> None:
    arc_keys = list(ARC_LABEL.keys())

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
        color = ARC_COLOR.get(arc, "#999")
        label = ARC_LABEL.get(arc, arc)
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
                link = p.get("link", "") if isinstance(p, dict) else ""
                source = p.get("source", "") if isinstance(p, dict) else ""
                link_html = (
                    f' <a href="{link}" target="_blank" style="font-size:0.85em;color:#999;text-decoration:none">'
                    f'&rarr; {source or "source"}</a>'
                    if link else ""
                )
                li_parts.append(f"<li>{text}{link_html}</li>")
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


def render_weekly_digest() -> None:
    digests = load_digests()

    with st.expander("Digest — critical summary & analysis by category", expanded=True):
        st.caption(
            "⚠️ Generated by a local language model. Talking points in particular can state "
            "specific numbers, dates, or vote outcomes not actually present in the source "
            "reporting — verify against the linked source before repeating anything."
        )
        tabs = st.tabs([label for _, label in DIGEST_WINDOWS])
        for tab, (window_days, _) in zip(tabs, DIGEST_WINDOWS):
            with tab:
                render_digest_window(digests.get(str(window_days), {}))

        if st.button("Generate digest", key="gen_digest"):
            with st.spinner("Analyzing recent coverage…"):
                run_digest()
            st.rerun()


# ── pipeline triggers ─────────────────────────────────────────────────────────

def run_collect() -> None:
    import rss_collect
    rss_collect.run()


def run_classify() -> int:
    import mediaflow_classify
    return mediaflow_classify.run()


def run_digest() -> dict:
    import weekly_digest
    return weekly_digest.generate()


_collect_last: float = 0.0
_digest_last: float = 0.0
_collect_lock = threading.Lock()


def _collect_loop() -> None:
    global _collect_last, _digest_last
    # collect immediately on startup, then on interval
    while True:
        if LOCK_FILE.exists():
            time.sleep(30)
            continue
        try:
            LOCK_FILE.touch()
            run_collect()
            run_classify()
            _collect_last = time.time()
            if time.time() - _digest_last >= AUTO_DIGEST_INTERVAL_SECONDS:
                run_digest()
                _digest_last = time.time()
        except Exception as e:
            print(f"[collector] error: {e}")
        finally:
            LOCK_FILE.unlink(missing_ok=True)
        time.sleep(AUTO_COLLECT_INTERVAL_SECONDS)


@st.cache_resource
def start_background_collector() -> None:
    """Starts once per server process — runs collect regardless of browser sessions."""
    t = threading.Thread(target=_collect_loop, daemon=True)
    t.start()


# ── live feed fragment ────────────────────────────────────────────────────────

ITEMS_PER_ARC = 40

@st.fragment(run_every=30)
def live_feed() -> None:
    """Display-only fragment. Polls for new data every 30s."""

    items = load_classified()

    if not items:
        st.info("No classified items yet. Click 'Update feed' to seed the feed.")
        return

    arc_keys = list(ARC_LABEL.keys())
    other_items = [i for i in items if i.get("arc") not in ARC_LABEL]
    all_limit = ITEMS_PER_ARC * len(arc_keys)
    total_items = len(items)
    visible_all = min(total_items, all_limit)

    main_items = [i for i in items if i.get("arc") in ARC_LABEL]

    tab_labels = ["All"] + list(ARC_LABEL.values())
    if other_items:
        tab_labels.append("Other")
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        for item in main_items[:all_limit]:
            render_item(item, show_arc_tag=True)

    for tab, arc in zip(tabs[1:], arc_keys):
        with tab:
            arc_items = [i for i in items if i.get("arc") == arc]
            if not arc_items:
                st.caption("No items.")
            for item in arc_items[:ITEMS_PER_ARC]:
                render_item(item, show_arc_tag=False)

    if other_items:
        with tabs[-1]:
            for item in other_items[:ITEMS_PER_ARC]:
                render_item(item, show_arc_tag=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="KapturFlow: Rep. Marcy Kaptur (OH-9)",
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
        </style>""",
        unsafe_allow_html=True,
    )

    # ── header ────────────────────────────────────────────────────────────────
    updated_display = "—"
    updated_iso = ""
    if CLASSIFIED_FILE.exists():
        mtime = datetime.fromtimestamp(CLASSIFIED_FILE.stat().st_mtime, tz=timezone.utc)
        updated_display = mtime.strftime("%H:%M UTC")
        updated_iso = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")

    ts_attr = f'data-utc="{updated_iso}"' if updated_iso else ""

    col1, col2 = st.columns([7.8, 1.775])
    with col1:
        st.markdown(
            "<h2 style='margin:0'>KapturFlow</h2>"
            "<div style='color:#999;font-size:0.9em'>Rep. Marcy Kaptur &middot; Ohio's 9th District</div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"<div style='text-align:center;font-size:0.58em;color:#999;font-family:\"Oxanium\",monospace;font-weight:700;white-space:nowrap;padding:1px 0 3px'>updated <span {ts_attr}>{updated_display}</span></div>",
            unsafe_allow_html=True,
        )
        if st.button("Update", type="secondary", use_container_width=True):
            with st.spinner("…"):
                run_collect()
                classified = run_classify()
            st.toast(f"{classified} new items classified.")
            st.rerun()

    # ── weekly digest ─────────────────────────────────────────────────────────
    render_weekly_digest()

    # ── live feed ─────────────────────────────────────────────────────────────
    live_feed()


if __name__ == "__main__":
    main()
