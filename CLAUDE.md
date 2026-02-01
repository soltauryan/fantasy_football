# Fantasy Football Analytics Platform

> **CLAUDE: As you work on this project, CHECK OFF completed items `[x]` in the Roadmap and add dated entries to Session Notes. This maintains continuity across sessions.**

---

## Project Goal
Build analytical tools for constructing the best fantasy football team(s) for the **2026 season**. As of Feb 2026, the 2025 season is complete and preparation for 2026 draft and season begins.

**Key Constraint:** Managing TWO teams (Ryan's and Wife's team) - architecture must support multi-team analysis.

---

## Current State (Feb 1, 2026)

### Data Pipeline (Working)
```
Bronze (Raw) → Silver (Cleaned) → Gold (Analytics-Ready)
```

| Layer | Tables | Status |
|-------|--------|--------|
| Bronze | 14 tables (NFL stats, ESPN league, NextGen, injuries, depth charts) | ✅ Complete |
| Silver | 3 tables (players, weekly_performance, depth_charts) | ✅ Complete |
| Gold | master_rankings, value_predictions_lgbm, projections_2026 | ✅ Complete |

### Data Sources
- **nflreadpy**: NFL stats, schedules, snap counts, NextGen stats, depth charts
- **espn-api**: League data, rosters, matchups, draft picks, free agents
- **Manual**: 2026 rookie projections CSV

### Models Built
1. **LightGBM Value Model** (`models/train_lgbm.py`) - Position-specific player valuation
2. **2026 Projections** (`models/predict_2026.py`) - Forward-looking PPG predictions
3. Ridge regression baseline (`models/train_value_model.py`)

### Analysis Tools
- `analysis/draft_analyzer.py` - Draft value analysis (legacy)
- `analysis/schedule_conflicts.py` - Bye week conflict detection
- `analysis/weekly_optimizer.py` - Lineup optimization
- `play/live_draft.py` - **Live draft CLI assistant**
- `play/draft_tui.py` - **Live draft TUI (rich interface)**

### Utilities
- `utils/db.py` - Database connection helpers
- `utils/features.py` - Feature engineering functions
- `utils/draft.py` - VOR calculations, scarcity analysis, draft recommendations

---

## Roadmap

### Phase 1: Live Draft Assistant 🎯 (Priority)
**Goal:** Real-time draft guidance as picks happen

- [x] Build draft state tracker (who's been picked, current round/pick)
- [x] Value-over-replacement (VOR) calculations by position
- [x] Best available player recommendations
- [x] Position scarcity alerts ("last elite RB available")
- [x] Two-team coordination (avoid picking same player twice, balance needs)
- [x] ADP vs actual pick tracking (VALUE/REACH analysis on each pick)
- [x] Trade value calculator for pick swaps

**Files created:**
- `play/live_draft.py` - Main draft assistant interface ✅
- `utils/draft.py` - Draft utility functions (VOR, scarcity, etc.) ✅

### Phase 2: Enhanced Weekly Analysis 📊
**Goal:** Identify waiver wire pickups and value plays

- [ ] Injury impact analyzer (RB1 out → RB2 value spike)
- [ ] Matchup-based projections (soft defense identification)
- [ ] Snap count trend detection (emerging players)
- [ ] Target share shifts after injuries
- [ ] Two-team waiver priority (who needs what position more)
- [ ] Week-ahead projections with uncertainty ranges

**Files to create/enhance:**
- `analysis/injury_impact.py` - Injury cascade analysis
- `analysis/waiver_ranker.py` - Weekly waiver wire rankings
- `utils/matchups.py` - Matchup analysis utilities

### Phase 3: Season-Long Management 📈
**Goal:** Optimize roster decisions throughout the season

- [ ] Trade analyzer (fair value calculator)
- [ ] Playoff schedule optimizer (target favorable week 14-17 matchups)
- [ ] Bench optimization (who to hold vs drop)
- [ ] Two-team trade coordination (legal trades between Ryan/Wife)

---

## Architecture Decisions

### Multi-Team Support
```python
# Team IDs are stable; names are fetched from DB dynamically
MY_TEAM_IDS = {
    "ryan": 6,   # SoltyTears4U (name may change)
    "wife": 9,   # Serving Punt (name may change)
}
LEAGUE_ID = 1365062471
```
- All analysis functions accept `team_id` parameter
- Team names fetched from `bronze_espn_teams` at runtime (handles renames)
- Dashboard views show both teams side-by-side
- Draft assistant prevents duplicate recommendations

### Shared Utilities Pattern
All reusable functions go in `utils/`:
- `utils/db.py` - Database operations
- `utils/features.py` - Feature engineering
- `utils/draft.py` - VOR, scarcity, recommendations ✅
- `utils/matchups.py` - Matchup analysis (planned)
- `utils/scoring.py` - Fantasy scoring rules (planned)

### Database Schema
SQLite at `data/nfl.db` (~124MB)
- Bronze tables: `bronze_*` (raw ingestion)
- Silver tables: `silver_*` (cleaned/normalized)
- Gold tables: `gold_*` (analytics-ready)

---

## Quick Reference

### Environment
**Using `uv` for venv management and running scripts.**
```bash
# Run any script
uv run python <script.py>

# Run the pipeline
uv run python run_pipeline.py

# Add dependencies
uv add <package>
```

### Run Full Pipeline
```bash
uv run python run_pipeline.py
```

### Draft Assistant
```bash
# CLI version (cmd-based)
uv run python play/live_draft.py

# TUI version (rich interface)
uv run python play/draft_tui.py
```

### Key File Locations
| Purpose | Location |
|---------|----------|
| Data ingestion | `etl/ingest_bronze.py`, `etl/ingest_espn.py` |
| Transformations | `etl/transform_silver.py` |
| Rankings | `etl/generate_master_rankings.py` |
| Models | `models/train_lgbm.py`, `models/predict_2026.py` |
| Analysis | `analysis/` |
| Utilities | `utils/` |
| Notebooks | `notebooks/` |

### ESPN API Credentials
Stored in scripts (SWID, ESPN_S2 tokens) - consider moving to `.env`

---

## Session Notes

> **Format:** Add new entries at the top with date. Note what was accomplished, decisions made, and next steps.

### Feb 1, 2026 (Session 2 continued)
- Added ADP tracking to draft assistant:
  - New commands: `adp`, `value`, `targets`
  - `adp [pos]` - Show best available sorted by ADP (from FantasyPros ECR)
  - `value` - Show players available past their ADP (steal opportunities)
  - `targets [n]` - Players likely available at your next pick (snake draft)
  - Pick/draft commands now show VALUE/REACH analysis (e.g., "ADP: 16.5 | GREAT VALUE")
  - 274 players with ADP data from bronze_ff_rankings (redraft-overall)
- Added trade value calculator:
  - New commands: `trade`, `pickvalue`
  - `trade` - Interactive trade evaluator (give picks, receive picks, see WIN/LOSS/FAIR)
  - `pickvalue <pick>` - Show value of a pick and equivalent 2-pick combinations
  - Exponential decay model: Pick 1 = 100, Pick 12 ≈ 54, Pick 24 ≈ 27
  - Supports notation: "1.05" (round.pick) or "15" (overall)
- **PHASE 1 COMPLETE!** All 7 items checked off
- Built TUI interface (`play/draft_tui.py`) using `textual`:
  - 3-panel layout: Rosters (left), Players (center), Scarcity (right)
  - Tabbed player views: Best Available, By ADP, Value Picks, Recommendations
  - Keyboard shortcuts: 1-4 filter positions, 0=all, v=toggle VOR/ADP, Tab=switch team
  - Click row to draft player to active team
  - Command input for pick/draft/search/undo
  - Live updating scarcity alerts
  - **Run with:** `uv run python play/draft_tui.py`
- Researched ESPN API draft limitations:
  - espn-api does NOT work for live drafts (ESPN uses different APIs)
  - Post-draft data works fine via `league.draft`
  - Built simulation mode to test draft assistant with 2025 data
  - `sim load` loads 168 picks from 2025 draft
  - `sim auto` auto-advances until your team's turn
  - Wife picks at 1.05, Ryan picks at 1.12 in 2025 draft order
- **Next:** Phase 2 (weekly analysis - injury impact, waiver ranker)

### Feb 1, 2026 (Session 2)
- Built `utils/draft.py` with VOR calculations, scarcity analysis, recommendation engine
- Built `play/live_draft.py` - interactive CLI draft assistant
  - Commands: `avail`, `rec`, `pick`, `draft`, `teams`, `scarcity`, `search`, `undo`, `sync`
  - Two-team support (ryan/wife) with team names fetched dynamically from DB
  - VOR-based rankings (Cam Skattebo leads at +118.4 VOR)
  - Position scarcity alerts when elite players running low
- Team IDs confirmed: ryan=6 (SoltyTears4U), wife=9 (Serving Punt)
- **Run with:** `uv run python play/live_draft.py`

### Feb 1, 2026 (Session 1)
- Created CLAUDE.md for project tracking
- Documented current state and roadmap
- Priority: Live draft assistant development

---

## Known Issues / Tech Debt
- [ ] ESPN credentials hardcoded (move to .env)
- [ ] 2025 injury data returns 404 from nflreadpy
- [ ] Rookie data manually curated (no automated source)
- [x] ~~Need to identify team_ids for Ryan and Wife's teams~~ (ryan=6, wife=9)
- [x] ESPN live draft sync **NOT SUPPORTED** by espn-api (uses different APIs during live draft)
  - `league.draft` only works AFTER draft completes
  - Workarounds: Selenium scraping, browser extensions (both brittle)
  - **Solution built:** Simulation mode using 2025 draft data for testing
  - Commands: `sim load`, `sim next [n]`, `sim auto`, `sim reset`, `sim status`
  - Auto-stops when it's your team's turn, shows VALUE/REACH analysis

---

## Future Enhancements
- [x] Build TUI (text user interface) for navigating draft assistant commands - `play/draft_tui.py` using `textual`
