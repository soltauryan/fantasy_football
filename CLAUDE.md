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
- `analysis/injury_impact.py` - **Injury impact analyzer** (Phase 2)
- `analysis/matchup_analyzer.py` - **Matchup analyzer** (Phase 2)
- `analysis/waiver_ranker.py` - **Waiver wire ranker** (Phase 2)
- `analysis/weekly_projections.py` - **Week-ahead projections** (Phase 2)
- `analysis/trade_analyzer.py` - **Trade value calculator** (Phase 3)
- `analysis/playoff_optimizer.py` - **Playoff schedule optimizer** (Phase 3)
- `analysis/bench_optimizer.py` - **Bench hold/drop analyzer** (Phase 3)
- `play/live_draft.py` - **Live draft CLI assistant**
- `play/draft_tui.py` - **Live draft TUI (rich interface)**
- `play/master_tui.py` - **Master TUI for all tools**

### Utilities
- `utils/db.py` - Database connection helpers
- `utils/features.py` - Feature engineering functions
- `utils/draft.py` - VOR calculations, scarcity analysis, draft recommendations
- `utils/weekly.py` - Weekly analysis (injury impact, snap trends, target trends)
- `utils/matchups.py` - Matchup analysis (defense rankings, soft matchups)

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

### Phase 2: Enhanced Weekly Analysis 📊 ✅ COMPLETE
**Goal:** Identify waiver wire pickups and value plays

- [x] Injury impact analyzer (RB1 out → RB2 value spike)
- [x] Matchup-based projections (soft defense identification)
- [x] Snap count trend detection (emerging players)
- [x] Target share shifts after injuries
- [x] Two-team waiver priority (who needs what position more)
- [x] Week-ahead projections with uncertainty ranges

**Files created/enhanced:**
- `analysis/injury_impact.py` - Injury cascade analysis ✅
- `analysis/waiver_ranker.py` - Weekly waiver wire rankings (enhanced with matchups) ✅
- `analysis/matchup_analyzer.py` - Defense rankings and soft matchup finder ✅
- `analysis/weekly_projections.py` - Week-ahead projections with floor/ceiling ✅
- `play/master_tui.py` - **Master TUI for all tools** ✅
- `utils/weekly.py` - Weekly analysis utilities (injury, snap, target functions) ✅
- `utils/matchups.py` - Matchup analysis utilities ✅
- `tests/` - Test suite with 50 tests ✅
- `utils/matchups.py` - Matchup analysis utilities

### Phase 3: Season-Long Management 📈 ✅ COMPLETE
**Goal:** Optimize roster decisions throughout the season

- [x] Trade analyzer (fair value calculator)
- [x] Playoff schedule optimizer (target favorable week 14-17 matchups)
- [x] Bench optimization (who to hold vs drop)
- [x] Two-team trade coordination (legal trades between Ryan/Wife)

**Files created:**
- `analysis/trade_analyzer.py` - Trade value rankings and comparison ✅
- `analysis/playoff_optimizer.py` - Playoff schedule analysis ✅
- `analysis/bench_optimizer.py` - Hold/drop/trade recommendations ✅
- `utils/trades.py` - Trade utility functions ✅
- `play/master_tui.py` - Updated with Trades/Playoffs/Bench tabs ✅

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

### Master TUI (All Tools)
```bash
uv run python play/master_tui.py
```
**Keyboard shortcuts:**
- `d/i/m/w/p` - Dashboard, Injuries, Matchups, Waivers, Projections
- `o/t/s/b` - Rosters, Trades, Schedules (playoffs), Bench
- `1-9` - Jump to week 1-9
- `Tab` - Toggle team filter (All/Ryan/Wife)
- `r` - Refresh data
- `F1` - Help overlay
- `q` - Quit

### Draft Assistant
```bash
# CLI version (cmd-based)
uv run python play/live_draft.py

# TUI version (rich interface)
uv run python play/draft_tui.py
```

### Weekly Analysis (Phase 2)
```bash
# Injury impact
uv run python analysis/injury_impact.py

# Matchups
uv run python analysis/matchup_analyzer.py --week 1

# Waiver rankings
uv run python analysis/waiver_ranker.py --week 1

# Projections with uncertainty
uv run python analysis/weekly_projections.py --week 1
```

### Season Management (Phase 3)
```bash
# Trade values and comparison
uv run python analysis/trade_analyzer.py
uv run python analysis/trade_analyzer.py --trade "Player A" "Player B"
uv run python analysis/trade_analyzer.py --two-team
uv run python analysis/trade_analyzer.py --needs

# Playoff schedule analysis
uv run python analysis/playoff_optimizer.py
uv run python analysis/playoff_optimizer.py --team ryan
uv run python analysis/playoff_optimizer.py --targets

# Bench optimization
uv run python analysis/bench_optimizer.py --team ryan
uv run python analysis/bench_optimizer.py --droppable
uv run python analysis/bench_optimizer.py --byes ryan
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

### Feb 1, 2026 (Session 5)
- **UX Review and Improvements for Master TUI:**
  - Added color coding for matchup grades (A+ green → F red)
  - Added color coding for trade tiers (Elite green → Droppable yellow)
  - Added color coding for bench recommendations (HOLD/TRADE/STASH/DROP)
  - Added color coding for injury status (OUT/DOUBTFUL red, QUESTIONABLE yellow)
  - Added color coding for waiver scores (higher = greener)
  - Added roster ownership highlighting (RYAN cyan, WIFE magenta, FA dim)
  - Improved empty state handling with placeholder messages
  - Added notification on data refresh ("Refreshing..." → "Data refreshed!")
  - Improved keyboard shortcuts:
    - Keys 1-9 now jump directly to weeks 1-9 (was only 1-3)
    - Changed `y` (playoffs) to `s` (schedules) for more intuitive binding
    - Added F1 for help overlay showing all shortcuts
  - Added help notification (F1) showing all keyboard shortcuts and tips
  - Improved CSS for rosters side-by-side layout
  - All 50 tests still passing
  - **All phases complete, UX polished!**

### Feb 1, 2026 (Session 4)
- **PHASE 3 COMPLETE!** All season-long management tools built.
- Built `analysis/trade_analyzer.py` - Trade analysis CLI:
  - Player trade value rankings based on projections, age, scarcity
  - Trade comparison (give vs receive with net value)
  - Fair trade finder for any player
  - Two-team trade suggestions between Ryan/Wife
  - Needs-based trade finder (mutual benefit trades)
  - Interactive trade evaluator mode
  - **Run with:** `uv run python analysis/trade_analyzer.py`
- Built `analysis/playoff_optimizer.py` - Playoff schedule analyzer:
  - Weeks 14-17 matchup analysis for all players
  - Schedule difficulty scoring (A+ to F grades)
  - Smash weeks and avoid weeks counter
  - Team-specific playoff roster analysis
  - Acquisition targets for playoff push
  - **Run with:** `uv run python analysis/playoff_optimizer.py`
- Built `analysis/bench_optimizer.py` - Bench management:
  - Hold/Drop/Trade/Stash recommendations for each player
  - Handcuff identification and analysis
  - Bye week coverage analysis
  - Positional depth evaluation
  - **Run with:** `uv run python analysis/bench_optimizer.py`
- Built `utils/trades.py` - Trade utility functions:
  - Trade value calculations with scarcity and age adjustments
  - Position replacement values
  - Fair trade matching
  - Needs-based trade finding
- Updated `play/master_tui.py` with Phase 3 tabs:
  - Trades tab: Trade value rankings
  - Playoffs tab: Week 14-17 schedule analysis
  - Bench tab: Hold/drop recommendations
  - New keyboard shortcuts: t=trades, y=playoffs, b=bench
- **ALL 3 PHASES COMPLETE!**
- **Run Master TUI:** `uv run python play/master_tui.py`

### Feb 1, 2026 (Session 3 continued)
- **PHASE 2 COMPLETE!**
- Built `analysis/weekly_projections.py` - Week-ahead projections with uncertainty:
  - Calculates floor/ceiling based on player variance (stddev)
  - Matchup adjustments (A+ = +15%, F = -10%)
  - Injury status discounts (QUESTIONABLE = -15%, OUT = 0)
  - Recent form detection (Hot/Cold/Stable)
  - Confidence levels (High/Medium/Low based on sample size & variance)
  - Team-specific views with starter lineup
  - **Run with:** `uv run python analysis/weekly_projections.py --week 1`
- Built `play/master_tui.py` - **Unified TUI for all analysis tools**:
  - Dashboard overview with team summaries
  - Tabbed interface: Dashboard, Injuries, Matchups, Waivers, Projections, Rosters
  - Week selector (1-18) and team filter (All/Ryan/Wife)
  - Keyboard shortcuts: d/i/m/w/p/t for tabs, 1-3 for weeks, Tab to toggle team
  - Integrated DataTables for all analysis views
  - Launch draft TUI from button
  - **Run with:** `uv run python play/master_tui.py`
- All 6/6 Phase 2 items now complete
- **Next:** Phase 3 (Season-Long Management)

### Feb 1, 2026 (Session 3)
- **Started Phase 2: Enhanced Weekly Analysis**
- Built `analysis/injury_impact.py` - Injury impact analyzer CLI:
  - Uses ESPN roster injury data for 2025 (nflreadpy returns 404)
  - Projects snap count increases for backups
  - Estimates target share redistribution
  - Shows rostered vs free agent status
  - Team-specific recommendations with positional need boosting
  - Commands: `--team`, `--pos`, `--emerging`, `--cascade`
  - **Run with:** `uv run python analysis/injury_impact.py`
- Built `utils/matchups.py` - Matchup analysis utilities:
  - Defense rankings by position (fantasy pts allowed)
  - Soft matchup identification (A+/A/B/C/D/F grades)
  - Schedule difficulty analysis per team
  - Streaming candidate recommendations
- Built `analysis/matchup_analyzer.py` - Matchup analyzer CLI:
  - Defense rankings for all positions
  - Week-by-week soft matchup report
  - Team schedule difficulty views
  - Streaming plays for each position
  - **Run with:** `uv run python analysis/matchup_analyzer.py`
- Enhanced `analysis/waiver_ranker.py`:
  - Integrated matchup scoring (boost for soft matchups, penalty for tough)
  - Shows matchup grades in output
  - Uses ESPN injury data for 2025+
  - **Run with:** `uv run python analysis/waiver_ranker.py --week 1`
- Enhanced `utils/weekly.py`:
  - Added `load_espn_injuries()` for 2025 injury data
  - Added `analyze_injury_impact_espn()` with projections
  - Fixed depth chart loader to use correct columns (club_code, depth_team)
  - Added `get_team_target_distribution()` for cascade analysis
- Set up test framework:
  - Added pytest as dev dependency
  - Created `tests/` directory with 50 tests
  - Tests for weekly.py, matchups.py, draft.py
  - **Run tests:** `uv run pytest tests/ -v`
- **5/6 Phase 2 items complete** (week-ahead projections with uncertainty ranges remaining)
- **Next:** Complete Phase 2 (uncertainty ranges), then Phase 3 (season-long management)

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
- [ ] **Duplicate players in draft TUI** - Investigate source of duplicates in player list (likely from joins in `load_projections()` or `add_adp_to_projections()`)
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
