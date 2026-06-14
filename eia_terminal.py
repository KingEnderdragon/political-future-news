"""
EIA Petroleum Terminal — reads pre-built CSVs from data/ and renders charts.
Invoked by mediaflow_app.py when session_state.mode == "terminal".
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"

# Metadata for known series; unknown CSVs get generic defaults
SERIES_META: dict[str, dict] = {
    "commercial_crude_exSPR": {
        "label": "Commercial Crude Stocks (ex-SPR)",
        "unit": "Million Barrels",
        "color": "#00cc66",
    },
}

TERMINAL_CSS = """
<style>
[data-testid="stAppViewContainer"] { background: #0a0a0a !important; }
[data-testid="stSidebar"]          { display: none; }
[data-testid="stHeader"]           { display: none; }
[data-testid="stToolbar"]          { display: none; }
[data-testid="collapsedControl"]   { display: none; }
.block-container { padding-top: 1rem !important; }
h1, h2, h3, h4, label, p, div, span, button {
    color: #c0c0c0 !important;
    font-family: 'Oxanium', monospace !important;
}
[data-baseweb="select"] * { background: #111 !important; color: #c0c0c0 !important; }
[data-testid="stDateInput"] input { background: #111 !important; color: #c0c0c0 !important; }
hr { border-color: #333 !important; }
[data-testid="stExpander"] { background: #111 !important; border: 1px solid #333 !important; }
</style>
"""


@st.cache_data(ttl=300)
def load_all_series() -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    if not DATA_DIR.exists():
        return result
    for csv_path in sorted(DATA_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(csv_path, parse_dates=["data_date"])
            df = df.sort_values("data_date").reset_index(drop=True)
            result[csv_path.stem] = df
        except Exception:
            pass
    return result


def _inject_esc_listener() -> None:
    st.iframe(
        """
        <script>
        (function() {
            var doc = window.parent.document;

            function fireBack(e) {
                if (e.key !== 'Escape') return;
                var btn = doc.querySelector('.st-key-terminal_back button');
                if (btn) btn.click();
            }

            if (doc.__esc_fn__) doc.removeEventListener('keydown', doc.__esc_fn__);
            doc.__esc_fn__ = fireBack;
            doc.addEventListener('keydown', fireBack);

            function attachToIframes() {
                doc.querySelectorAll('iframe').forEach(function(f) {
                    try {
                        if (!f.__esc_t__) {
                            f.__esc_t__ = true;
                            f.contentDocument.addEventListener('keydown', fireBack);
                        }
                    } catch (ignore) {}
                });
            }
            attachToIframes();

            if (doc.__esc_obs__) { try { doc.__esc_obs__.disconnect(); } catch(_) {} }
            doc.__esc_obs__ = new MutationObserver(attachToIframes);
            doc.__esc_obs__.observe(doc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        height=1,
    )


def render_terminal() -> None:
    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)
    _inject_esc_listener()

    # ── header ────────────────────────────────────────────────────────────────
    col_back, col_title = st.columns([1, 9])
    with col_back:
        if st.button("← Back", key="terminal_back"):
            st.session_state.mode = "newscenter"
            st.rerun()
    with col_title:
        st.markdown(
            "<p style='font-size:1.1em;letter-spacing:0.12em;color:#555 !important;"
            "padding-top:6px;margin:0'>EIA PETROLEUM TERMINAL</p>",
            unsafe_allow_html=True,
        )

    st.markdown("<hr style='margin:6px 0 14px'>", unsafe_allow_html=True)

    # ── load data ─────────────────────────────────────────────────────────────
    series_data = load_all_series()

    if not series_data:
        st.warning("No data in data/ — run build_timeseries.py and commit the output.")
        return

    # ── controls ──────────────────────────────────────────────────────────────
    def label(key: str) -> str:
        return SERIES_META.get(key, {}).get("label", key.replace("_", " ").title())

    c1, c2, c3 = st.columns([3, 1.2, 1.2])

    with c1:
        selected = st.multiselect(
            "Series",
            options=list(series_data.keys()),
            default=list(series_data.keys())[:1],
            format_func=label,
            label_visibility="collapsed",
        )

    all_dates = pd.concat([series_data[k]["data_date"] for k in series_data])
    global_min = all_dates.min().date()
    global_max = all_dates.max().date()

    with c2:
        start = st.date_input("From", value=global_min, min_value=global_min,
                              max_value=global_max, label_visibility="collapsed")
    with c3:
        end = st.date_input("To", value=global_max, min_value=global_min,
                            max_value=global_max, label_visibility="collapsed")

    if not selected:
        st.caption("Select a series above.")
        return

    # ── chart ─────────────────────────────────────────────────────────────────
    fig = go.Figure()

    for key in selected:
        df = series_data[key]
        mask = (df["data_date"].dt.date >= start) & (df["data_date"].dt.date <= end)
        df_f = df[mask]
        val_col = next(c for c in df.columns if c != "data_date")
        meta = SERIES_META.get(key, {})

        fig.add_trace(go.Scatter(
            x=df_f["data_date"],
            y=df_f[val_col],
            mode="lines+markers",
            name=label(key),
            line=dict(color=meta.get("color", "#00aaff"), width=2),
            marker=dict(size=4),
            hovertemplate="%{x|%b %d %Y}<br>%{y:,.1f} MB<extra></extra>",
        ))

    unit = SERIES_META.get(selected[0], {}).get("unit", "MB") if len(selected) == 1 else "MB"

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0a0a0a",
        plot_bgcolor="#0d0d0d",
        font=dict(family="Oxanium, monospace", size=12, color="#999"),
        margin=dict(l=50, r=20, t=20, b=50),
        yaxis=dict(title=unit, gridcolor="#1a1a1a", zerolinecolor="#222"),
        xaxis=dict(gridcolor="#1a1a1a", zerolinecolor="#222"),
        legend=dict(orientation="h", y=-0.18, font=dict(size=11)),
        height=430,
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── raw data ──────────────────────────────────────────────────────────────
    with st.expander("Raw data"):
        for key in selected:
            df = series_data[key]
            mask = (df["data_date"].dt.date >= start) & (df["data_date"].dt.date <= end)
            val_col = next(c for c in df.columns if c != "data_date")
            st.caption(label(key))
            st.dataframe(
                df[mask][["data_date", val_col]]
                .rename(columns={"data_date": "Date", val_col: f"Value ({unit})"}),
                hide_index=True,
                use_container_width=True,
            )
