# Where We Were — Session Summary
Date: 2026-06-08
Project: Mooper Oil Crisis Model (MOCM)

---

## Sessions 1 + 2 Summary

Full detail on session 1 (feed discovery, ingest layer build) is preserved in
the CLAUDE.md data sources tables and the explore/ probe outputs.

---

## Session 2 — What We Built

### Goal
Move from a collector that writes to a text log to a live visual system:
arc-classified, continuously updated, readable at a glance.

### 1. Restructured the working directory
Moved all feed-probe scripts and their outputs into `explore/`:
- gdelt_explore.py, rss_explore.py, rss_explore_t2/t3.py,
  rss_explore_additional.py, rss_explore_wire.py
- All associated output .txt files
Root now contains only live operational files.

### 2. Modified rss_collect.py — structured item store
Added `mediaflow_items.json` as a parallel output alongside the existing
human-readable log. Each collected item gets a stable 12-char ID (MD5 of
canonical URL). The items file is append-only and deduplicated by ID.
The existing log and seen.json behavior is unchanged.

### 3. Built mediaflow_classify.py — incremental arc classifier
- Reads `mediaflow_items.json`, diffs against `mediaflow_classified.json`
- Initial version sent only unclassified items to Claude Haiku in batches of 15
  (superseded in Session 3 by batches of 30 with concurrent API calls)
- Each item receives: arc, one-sentence factual summary, conflict flag
- Writes merged results back to `mediaflow_classified.json`
- Fully incremental — routine runs only process new items

**Arc taxonomy** is a single `ARCS` list at the top of the file:
```python
ARCS = ["KINETIC", "DIPLOMATIC", "STRAIT_SHIPPING", "MARKET", "IEA_SUPPLY", "UNMAPPED"]
```
Add/remove arcs here; the system prompt rebuilds automatically from this list.

**System prompt design** — deliberately minimal (~180 tokens):
- No situational briefing (model knows the context from the articles)
- No edge-case rules (creates pattern-matching brittleness)
- Input/output format + one ghostwritten example anchors behavior
- The only interpolated variable is the arc enum string

```
Classify news articles about the Iran/Hormuz oil crisis.

Input: JSON array — each item has id, source, title, summary.
Output: JSON array, same order — each item has:
  id       — same as input
  arc      — one of: KINETIC | DIPLOMATIC | STRAIT_SHIPPING | MARKET | IEA_SUPPLY
  summary  — one sentence, ≤100 chars, present tense, factual
  conflict — true if the item reports a denial or contradictory claim, else false

Example: [input/output pair ghostwritten here]

Return only the JSON array.
```

### 4. Built mediaflow_app.py — Streamlit dashboard
- White background; arc color used sparingly (left-border accent only)
- Tabs: All | Kinetic | Diplomatic | Strait/Shipping | Market | IEA/Supply
- Items sorted newest-first within each tab
- Conflict items flagged with ⚡
- Sidebar: single "Update feed" button runs collect then classify in sequence
- Sidebar: item limit slider, conflict-only filter, auto-refresh toggle
- Run with: `python -m streamlit run mediaflow_app.py`

### 5. Initial bootstrap run
- Ran collector: 830 items collected into mediaflow_items.json
- Ran classifier: 830/830 classified, 0 failures
- Dashboard operational at localhost:8501

---

## Known Issues / Next Review Items

- **Relevance filter noise:** Some DW World articles about disease outbreaks,
  sport, and other non-Iran topics are passing the keyword filter (they match
  on terms like "oil", "shipping", "maritime" in unrelated contexts). These
  get classified but land as noise in MARKET or STRAIT_SHIPPING. Fix: tighten
  EXCLUDE_RE or add a minimum keyword density threshold.

- **Classification quality on Kinetic arc:** Not yet reviewed carefully.
  This is the highest-signal arc — worth going through it manually once to
  validate the model's arc assignment and summary quality.

- **Conflict flag calibration:** Flag fires on explicit denials within a
  single article ("CENTCOM denies X"). Cross-item contradictions (article A
  and article B each report opposite facts without referencing each other)
  are not detected. A second-pass comparison step remains deferred.

---

## Session 3 - Dashboard + Classifier Critical Review

### Dashboard / Display Mechanics
- Auto-refresh no longer blocks the Streamlit script with `time.sleep`; it now
  uses a browser-side reload timer.
- Tabs now show visible/total counts.
- Per-tab captions make item-limit truncation explicit.
- `Other / Unmapped` appears when classified records do not belong to a known
  arc, so records are not silently absent from every per-arc view.
- Current display selection remains newest-first by `published`; the sidebar
  item limit intentionally hides older items.

### Feed Update Performance
- `rss_collect.py` now fetches RSS feeds, official HTML monitors, and NewsAPI
  queries with bounded parallel I/O.
- Requests share a shorter connect/read timeout, so one stuck feed no longer
  serially delays the entire update.
- Live collector smoke tests completed in roughly 15-18 seconds, with IRNA
  occasionally timing out cleanly.
- NewsAPI key is now loaded from environment or `keys.env`, not hardcoded.

### Classifier / API Labeling
- `mediaflow_classify.py` now batches 30 items per request and runs up to 4
  classifier requests concurrently.
- API payload JSON is compacted.
- Batch calls retry with backoff.
- Model output is normalized before persistence: invalid/null arcs, missing
  summaries, and non-bool conflict values are repaired.
- `UNMAPPED` is now an explicit arc for unrelated feed noise.
- Existing malformed classified rows were repaired locally without API calls.

### Current State After Review
- `mediaflow_items.json`: 1406 items
- `mediaflow_classified.json`: 1406 items
- Bad/null arcs: 0
- Missing summaries: 0
- Bad conflict fields: 0
- Current arc distribution:
  - MARKET: 521
  - KINETIC: 354
  - STRAIT_SHIPPING: 332
  - DIPLOMATIC: 168
  - IEA_SUPPLY: 19
  - UNMAPPED: 12

### Remaining Design Question
The classifier still asks the API for both arc labels and polished summaries in
the same call. The next major speed/efficiency gain would be to split the path:
fast label/conflict classification first, then optional/background summary
generation only for items that survive relevance or display filters.

---

## What Remains To Be Built

### MediaFlow — Near Term
1. Review Kinetic arc classification quality; tune if needed
2. Tighten relevance filter to reduce noise items now landing in UNMAPPED
3. ISW direct RSS feed — 301 redirect, correct URL still unknown
4. Event-level deduplication / clustering (same event, multiple articles)
   remains a processor task — currently each article appears separately

### MediaFlow — Phase 2 (Deferred)
- Telegram OSINT channels (TankerTrackers, OSINTdefender, naval monitors)
  — fastest real-time kinetic signal; no rate limits on public channels
- MarineTraffic API — direct AIS tanker position data; free tier available
- Mediastack / TheNewsAPI as NewsAPI backup sources

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
