"""
MediaFlow conversational agent — natural language interface over the classified feed.
Invoked by mediaflow_app.py when session_state.mode == "chat".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import streamlit as st

HERE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", HERE))
CLASSIFIED_FILE = DATA_DIR / "mediaflow_classified.json"

ARC_LABEL = {
    "KINETIC":         "Kinetic",
    "DIPLOMATIC":      "Diplomatic",
    "STRAIT_SHIPPING": "Maritime",
    "MARKET":          "Financial",
    "IEA_SUPPLY":      "Physical Supply",
}

_SYSTEM_TEMPLATE = """\
You are a MediaFlow intelligence agent embedded in the Mooper Oil Crisis Model (MOCM). \
Your role is to help the analyst understand and query the MediaFlow news feed — a \
real-time monitor of the US-Iran war and its effects on the Strait of Hormuz and \
global oil markets.

SITUATION (as of June 2026)
The United States launched Operation Epic Fury against Iran approximately 100 days ago. \
This is an active war, not a latent risk. The Strait of Hormuz is in a state of \
near-closure. Iranian ballistic missiles struck US allies Bahrain and Kuwait on June 6. \
Iran launched missiles at Israel on June 7 as a "warning." US forces have downed Iranian \
drones targeting Hormuz shipping traffic. Iran has partially closed its western airspace. \
US equity markets are still hitting record highs, apparently pricing in AI euphoria over \
war risk. The gap between physical reality and market pricing is the central problem this \
system measures.

ARC TAXONOMY
- Kinetic: military incidents, strikes, missile launches, naval movements, drone activity
- Diplomatic: government statements, negotiations, JCPOA/nuclear talks, UN/IAEA activity
- Maritime: tanker diversions, Hormuz traffic, drone/mining threats, war risk insurance
- Financial: futures moves, physical differentials, shipping rates, positioning data
- Physical Supply: IEA/EIA communications, OPEC+ releases, inventory and production data
Items marked ⚡ have contradicting claims reported across sources.

INSTRUCTIONS
Answer questions about the feed — summarize an arc, identify patterns, flag escalation \
signals, compare current reports to historical analogues, or help the analyst think through \
what the data implies. Be concise and factual. When a question goes beyond what the feed \
shows, say so clearly rather than speculating. Do not editorialize about the war itself.

CURRENT FEED (most recent {n} items across all arcs, newest first)
{context}
"""

CHAT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Crimson+Text:ital,wght@0,400;0,600;1,400&family=Oxanium:wght@700&display=swap');
[data-testid="stAppViewContainer"] { background: #fff; }
[data-testid="stSidebar"]          { display: none; }
[data-testid="collapsedControl"]   { display: none; }
[data-testid="stHeader"]           { display: none; }
[data-testid="stToolbar"]          { display: none; }
.block-container { padding-top: 0.6rem !important; padding-bottom: 1rem !important; }
body, p, div, span, .stMarkdown {
    font-family: 'Crimson Text', Georgia, serif !important;
}
.stChatMessage p, .stChatMessage div {
    font-family: 'Crimson Text', Georgia, serif !important;
    font-size: 1.05em !important;
    line-height: 1.55 !important;
}
div[data-testid="stButton"] > button,
div[data-testid="stButton"] > button > div,
div[data-testid="stButton"] > button p {
    font-family: 'Oxanium', monospace !important;
    font-weight: 700 !important;
}
[data-testid="stChatInput"] textarea {
    font-family: 'Crimson Text', Georgia, serif !important;
    font-size: 1.05em !important;
}
</style>
"""


def _parse_dt(s: str) -> datetime:
    if not s or s == "unknown":
        return datetime.min.replace(tzinfo=timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _build_context(max_items: int = 150) -> tuple[str, int]:
    """Return (formatted context string, item count). Skips UNMAPPED."""
    if not CLASSIFIED_FILE.exists():
        return "(No feed data available yet.)", 0

    raw = json.loads(CLASSIFIED_FILE.read_text(encoding="utf-8"))
    items = sorted(raw, key=lambda x: _parse_dt(x.get("published", "")), reverse=True)

    lines: list[str] = []
    for item in items:
        arc = item.get("arc", "")
        if arc == "UNMAPPED":
            continue
        if len(lines) >= max_items:
            break
        label = ARC_LABEL.get(arc, arc)
        dt = _parse_dt(item.get("published", ""))
        date_str = dt.strftime("%Y-%m-%d %H:%M UTC") if dt != datetime.min.replace(tzinfo=timezone.utc) else "unknown"
        source = item.get("source", "?")
        summary = item.get("arc_summary") or item.get("title", "")
        conflict = " ⚡" if item.get("conflict") else ""
        lines.append(f"[{label}] {date_str} | {source}{conflict}: {summary}")

    if not lines:
        return "(No classified items yet.)", 0
    return "\n".join(lines), len(lines)


def _inject_chat_js() -> None:
    """ESC → back button. Same guard pattern as terminal JS."""
    st.iframe(
        """
        <script>
        (function() {
            var doc = window.parent.document;
            function fireBack(e) {
                if (e.key !== 'Escape') return;
                var btn = doc.querySelector('.st-key-chat_back button');
                if (btn) btn.click();
            }
            if (doc.__chat_esc__) doc.removeEventListener('keydown', doc.__chat_esc__);
            doc.__chat_esc__ = fireBack;
            doc.addEventListener('keydown', fireBack);

            function attachToIframes() {
                doc.querySelectorAll('iframe').forEach(function(f) {
                    try {
                        if (!f.__chat_esc__) {
                            f.__chat_esc__ = true;
                            f.contentDocument.addEventListener('keydown', fireBack);
                        }
                    } catch (ignore) {}
                });
            }
            attachToIframes();
            if (doc.__chat_obs__) { try { doc.__chat_obs__.disconnect(); } catch(_) {} }
            doc.__chat_obs__ = new MutationObserver(attachToIframes);
            doc.__chat_obs__.observe(doc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        height=1,
    )


def render_chat() -> None:
    st.markdown(CHAT_CSS, unsafe_allow_html=True)
    _inject_chat_js()

    # ── header ────────────────────────────────────────────────────────────────
    col_back, col_title = st.columns([1, 9])
    with col_back:
        if st.button("← Back", key="chat_back"):
            st.session_state.mode = "newscenter"
            st.rerun()
    with col_title:
        st.markdown(
            "<p style='font-family:\"Oxanium\",monospace;font-weight:700;font-size:1.1em;"
            "color:#999;padding-top:6px;margin:0;letter-spacing:0.06em'>MEDIAFLOW AGENT</p>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr style='margin:6px 0 10px'>", unsafe_allow_html=True)

    # ── chat history ──────────────────────────────────────────────────────────
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── input ─────────────────────────────────────────────────────────────────
    if prompt := st.chat_input("Ask about the feed…"):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        context, n = _build_context()
        system = _SYSTEM_TEMPLATE.format(context=context, n=n)

        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.chat_messages
        ]

        try:
            client = anthropic.Anthropic()
            with st.chat_message("assistant"):
                with client.messages.stream(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1024,
                    system=system,
                    messages=api_messages,
                ) as stream:
                    response_text = st.write_stream(stream.text_stream)
            st.session_state.chat_messages.append(
                {"role": "assistant", "content": response_text}
            )
        except anthropic.AuthenticationError:
            st.error("ANTHROPIC_API_KEY missing or invalid.")
        except Exception as e:
            st.error(f"API error: {e}")
