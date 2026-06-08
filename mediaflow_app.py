"""
MediaFlow dashboard — Iran/Hormuz crisis monitor.
Run with: streamlit run mediaflow_app.py
"""

import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import streamlit as st

HERE            = Path(__file__).parent
DATA_DIR        = Path(os.environ.get("DATA_DIR", HERE))
CLASSIFIED_FILE = DATA_DIR / "mediaflow_classified.json"
ITEMS_FILE      = DATA_DIR / "mediaflow_items.json"
LOCK_FILE       = DATA_DIR / ".collect_lock"

AUTO_COLLECT_INTERVAL_SECONDS = 900  # 15 minutes

ARC_COLOR = {
    "KINETIC":        "#c0392b",
    "DIPLOMATIC":     "#2980b9",
    "STRAIT_SHIPPING":"#d35400",
    "MARKET":         "#27ae60",
    "IEA_SUPPLY":     "#8e44ad",
}

ARC_LABEL = {
    "KINETIC":        "Kinetic",
    "DIPLOMATIC":     "Diplomatic",
    "STRAIT_SHIPPING":"Strait / Shipping",
    "MARKET":         "Market",
    "IEA_SUPPLY":     "IEA / Supply",
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


def inject_tz_converter() -> None:
    """Renders once per full page load. MutationObserver stays alive for the
    session and converts any data-utc spans the fragment adds later."""
    st.iframe(
        """
        <script>
        function convertTimestamps() {
            try {
                var els = window.parent.document.querySelectorAll('[data-utc]');
                els.forEach(function(el) {
                    var utc = el.getAttribute('data-utc');
                    if (!utc || el.getAttribute('data-converted')) return;
                    var dt = new Date(utc);
                    if (isNaN(dt)) return;
                    el.textContent = dt.toLocaleString('en-US', {
                        month: 'short', day: 'numeric',
                        hour: '2-digit', minute: '2-digit',
                        timeZoneName: 'short'
                    });
                    el.setAttribute('data-converted', '1');
                });
            } catch(e) {}
        }
        convertTimestamps();
        var observer = new MutationObserver(convertTimestamps);
        observer.observe(window.parent.document.body, {childList: true, subtree: true});
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
    link     = item.get("link", "#")

    arc_tag = ""
    if show_arc_tag and arc:
        label = ARC_LABEL.get(arc, arc)
        arc_tag = f'<span style="font-size:0.7em;color:{color};font-weight:600;text-transform:uppercase;letter-spacing:0.04em">{label}&ensp;</span>'

    conflict_mark = (
        '<span style="color:#c0392b;font-weight:700" title="Conflicting claims reported">⚡</span> '
        if conflict else ""
    )

    ts_attr = f'data-utc="{ts_iso}"' if ts_iso else ""

    st.markdown(
        f"""<div style="border-left:3px solid {color};padding:7px 12px;margin-bottom:10px;">
{arc_tag}<span style="color:#999;font-size:0.75em"><span {ts_attr}>{ts_display}</span> &nbsp;·&nbsp; {source}</span><br>
{conflict_mark}<span style="font-size:0.9em;line-height:1.4">{summary}</span><br>
<a href="{link}" target="_blank" style="font-size:0.75em;color:#999;text-decoration:none">→ source</a>
</div>""",
        unsafe_allow_html=True,
    )


# ── pipeline triggers ─────────────────────────────────────────────────────────

def run_collect() -> None:
    import rss_collect
    rss_collect.run()


def run_classify() -> int:
    import mediaflow_classify
    return mediaflow_classify.run()


def maybe_collect() -> None:
    """Run collect+classify if enough time has passed since the last run."""
    last = st.session_state.get("last_collect", 0)
    if time.time() - last < AUTO_COLLECT_INTERVAL_SECONDS:
        return
    if LOCK_FILE.exists():
        return
    try:
        LOCK_FILE.touch()
        run_collect()
        run_classify()
        st.session_state["last_collect"] = time.time()
    finally:
        LOCK_FILE.unlink(missing_ok=True)


# ── live feed fragment ────────────────────────────────────────────────────────

@st.fragment(run_every=AUTO_COLLECT_INTERVAL_SECONDS)
def live_feed(limit: int, conflicts_only: bool) -> None:
    """Collects and renders the feed. Runs on a timer without a full page
    rerun, so the timezone converter iframe is never destroyed."""
    maybe_collect()

    items = load_classified()

    if not items:
        st.info("No classified items yet. Click 'Update feed' in the sidebar.")
        return

    if conflicts_only:
        items = [i for i in items if i.get("conflict")]

    arc_keys = list(ARC_LABEL.keys())
    other_items = [i for i in items if i.get("arc") not in ARC_LABEL]
    tab_arc_count = len(arc_keys) + (1 if other_items else 0)
    all_limit = limit * tab_arc_count
    total_items = len(items)
    visible_all = min(total_items, all_limit)

    tab_labels = [f"All ({visible_all}/{total_items})"]
    for arc in arc_keys:
        count = sum(1 for i in items if i.get("arc") == arc)
        tab_labels.append(f"{ARC_LABEL[arc]} ({min(limit, count)}/{count})")
    if other_items:
        tab_labels.append(f"Other / Unmapped ({min(limit, len(other_items))}/{len(other_items)})")
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        subset = items[:all_limit]
        hidden = total_items - len(subset)
        if hidden:
            st.caption(f"Showing newest {len(subset)} of {total_items}; {hidden} older items hidden by the item limit.")
        for item in subset:
            render_item(item, show_arc_tag=True)

    for tab, arc in zip(tabs[1:], arc_keys):
        with tab:
            arc_items = [i for i in items if i.get("arc") == arc]
            subset = arc_items[:limit]
            if not subset:
                st.caption("No items.")
            elif len(arc_items) > len(subset):
                st.caption(f"Showing newest {len(subset)} of {len(arc_items)}; older items hidden by the item limit.")
            for item in subset:
                render_item(item, show_arc_tag=False)

    if other_items:
        with tabs[-1]:
            subset = other_items[:limit]
            if len(other_items) > len(subset):
                st.caption(f"Showing newest {len(subset)} of {len(other_items)}; older items hidden by the item limit.")
            for item in subset:
                render_item(item, show_arc_tag=True)


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="MediaFlow — Iran/Hormuz",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Rendered once per full page load — MutationObserver stays alive
    # for the entire session, converting timestamps as the fragment adds them.
    inject_tz_converter()

    st.markdown(
        """<style>
        [data-testid="stAppViewContainer"] { background: #fff; }
        [data-testid="stSidebar"] { background: #fafafa; }
        .stTabs [data-baseweb="tab-list"] { gap: 4px; }
        .stTabs [data-baseweb="tab"] { padding: 6px 14px; }
        </style>""",
        unsafe_allow_html=True,
    )

    # ── sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("**MediaFlow**")
        st.caption("Iran / Hormuz · June 2026")
        st.divider()

        if st.button("Update feed", use_container_width=True):
            with st.spinner("Fetching feeds…"):
                run_collect()
            with st.spinner("Classifying new items…"):
                classified = run_classify()
            st.session_state["last_collect"] = time.time()
            st.toast(f"Feed updated. {classified} new items classified.")
            st.rerun()

        st.divider()

        limit = st.slider("Items per arc", 10, 100, 40, 10)
        conflicts_only = st.checkbox("Conflict items only")

        st.divider()

        n_items, n_classified = item_counts()
        st.markdown(f"**{n_items}** collected &nbsp; **{n_classified}** classified")
        if CLASSIFIED_FILE.exists():
            mtime = datetime.fromtimestamp(CLASSIFIED_FILE.stat().st_mtime, tz=timezone.utc)
            st.caption(f"Updated {mtime.strftime('%H:%M UTC')}")

    # ── header ────────────────────────────────────────────────────────────────
    st.markdown("### MediaFlow &nbsp;·&nbsp; Iran / Hormuz")
    st.divider()

    # ── live feed (collect + display in one fragment) ─────────────────────────
    live_feed(limit=limit, conflicts_only=conflicts_only)


if __name__ == "__main__":
    main()
