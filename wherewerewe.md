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

## Session 4 — Railway Deployment

### What Was Done
- Initialized git repo, pushed to private GitHub repo: OwenTanzer/oil-futures
- Created `requirements.txt`, `railway.toml`, and `worker.py`
- Added `DATA_DIR` env variable support to all three scripts so web service
  and worker can share a Railway volume at `/data`
- Added daily snapshot commits: worker copies data files into
  `snapshots/YYYY-MM-DD/` and pushes to GitHub once per calendar day
- Deployed web service on Railway — app is live on external URL
- Volume attached to web service at `/data`
- Env vars (ANTHROPIC_API_KEY, NEWSAPI_KEY) set on web service

### Worker / Volume Problem — Unresolved
Railway does not support attaching a single volume to two services.
The worker service (`fulfilling-truth`) cannot share the web service's volume.
This means the worker cannot write new items to the same data files the
dashboard reads. **The "Update feed" button in the Railway deployment is
effectively broken** — it runs but writes to ephemeral storage the dashboard
never sees. This is the highest-priority infrastructure problem.

Options not yet pursued:
- Use a cron job on the web service itself (single service, single volume,
  no sharing problem) — simplest fix
- Use a database (Postgres, Redis) instead of flat JSON files — right
  architecture long-term but more work
- Push data back to GitHub on each update and have the web service pull —
  ugly but functional

---

## Known Issues — Priority Order

### CRITICAL
1. **Update feed broken in Railway** — worker and web service can't share a
   volume; new items never reach the dashboard. Fix: move the collect+classify
   cycle into the web service itself via a cron schedule, eliminating the
   separate worker entirely.

### HIGH
2. **Stale news displayed** — most recent Kinetic item as of 2026-06-08 was
   from 09:25 UTC (Iran/Israel strikes), despite Iran subsequently announcing
   a ceasefire. The feed is not reflecting events that happened after the last
   local collect run. Directly related to issue #1.

3. **Timezone display** — all timestamps shown in UTC with no label and no
   user-local conversion. Users in other timezones cannot easily interpret
   the feed. Fix: detect browser timezone via JS component and convert display
   timestamps client-side, or at minimum label all times explicitly as UTC.

### HIGH
3b. **Timezone partially fixed** — v2 approach (JS reads `window.parent.document`
    and rewrites `data-utc` spans client-side) works for items already on screen
    at page load. Confirmed working 2026-06-08. Two remaining sub-bugs:
    - **New entries still show UTC** — the MutationObserver is supposed to catch
      Streamlit re-renders but is not converting newly added items. Likely cause:
      `data-converted` attribute is being set on initial items but new items
      injected by Streamlit may land in a part of the DOM the observer isn't
      watching, or the observer fires before the new HTML is fully parsed.
      Need Railway logs before attempting fix.
    - **Page refresh wipes all collected entries** — refreshing the browser
      returns the app to the base state of the committed JSON files, losing all
      items collected since the last daily snapshot commit. This is the volume/
      worker architecture problem: the web service writes to its volume but the
      data is not re-seeded on restart from the volume correctly, or the volume
      mount is not persisting between Streamlit reruns. Need Railway logs.

### MEDIUM
4. **Auto-refresh not working** — the browser-side reload timer appears
   non-functional in the Railway deployment. Needs investigation; may be
   a CSP or iframe sandboxing issue with the `components.html` injection.

5. **UI is ugly** — the current interface is functional but not shareable.
   Needs a design pass: better typography, cleaner layout, possibly a
   headline-style card format instead of the current bordered list items.

6. **Arc taxonomy needs refinement** — current arcs (KINETIC, DIPLOMATIC,
   STRAIT_SHIPPING, MARKET, IEA_SUPPLY, UNMAPPED) are a reasonable first cut
   but classification quality on edge cases is unreviewed. Items about Iranian
   domestic politics, US domestic energy policy, and China demand signals are
   landing inconsistently.

7. **Keyword system is static and coarse** — keywords are a flat list with
   no arc weighting. Ideally keywords would be arc-specific (KINETIC keywords
   vs. MARKET keywords) and would be reviewed/updated daily as the crisis
   evolves. An adaptive keyword system tied to a semi-daily review process
   would reduce both false positives and missed items.

### LOW / DEFERRED
8. **Coverage gaps** — several high-value source categories not yet integrated:
   - Discord/Telegram OSINT channels (TankerTrackers, OSINTdefender, etc.)
     — fastest kinetic signal; should be explored before any paid service
   - Reddit (r/iran, r/worldnews) — already probed and live; not yet added
     to active feeds in rss_collect.py
   - Better querying of existing free sources — Google News and Bing RSS
     queries may be suboptimal; query strings could be tuned
   - MarineTraffic free API tier — direct AIS tanker data; still unprobed
   - ISW direct RSS — 301 redirect, correct URL still unknown

9. **Event-level deduplication** — same event covered by 6 sources appears
   as 6 separate items. Processor-level clustering still deferred.

10. **Conflict flag cross-item detection** — currently flags only intra-article
    denials, not contradictions between separate articles.

---

## What Remains To Be Built

### Immediate (before sharing with others)
1. Fix the update feed / worker problem (cron on web service is likely fix)
2. Fix or remove the auto-refresh (determine if it's a Railway CSP issue)
3. Add explicit UTC label to all timestamps; consider browser-local conversion
4. Basic UI cleanup pass

### MediaFlow — Near Term
5. Adaptive keyword system — arc-specific keyword sets, semi-daily review hook
6. Arc taxonomy review — manual pass through Kinetic arc; tune edge cases
7. Add Reddit feeds (already probed live) to active collector
8. Explore Telegram/Discord OSINT channels as Phase 2 real-time layer

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
