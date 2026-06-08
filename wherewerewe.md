# Where We Were — Session Summary
Date: 2026-06-08
Project: Mooper Oil Crisis Model (MOCM)

---

## Sessions 1–3 Summary

Full detail on sessions 1–3 (feed discovery, ingest layer, classifier, initial dashboard)
is preserved in the CLAUDE.md data sources tables, explore/ probe outputs, and earlier
entries in this file. The system was fully operational locally by end of Session 3 with
1406 items collected and classified across 6 arcs.

---

## Session 4 — Railway Deployment + UI Polish

### Infrastructure — Fully Resolved

- Git repo initialized, pushed to private GitHub: OwenTanzer/oil-futures
- Deployed on Railway at `oil.moopertonic.net` (custom domain via Cloudflare)
- Volume attached at `/data`, `DATA_DIR=/data` set on web service
- `DATA_DIR` bug resolved — was reading repo JSON files instead of volume on every deploy
- IRNA removed from active feeds (confirmed live in probe but 12s timeout in production,
  0 items ever collected; documented in CLAUDE.md Tier 5 for future repair)
- Daily snapshot commits: `snapshots/YYYY-MM-DD/` pushed to GitHub via `worker.py`
- Background collector thread (`@st.cache_resource`) runs every 5 minutes independent
  of any browser session — collects immediately on startup, then on interval
- Display fragment polls every 30 seconds; page reloads every 2 minutes via iframe
  `setInterval` to support backgrounded tabs
- File-based lock prevents concurrent collect runs across multiple browser sessions

### Dashboard — Current State

**Live at:** `oil.moopertonic.net`

**Architecture:**
- Background thread: collect + classify every 5 min, server-side, no browser required
- Display fragment: re-renders every 30s from volume data
- Page reload: every 2 min via iframe, covers backgrounded tabs

**UI:**
- Title graphic: MEDIA FLOW / The Iran-Hormuz Crisis masthead (5:1 ratio PNG)
- Typography: Crimson Text for summaries and arc labels; Oxanium bold for metadata
  (timestamps, sources) and Update button; Streamlit default for tabs (Crimson pending)
- Header: compact single row — graphic (col1) + timestamp + Update button (col2)
- Tabs: All | Kinetic | Diplomatic | Maritime | Financial | Physical Supply | Other
  (All tab excludes UNMAPPED/Other items by default)
- Arc labels on All tab: colored, bold, 0.83em
- Timestamps: browser-local timezone via JS `data-utc` attribute + MutationObserver
- No sidebar, no Streamlit toolbar/header
- Confirmed working on both mobile and desktop

---

## Known Issues — Remaining

### MEDIUM
1. **Arc taxonomy needs refinement** — arc labels renamed (Maritime, Financial,
   Physical Supply) but classification quality on edge cases still unreviewed.
   Items about Iranian domestic politics, US domestic energy policy, and China
   demand signals landing inconsistently.

2. **Keyword system is static and coarse** — flat list, no arc weighting.
   Adaptive per-arc keyword sets with semi-daily review would reduce false
   positives and missed items.

3. **Crimson Text on tabs** — CSS specificity battle with Streamlit/BaseWeb;
   tab labels not yet confirmed rendering in Crimson Text despite multiple attempts.

4. **Reddit 429 rate limiting** — Reddit feeds occasionally hit HTTP 429 at
   5-minute collect intervals. Non-fatal (clean WARN) but items are missed.
   Consider backing off Reddit to every other cycle.

### LOW / DEFERRED
5. **Coverage gaps:**
   - Telegram OSINT channels (TankerTrackers, OSINTdefender) — highest-priority
     gap; fastest real-time kinetic signal before any paid source
   - MarineTraffic free API — direct AIS tanker data; still unprobed
   - Better Google News / Bing query tuning

6. **Event-level deduplication** — same event from 6 sources appears 6 times.

7. **Conflict flag cross-item detection** — flags intra-article denials only,
   not contradictions between separate articles.

---

## What Remains To Be Built

### MediaFlow — Near Term
1. Adaptive keyword system — arc-specific keyword sets, semi-daily review hook
2. Arc taxonomy review — manual pass through Kinetic arc; tune edge cases
3. Telegram/Discord OSINT layer — Phase 2 real-time kinetic signal

### ForcingFunction (Not Yet Started)
The classifier output has already surfaced several measurable variables
that belong in ForcingFunction:
- AIS dark tanker count (proxy for actual vs. reported Hormuz traffic)
- Per-vessel transit cost ($1.5M–$2M is a measurable threshold)
- OPEC+ quota hike count since closure (4 and counting)
- SPR repayment obligation (40M barrels owed)
- IRGC missile launch rate (kinetic escalation proxy)
- Iran oil revenue loss rate ($6bn and counting)

Historical calibration against the 1987–88 Tanker War and other reference
episodes (1973, 1990–91, 2011–12, 2019) is the foundational work needed
before variable weights can be assigned.
