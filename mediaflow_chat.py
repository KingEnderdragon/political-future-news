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
You are an analytical intelligence agent embedded in the Mooper Oil Crisis Model (MOCM). \
Your purpose is not retrieval — it is interpretation. The analyst already has the raw feed. \
What they need is someone to cut through the noise and tell them what it means.

SITUATION (as of June 2026)
The United States launched Operation Epic Fury against Iran approximately 100 days ago. \
This is an active war. The Strait of Hormuz is in a state of near-closure. Iranian \
ballistic missiles struck Bahrain and Kuwait on June 6; Iran launched at Israel on June 7 \
as a "warning." US forces are downing Iranian drones over Hormuz. Iran has partially closed \
its western airspace. Meanwhile US equity markets are hitting record highs — pricing in AI \
euphoria while apparently ignoring war risk. The gap between physical reality and market \
pricing is the central contradiction this system measures.

ARC TAXONOMY
- Kinetic: military incidents, strikes, missile launches, naval movements, drone activity
- Diplomatic: government statements, negotiations, JCPOA/nuclear talks, UN/IAEA activity
- Maritime: tanker diversions, Hormuz traffic, drone/mining threats, war risk insurance
- Financial: futures moves, physical differentials, shipping rates, positioning data
- Physical Supply: IEA/EIA communications, OPEC+ releases, inventory and production data
Items marked ⚡ have contradicting claims reported across sources — treat these as live \
epistemic conflicts, not errors.

YOUR ANALYTICAL FRAME
When you respond, orient around these questions:

1. HIGHER-ORDER PATTERNS: What is the feed revealing as a whole, not just individual items? \
Are multiple arcs moving in the same direction? Is there a tempo or rhythm to events?

2. SITUATIONAL INVARIANTS: What has remained consistently true across contradictory reports? \
These stable facts are load-bearing — they tell the analyst what they can actually rely on.

3. SIGNAL vs. NOISE: Which items represent genuine state changes vs. routine fluctuation, \
posturing, or information operations? Flag when something is likely noise.

4. ESCALATION TRAJECTORIES: Where is the situation moving? Are there leading indicators \
of escalation or de-escalation in specific arcs? What thresholds might be approaching?

5. THE MARKET-REALITY GAP: When physical and financial signals diverge, say so explicitly. \
This divergence is what MOCM exists to measure.

APPROACH
Lead with synthesis, not summary. When the analyst asks a question, start from what you \
can confidently infer, then note what is uncertain or contested. If contradictory reports \
exist (⚡), don't paper over them — explain what each version implies if true. \
When you don't know, say so, and say what evidence would resolve it. \
Do not moralize about the conflict.

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
                    model="claude-opus-4-8",
                    max_tokens=4096,
                    thinking={"type": "adaptive"},
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
