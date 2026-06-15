# Where We Were — Session Summary
Date: 2026-06-14
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
- Header: compact single row — graphic (col1) + timestamp/Update/nav buttons (col2)
- col2 button row: Update (full-width) + 1×4 icon buttons below: ⊹ (terminal), □ □ □ (placeholders)
- Tabs: All | Kinetic | Diplomatic | Maritime | Financial | Physical Supply | Other
  (All tab excludes UNMAPPED/Other items by default)
- Arc labels on All tab: colored, bold, 0.83em
- Timestamps: browser-local timezone via JS `data-utc` attribute + MutationObserver
- No sidebar, no Streamlit toolbar/header
- Confirmed working on both mobile and desktop

---

## Session 5 — EIA Petroleum Terminal

### What Was Built

**EIA data pipeline** (lives in local `~/Documents/computational_projects/oil_futures/`,
NOT in this repo — raw CSVs are gitignored there):
- `download_wpsr.py` — downloads EIA Weekly Petroleum Status Report CSVs from the
  public archive. Idempotent, 0.3s polite delay. Handles holiday-shifted Thursday
  releases via `HOLIDAY_OVERRIDES` dict. Accepts `start` / `end` date args.
  2026 data (23 weeks) already downloaded. 2016–2025 download running in background.
- `build_timeseries.py` — parses Table 1 CSVs, extracts named rows, writes clean
  `data_date, value` CSVs to `EIAreport_data/` (local) and `data/` (repo).

**Processed data committed to this repo** (`data/`):
- `data/commercial_crude_exSPR.csv` — 23 weekly obs, Jan–Jun 2026, units: million barrels

**Terminal page** (`eia_terminal.py`):
- Dark theme (#0a0a0a), Oxanium font
- Auto-discovers all CSVs in `data/` — adding a new series is just committing a CSV
- Multiselect series picker, date range pickers, Plotly dark-theme line chart
- Raw data expander below chart
- `SERIES_META` dict for per-series labels, units, chart colors

**Navigation / hotkeys** (in `mediaflow_app.py`):
- `T` → enter terminal (JS listener via `st.iframe`, uses `.st-key-goto_terminal` CSS selector)
- `Esc` → back to newscenter (JS listener via `st.iframe`, uses `.st-key-terminal_back`)
- ⊹ button in header also enters terminal (mouse fallback)
- ← Back button also exits terminal (mouse fallback)
- Hotkey JS pattern: replace-not-guard — stores listener/observer refs on parent document
  and replaces them each render, avoiding the dead-iframe guard bug where T stopped
  working after the first round-trip

### Known Issues — Terminal (Session 5, now resolved)

- ~~Aesthetic mismatch~~ — resolved in Session 6 (light mode, shared font/color language)
- 3 dummy buttons (□) in the nav row are placeholders with no function yet.
- NYMEX futures gap: Table 13 data unavailable after April 2024 in WPSR; needs
  separate CME or other source.
- No live refresh: terminal reads committed CSVs only. Latest week appears only
  after running the pipeline and committing. Could add a live EIA fetch button later.

---

## Session 6 — Mooper Terminal (Command-Line Interface)

### What Was Built

**Terminal redesigned as a real CLI** (`eia_terminal.py`):
- `st.chat_input` at the bottom provides a persistent command prompt
- Command history accumulates in session state and renders inline (text + charts)
- Blinking block cursor (CSS `step-end` animation) at the bottom of history
- Auto-focus: input grabs keyboard on load and after any click (80ms delay via JS)
- ESC → Back still works; `back`/`exit` commands also navigate out
- Light mode throughout — white background, Oxanium font, dark text — matches newscenter
- Title: MOOPER TERMINAL (header only; no restatement in startup message)
- Plotly charts switched to `plotly_white` theme

**Data pipeline expanded** (`build_timeseries.py` in `oil_futures/`):
- Now extracts 5 series; all 92 obs (2016–2026 complete)
- Added `col1_endswith` match mode to avoid sub-row false positives
  (critical for crude imports: avoids "Imports by SPR", "Imports into SPR by Others")

**Data committed to `data/`** (all 92 weekly obs, 2016–2026):
- `commercial_crude_exSPR.csv` — stocks, Million Barrels
- `total_products_supplied.csv` — demand proxy, kb/d
- `crude_exports.csv` — crude oil exports, kb/d
- `crude_imports.csv` — crude oil imports, kb/d
- `crude_production.csv` — domestic crude production, kb/d

**Terminal commands:**
- `stocks [year|y1-y2]` — commercial crude stocks (ex-SPR)
- `demand [year|y1-y2]` — total products supplied (aliases: supply, products)
- `exports [year|y1-y2]` — crude oil exports
- `imports [year|y1-y2]` — crude oil imports
- `production [year|y1-y2]` — domestic crude production (alias: prod)
- `aggregate_demand [year|y1-y2]` — products supplied + exports; total draw (aliases: agg, total_demand)
- `aggregate_supply [year|y1-y2]` — imports + production; total supply input (aliases: agg_supply, total_supply)
- Aggregate charts show individual series + dotted black sum line
- `ls`, `help`, `clear`, `back`/`exit` also available

### Known Issue — Accounting Level Mixing (resolved in Session 7)

~~The current series selection mixes two different levels of the petroleum supply chain~~
~~and this needs to be thought through carefully before treating the aggregates as signals.~~

Resolved: `demand` and `aggregate_demand` now use `refinery_input` (crude oil input to
refineries, WPSR Table 1 row 38) instead of `total_products_supplied`. See Session 7.

---

## Session 7 — Refinery Input Series + Pipeline Documentation

### What Changed

**Demand series corrected** (`eia_terminal.py`):
- `demand` command now plots `refinery_input` (crude oil input to refineries, kb/d)
  instead of `total_products_supplied`
- `aggregate_demand` now = refinery_input + crude_exports (both at the crude level,
  consistent with aggregate_supply = imports + production)
- Aliases updated: `demand/refinery/runs` → `refinery_input`; `supply/products` dropped
- This resolves the Session 6 accounting-level mixing issue: all four series in the two
  aggregates are now consistently upstream crude flows

**New series added** (`build_timeseries.py` + `data/`):
- `refinery_input.csv` — 97 weekly obs, 2016–2026, kb/d
  - Extracted from WPSR Table 1 row 38: `col0="Crude Oil Supply "`,
    `col1_contains="Crude Oil Input to Refineries"`, `col_idx=2`
- All existing CSVs also gained 5 rows (2017-07-21 through 2017-08-18) that were
  missing from the prior build

**Pipeline documented** (`oil_futures/CLAUDE.md` — local, not in this repo):
- Table 1 two-column row format explained
- Row numbers for all current series
- Full instructions for adding a new series
- Holiday override pattern for download_wpsr.py

### Data Now in `data/`
- `commercial_crude_exSPR.csv` — stocks, Million Barrels (97 obs)
- `refinery_input.csv` — crude input to refineries, kb/d (97 obs) ← new
- `crude_exports.csv` — crude oil exports, kb/d (97 obs)
- `crude_imports.csv` — crude oil imports, kb/d (97 obs)
- `crude_production.csv` — domestic crude production, kb/d (97 obs)
- `total_products_supplied.csv` — retained in build but no longer used by terminal

### Terminal Commands (current state)
- `stocks [year|y1-y2]` — commercial crude stocks (ex-SPR), MB
- `demand [year|y1-y2]` — refinery crude input, kb/d (aliases: refinery, runs)
- `exports [year|y1-y2]` — crude oil exports, kb/d
- `imports [year|y1-y2]` — crude oil imports, kb/d
- `production [year|y1-y2]` — domestic crude production, kb/d (alias: prod)
- `aggregate_demand [year|y1-y2]` — refinery_input + exports (aliases: agg, total_demand)
- `aggregate_supply [year|y1-y2]` — imports + production (aliases: agg_supply, total_supply)

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
