#!/usr/bin/env python3
"""
Fantasy Football Master TUI

Unified command center for all fantasy football analysis tools.
Run with: uv run python play/master_tui.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import polars as pl
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Static, DataTable, Button, TabbedContent, TabPane, Select
from textual.binding import Binding

from utils.db import get_connection, read_sqlite_robust
from utils.weekly import analyze_injury_impact_espn, get_snap_trends
from utils.matchups import get_soft_matchups, get_matchup_grade
from utils.trades import get_all_trade_values
from analysis.weekly_projections import generate_projections
from analysis.waiver_ranker import rank_waiver_pickups, analyze_for_team
from analysis.playoff_optimizer import get_all_playoff_schedules, get_team_playoff_analysis
from analysis.bench_optimizer import get_bench_analysis


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MY_TEAM_IDS = {"ryan": 6, "wife": 9}
SEASON = 2025

# Two italic F's - Final Fantasy style, sheared to the right
LOGO = r"""[bold bright_blue]
    ____//   ____//
   //___    //___        [bold bright_cyan]F[/][cyan]ANTASY[/]
  //       //            [bold bright_cyan]F[/][cyan]OOTBALL[/]
 //       //
//_      //_             [white]━━━━━━━━━━━━━━━━━━━━━[/]
                         [dim]Command Center[/] [bold]•[/] [dim]{season}[/]
[/]"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FORMATTING HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fmt_grade(grade: str) -> str:
    """Format matchup/tier grades with color."""
    if not grade:
        return "[dim]-[/]"
    g = grade.strip().upper()
    styles = {
        "A+": "bold bright_green", "A": "green", "B": "bright_cyan",
        "C": "white", "D": "yellow", "F": "bold red",
        "ELITE": "bold bright_green", "STARTER": "green", "FLEX": "bright_cyan",
        "BENCH": "white", "DROPPABLE": "yellow",
    }
    return f"[{styles.get(g, 'white')}]{grade}[/]"


def fmt_action(action: str) -> str:
    """Format bench action recommendations with color."""
    styles = {"HOLD": "green", "TRADE": "bright_cyan", "STASH": "yellow", "DROP": "red"}
    return f"[{styles.get(action.upper(), 'white')}]{action}[/]"


def fmt_owner(owner: str) -> str:
    """Format roster ownership with team colors."""
    if not owner or owner.upper() in ("FA", "FREE", ""):
        return "[dim]—[/]"
    if owner.upper() == "RYAN":
        return "[bright_cyan]Ryan[/]"
    if owner.upper() == "WIFE":
        return "[bright_magenta]Wife[/]"
    return owner


def fmt_status(status: str) -> str:
    """Format injury status with severity colors."""
    if not status or status.upper() in ("ACTIVE", "NORMAL", ""):
        return "[green]✓[/]"
    s = status.upper()
    if s in ("OUT", "IR"):
        return f"[bold red]{s}[/]"
    if s == "DOUBTFUL":
        return "[red]D[/]"
    if s == "QUESTIONABLE":
        return "[yellow]Q[/]"
    return f"[yellow]{status[:3]}[/]"


def fmt_score(score: float, thresholds: tuple = (8, 5)) -> str:
    """Format numeric scores with color based on thresholds."""
    high, med = thresholds
    if score >= high:
        return f"[bold bright_green]{score:.1f}[/]"
    if score >= med:
        return f"[green]{score:.1f}[/]"
    return f"{score:.1f}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA LOADERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_team_names() -> dict:
    """Fetch fantasy team names from database."""
    conn = get_connection()
    df = read_sqlite_robust("SELECT team_id, team_name FROM bronze_espn_teams", conn)
    conn.close()
    return {
        key: {"id": tid, "name": df.filter(pl.col("team_id") == tid)["team_name"][0]
              if len(df.filter(pl.col("team_id") == tid)) > 0 else f"Team {tid}"}
        for key, tid in MY_TEAM_IDS.items()
    }


def load_rosters() -> dict:
    """Fetch current rosters for both fantasy teams."""
    conn = get_connection()
    rosters = {}
    for key, tid in MY_TEAM_IDS.items():
        rosters[key] = read_sqlite_robust(f"""
            SELECT player_name, position, pro_team AS team,
                   injury_status, projected_total_points, total_points
            FROM bronze_espn_rosters
            WHERE team_id = {tid} AND position IN ('QB', 'RB', 'WR', 'TE')
            ORDER BY
                CASE position WHEN 'QB' THEN 1 WHEN 'RB' THEN 2 WHEN 'WR' THEN 3 ELSE 4 END,
                projected_total_points DESC
        """, conn)
    conn.close()
    return rosters


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DASHBOARD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DashboardWidget(Static):
    """Home screen with logo, team summaries, and alerts."""

    def compose(self) -> ComposeResult:
        yield Static(id="dash-content")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        teams = load_team_names()
        rosters = load_rosters()
        lines = [LOGO.format(season=SEASON)]

        # Team summary cards
        for key in ["ryan", "wife"]:
            name = teams[key]["name"]
            roster = rosters.get(key, pl.DataFrame())
            color = "bright_cyan" if key == "ryan" else "bright_magenta"

            if roster.is_empty():
                lines.append(f"[bold {color}]▌ {name}[/]  [dim]No roster data[/]")
                continue

            pts = roster["total_points"].sum() or 0
            proj = roster["projected_total_points"].sum() or 0
            pos_counts = roster.group_by("position").len()
            pos_str = "  ".join(f"[dim]{r['position']}[/]{r['len']}" for r in pos_counts.iter_rows(named=True))

            injured = roster.filter(
                pl.col("injury_status").is_not_null() &
                ~pl.col("injury_status").is_in(["ACTIVE", "NORMAL"])
            )
            inj_str = ""
            if not injured.is_empty():
                inj_names = ", ".join(injured["player_name"].to_list()[:2])
                inj_str = f"  [yellow]⚠ {inj_names}[/]"

            lines.append(f"[bold {color}]▌ {name}[/]")
            lines.append(f"  {pos_str}   │   [bold]{pts:.0f}[/] pts   │   Proj [dim]{proj:.0f}[/]{inj_str}")
            lines.append("")

        # Alerts
        lines.append("[bold]━━━ ALERTS ━━━[/]")
        injuries = analyze_injury_impact_espn(SEASON)
        if injuries:
            lines.append("")
            lines.append("[yellow]⚡ Injury Opportunities[/]")
            for opp in injuries[:3]:
                lines.append(f"   [bold]{opp['backup_player']}[/] ← {opp['injured_player']} "
                           f"[dim]({opp['position']}, score {opp['opportunity_score']:.1f})[/]")

        trends = get_snap_trends(SEASON, min_weeks=3, min_trend=15.0)
        if not trends.is_empty():
            lines.append("")
            lines.append("[green]📈 Rising Snap Shares[/]")
            for row in trends.head(3).iter_rows(named=True):
                lines.append(f"   [bold]{row['full_name']}[/] [dim]+{row['snap_trend']:.0f}%[/]")

        self.query_one("#dash-content").update("\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INJURIES TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class InjuriesWidget(Static):
    """Table of backup players gaining value from injuries."""

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Injury Opportunities[/]  [dim]│  Backups gaining value from injured starters[/]",
            classes="tab-header"
        )
        yield DataTable(id="inj-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one("#inj-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Backup", "Pos", "NFL", "Replaces", "Status", "Opp Score", "Roster")

        injuries = analyze_injury_impact_espn(SEASON)
        if not injuries:
            table.add_row("[dim]No injury opportunities found[/]", "", "", "", "", "", "")
            return

        seen = set()
        for opp in injuries[:35]:
            if opp["backup_player"] in seen:
                continue
            seen.add(opp["backup_player"])
            table.add_row(
                opp["backup_player"],
                opp["position"],
                opp["team"],
                opp["injured_player"],
                fmt_status(opp["injury_status"]),
                fmt_score(opp["opportunity_score"], (7, 4)),
                fmt_owner(opp.get("rostered_by")),
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MATCHUPS TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MatchupsWidget(Static):
    """Soft defensive matchups for the selected week."""

    def __init__(self, week: int = 1):
        super().__init__()
        self.week = week

    def compose(self) -> ComposeResult:
        yield Static(id="match-header", classes="tab-header")
        yield DataTable(id="match-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        self.query_one("#match-header").update(
            f"[bold]Week {self.week} Matchups[/]  [dim]│  Offenses facing weak defenses (lower rank = weaker D)[/]"
        )
        table = self.query_one("#match-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Offense", "vs Defense", "Position", "Def Rank", "Pts Allowed", "Grade")

        matchups = get_soft_matchups(self.week, SEASON, top_n=30)
        if not matchups:
            table.add_row("[dim]No data for this week[/]", "", "", "", "", "")
            return

        for m in matchups[:28]:
            rank = m["def_rank"]
            rank_style = "bright_green" if rank <= 8 else "cyan" if rank <= 16 else "yellow" if rank <= 24 else "red"
            table.add_row(
                m["team"],
                f"@ {m['opponent']}",
                m["position"],
                f"[{rank_style}]#{rank}[/]",
                f"{m['pts_allowed']:.1f}",
                fmt_grade(get_matchup_grade(rank)),
            )

    def set_week(self, week: int) -> None:
        self.week = week
        self.refresh_data()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WAIVERS TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WaiversWidget(Static):
    """Waiver wire pickup recommendations."""

    def __init__(self, week: int = 1, team_key: str = None):
        super().__init__()
        self.week = week
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        yield Static(id="waiver-header", classes="tab-header")
        yield DataTable(id="waiver-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        team_label = f" for {self.team_key.upper()}" if self.team_key else ""
        self.query_one("#waiver-header").update(
            f"[bold]Week {self.week} Waivers{team_label}[/]  [dim]│  Available players worth adding[/]"
        )
        table = self.query_one("#waiver-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Player", "Pos", "NFL", "Owned%", "Matchup", "Score", "Reason")

        rankings = (analyze_for_team(self.team_key, SEASON, self.week, top_n=25)
                   if self.team_key else rank_waiver_pickups(SEASON, self.week, top_n=25))

        if rankings.is_empty():
            table.add_row("[dim]No waiver targets found[/]", "", "", "", "", "", "")
            return

        for row in rankings.iter_rows(named=True):
            matchup = row.get("matchup_grade") or ""
            table.add_row(
                row["player_name"],
                row["position"],
                row.get("team", "")[:4],
                f"{row['pct_owned']:.0f}%",
                fmt_grade(matchup) if matchup else "[dim]—[/]",
                fmt_score(row["waiver_score"], (12, 8)),
                row.get("reasons", "")[:40],
            )

    def set_week(self, week: int, team_key: str = None) -> None:
        self.week = week
        self.team_key = team_key
        self.refresh_data()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PROJECTIONS TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ProjectionsWidget(Static):
    """Weekly player projections with floor/ceiling ranges."""

    def __init__(self, week: int = 1, team_key: str = None):
        super().__init__()
        self.week = week
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        yield Static(id="proj-header", classes="tab-header")
        yield DataTable(id="proj-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        team_label = f" — {self.team_key.upper()}" if self.team_key else ""
        self.query_one("#proj-header").update(
            f"[bold]Week {self.week} Projections{team_label}[/]  [dim]│  Expected points with uncertainty range[/]"
        )
        table = self.query_one("#proj-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Player", "Pos", "Opponent", "Matchup", "Projected", "Floor", "Ceiling", "Form")

        projections = generate_projections(self.week, SEASON, team_key=self.team_key)
        if not projections:
            table.add_row("[dim]No projections available[/]", "", "", "", "", "", "", "")
            return

        for p in projections[:35]:
            form_styles = {"Hot": "bold bright_green", "Cold": "bold red", "Stable": "dim"}
            form_str = f"[{form_styles.get(p.recent_form, 'white')}]{p.recent_form}[/]"
            table.add_row(
                p.player_name,
                p.position,
                f"vs {p.opponent}",
                fmt_grade(p.matchup_grade),
                f"[bold]{p.injury_adjusted:.1f}[/]",
                f"[dim]{p.floor:.1f}[/]",
                f"[bright_cyan]{p.ceiling:.1f}[/]",
                form_str,
            )

    def set_week(self, week: int, team_key: str = None) -> None:
        self.week = week
        self.team_key = team_key
        self.refresh_data()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ROSTERS TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RosterWidget(Static):
    """Single team roster display."""

    def __init__(self, team_key: str):
        super().__init__()
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        teams = load_team_names()
        name = teams[self.team_key]["name"]
        color = "bright_cyan" if self.team_key == "ryan" else "bright_magenta"
        yield Static(f"[bold {color}]{name}[/]", classes="roster-title")
        yield DataTable(id=f"roster-{self.team_key}", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one(f"#roster-{self.team_key}", DataTable)
        table.clear(columns=True)
        table.add_columns("Player", "Pos", "NFL", "Points", "Proj", "Health")

        roster = load_rosters().get(self.team_key, pl.DataFrame())
        if roster.is_empty():
            table.add_row("[dim]No roster data[/]", "", "", "", "", "")
            return

        for row in roster.iter_rows(named=True):
            table.add_row(
                row["player_name"],
                row["position"],
                row.get("team", "")[:4],
                f"{row.get('total_points', 0):.0f}",
                f"{row.get('projected_total_points', 0):.0f}",
                fmt_status(row.get("injury_status")),
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADES TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TradesWidget(Static):
    """Trade value rankings for all players."""

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Trade Values[/]  [dim]│  Player worth based on projections, age, and positional scarcity[/]",
            classes="tab-header"
        )
        yield DataTable(id="trades-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        table = self.query_one("#trades-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Player", "Pos", "NFL", "Trade Value", "Tier", "Roster")

        values = get_all_trade_values()
        if not values:
            table.add_row("[dim]No trade data[/]", "", "", "", "", "")
            return

        for v in values[:40]:
            table.add_row(
                v.player_name,
                v.position,
                v.team[:4] if v.team else "",
                f"[bold]{v.final_value:.1f}[/]",
                fmt_grade(v.tier),
                fmt_owner(v.rostered_by),
            )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PLAYOFFS TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PlayoffsWidget(Static):
    """Fantasy playoff schedule analysis (weeks 14-17)."""

    def __init__(self, team_key: str = None):
        super().__init__()
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        yield Static(id="playoff-header", classes="tab-header")
        yield DataTable(id="playoff-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        team_label = f" — {self.team_key.upper()}" if self.team_key else ""
        self.query_one("#playoff-header").update(
            f"[bold]Playoff Schedule{team_label}[/]  [dim]│  Matchup grades for weeks 14-17[/]"
        )
        table = self.query_one("#playoff-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Player", "Pos", "NFL", "Wk 14", "Wk 15", "Wk 16", "Wk 17", "Overall")

        schedules = (get_team_playoff_analysis(self.team_key, SEASON)
                    if self.team_key else get_all_playoff_schedules(SEASON))

        if not schedules:
            table.add_row("[dim]No playoff data[/]", "", "", "", "", "", "", "")
            return

        for s in schedules[:35]:
            table.add_row(
                s.player_name,
                s.position,
                s.team,
                fmt_grade(s.week_14["grade"]),
                fmt_grade(s.week_15["grade"]),
                fmt_grade(s.week_16["grade"]),
                fmt_grade(s.week_17["grade"]),
                fmt_grade(s.schedule_grade),
            )

    def set_team(self, team_key: str = None) -> None:
        self.team_key = team_key
        self.refresh_data()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BENCH TAB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class BenchWidget(Static):
    """Bench player hold/drop/trade recommendations."""

    def __init__(self, team_key: str = "ryan"):
        super().__init__()
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        yield Static(id="bench-header", classes="tab-header")
        yield DataTable(id="bench-table", zebra_stripes=True)

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        self.query_one("#bench-header").update(
            f"[bold]Bench — {self.team_key.upper()}[/]  [dim]│  Hold, trade, stash, or drop recommendations[/]"
        )
        table = self.query_one("#bench-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Player", "Pos", "Trade Value", "Tier", "Action", "Reasoning")

        analysis = get_bench_analysis(self.team_key)
        if not analysis:
            table.add_row("[dim]No bench data[/]", "", "", "", "", "")
            return

        for p in analysis:
            table.add_row(
                p.player_name,
                p.position,
                f"{p.trade_value:.1f}",
                fmt_grade(p.tier),
                fmt_action(p.recommendation),
                p.reasoning,
            )

    def set_team(self, team_key: str) -> None:
        self.team_key = team_key
        self.refresh_data()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN APPLICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FantasyTUI(App):
    """Fantasy Football Command Center - Main Application."""

    CSS = """
    Screen { background: $surface; }

    #main { height: 100%; }

    TabbedContent { height: 100%; }
    TabPane { padding: 1 2; }

    DataTable { height: 100%; margin-top: 1; }

    .tab-header {
        padding: 0 0 1 0;
        border-bottom: solid $primary-darken-3;
    }

    .controls {
        height: 3;
        dock: top;
        background: $panel;
        padding: 0 2;
    }
    .controls Static { padding: 1 0; }

    #week-select, #team-select { width: 18; }
    Button { margin: 0 1; }

    #rosters-box { layout: horizontal; height: 100%; }
    RosterWidget {
        width: 1fr;
        height: 100%;
        padding: 1;
        border: solid $primary-darken-3;
    }
    .roster-title {
        text-align: center;
        padding: 1;
        border-bottom: solid $primary-darken-3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "go_home", "Home"),
        Binding("i", "go_injuries", "Injuries"),
        Binding("m", "go_matchups", "Matchups"),
        Binding("w", "go_waivers", "Waivers"),
        Binding("p", "go_projections", "Projections"),
        Binding("o", "go_rosters", "Rosters"),
        Binding("t", "go_trades", "Trades"),
        Binding("s", "go_playoffs", "Playoffs"),
        Binding("b", "go_bench", "Bench"),
        Binding("?", "help", "Help"),
        Binding("1", "wk1", show=False), Binding("2", "wk2", show=False),
        Binding("3", "wk3", show=False), Binding("4", "wk4", show=False),
        Binding("5", "wk5", show=False), Binding("6", "wk6", show=False),
        Binding("7", "wk7", show=False), Binding("8", "wk8", show=False),
        Binding("9", "wk9", show=False),
        Binding("tab", "cycle_team", "Team"),
    ]

    def __init__(self):
        super().__init__()
        self.week = 1
        self.team = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Horizontal(
                Static(" Week:", classes="lbl"),
                Select([(f"Week {w}", w) for w in range(1, 19)], value=1, id="week-select"),
                Static("  Team:", classes="lbl"),
                Select([("All Teams", "all"), ("Ryan", "ryan"), ("Wife", "wife")], value="all", id="team-select"),
                Button("Refresh", id="btn-refresh", variant="primary"),
                Button("Draft TUI", id="btn-draft"),
                classes="controls",
            ),
            TabbedContent(
                TabPane("Home", DashboardWidget(), id="tab-home"),
                TabPane("Injuries", InjuriesWidget(), id="tab-injuries"),
                TabPane("Matchups", MatchupsWidget(week=1), id="tab-matchups"),
                TabPane("Waivers", WaiversWidget(week=1), id="tab-waivers"),
                TabPane("Projections", ProjectionsWidget(week=1), id="tab-projections"),
                TabPane("Rosters", Container(RosterWidget("ryan"), RosterWidget("wife"), id="rosters-box"), id="tab-rosters"),
                TabPane("Trades", TradesWidget(), id="tab-trades"),
                TabPane("Playoffs", PlayoffsWidget(), id="tab-playoffs"),
                TabPane("Bench", BenchWidget("ryan"), id="tab-bench"),
            ),
            id="main",
        )
        yield Footer()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "week-select":
            self.week = event.value
            self._sync_week()
        elif event.select.id == "team-select":
            self.team = None if event.value == "all" else event.value
            self._sync_team()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh":
            self.action_refresh()
        elif event.button.id == "btn-draft":
            import subprocess
            subprocess.Popen(["uv", "run", "python", "play/draft_tui.py"], start_new_session=True)

    def _sync_week(self) -> None:
        for widget in [MatchupsWidget, WaiversWidget, ProjectionsWidget]:
            try:
                w = self.query_one(widget)
                if hasattr(w, 'set_week'):
                    w.set_week(self.week, self.team) if widget != MatchupsWidget else w.set_week(self.week)
            except Exception:
                pass

    def _sync_team(self) -> None:
        try: self.query_one(WaiversWidget).set_week(self.week, self.team)
        except: pass
        try: self.query_one(ProjectionsWidget).set_week(self.week, self.team)
        except: pass
        try: self.query_one(PlayoffsWidget).set_team(self.team)
        except: pass
        try: self.query_one(BenchWidget).set_team(self.team or "ryan")
        except: pass

    def action_refresh(self) -> None:
        self.notify("Refreshing data...", timeout=1)
        for wtype in [DashboardWidget, InjuriesWidget, TradesWidget, PlayoffsWidget, BenchWidget]:
            try: self.query_one(wtype).refresh_data()
            except: pass
        try:
            for r in self.query(RosterWidget): r.refresh_data()
        except: pass
        self._sync_week()
        self.notify("✓ Refreshed", timeout=2)

    def action_go_home(self) -> None: self.query_one(TabbedContent).active = "tab-home"
    def action_go_injuries(self) -> None: self.query_one(TabbedContent).active = "tab-injuries"
    def action_go_matchups(self) -> None: self.query_one(TabbedContent).active = "tab-matchups"
    def action_go_waivers(self) -> None: self.query_one(TabbedContent).active = "tab-waivers"
    def action_go_projections(self) -> None: self.query_one(TabbedContent).active = "tab-projections"
    def action_go_rosters(self) -> None: self.query_one(TabbedContent).active = "tab-rosters"
    def action_go_trades(self) -> None: self.query_one(TabbedContent).active = "tab-trades"
    def action_go_playoffs(self) -> None: self.query_one(TabbedContent).active = "tab-playoffs"
    def action_go_bench(self) -> None: self.query_one(TabbedContent).active = "tab-bench"

    def action_help(self) -> None:
        self.notify(
            "[bold]Tabs:[/] d=Home i=Injuries m=Matchups w=Waivers p=Proj o=Rosters t=Trades s=Playoffs b=Bench\n"
            "[bold]Other:[/] 1-9=Week Tab=Cycle_Team r=Refresh q=Quit",
            title="Keys", timeout=10
        )

    def _set_wk(self, n: int) -> None:
        self.week = n
        self.query_one("#week-select", Select).value = n
        self._sync_week()

    def action_wk1(self): self._set_wk(1)
    def action_wk2(self): self._set_wk(2)
    def action_wk3(self): self._set_wk(3)
    def action_wk4(self): self._set_wk(4)
    def action_wk5(self): self._set_wk(5)
    def action_wk6(self): self._set_wk(6)
    def action_wk7(self): self._set_wk(7)
    def action_wk8(self): self._set_wk(8)
    def action_wk9(self): self._set_wk(9)

    def action_cycle_team(self) -> None:
        self.team = {"ryan": "wife", "wife": None}.get(self.team, "ryan")
        self.query_one("#team-select", Select).value = self.team or "all"
        self._sync_team()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    app = FantasyTUI()
    app.title = "Fantasy Football"
    app.sub_title = "Command Center"
    app.run()


if __name__ == "__main__":
    main()
