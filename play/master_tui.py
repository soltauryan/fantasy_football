#!/usr/bin/env python3
"""
Fantasy Football Master TUI - 2026 Season

Unified interface for all fantasy football analysis tools:
- Dashboard overview
- Injury impact analysis
- Matchup analyzer
- Waiver wire rankings
- Weekly projections
- Draft assistant launcher

Usage:
    uv run python play/master_tui.py
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import polars as pl
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, DataTable, Input, Button, Label,
    TabbedContent, TabPane, Select, Rule
)
from textual.binding import Binding
from textual.screen import Screen

from utils.db import get_connection, read_sqlite_robust
from utils.weekly import (
    analyze_injury_impact_espn,
    get_snap_trends,
    get_target_share_trends,
)
from utils.matchups import (
    calculate_defense_rankings,
    get_soft_matchups,
    get_matchup_grade,
    load_schedule,
    get_opponent_for_game,
)

# Import analysis modules
from analysis.weekly_projections import generate_projections, PlayerProjection
from analysis.waiver_ranker import rank_waiver_pickups, analyze_for_team
from utils.trades import get_all_trade_values, find_needs_based_trades
from analysis.playoff_optimizer import get_all_playoff_schedules, get_team_playoff_analysis
from analysis.bench_optimizer import get_bench_analysis


# Team configuration
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}

SEASON = 2025


def colorize_grade(grade: str) -> str:
    """Add rich color markup to matchup/schedule grades."""
    grade = grade.strip()
    if grade in ("A+", "Elite"):
        return f"[bold green]{grade}[/]"
    elif grade in ("A", "Starter"):
        return f"[green]{grade}[/]"
    elif grade in ("B", "Flex"):
        return f"[cyan]{grade}[/]"
    elif grade in ("C", "Bench"):
        return f"[white]{grade}[/]"
    elif grade in ("D", "Droppable"):
        return f"[yellow]{grade}[/]"
    elif grade == "F":
        return f"[bold red]{grade}[/]"
    return grade


def colorize_recommendation(rec: str) -> str:
    """Add rich color markup to bench recommendations."""
    if rec == "HOLD":
        return f"[green]{rec}[/]"
    elif rec == "TRADE":
        return f"[cyan]{rec}[/]"
    elif rec == "STASH":
        return f"[yellow]{rec}[/]"
    elif rec == "DROP":
        return f"[red]{rec}[/]"
    return rec


def load_team_names() -> dict[str, dict]:
    """Load team names from database."""
    conn = get_connection()
    teams_df = read_sqlite_robust(
        "SELECT team_id, team_name FROM bronze_espn_teams", conn
    )
    conn.close()

    teams = {}
    for key, team_id in MY_TEAM_IDS.items():
        row = teams_df.filter(pl.col("team_id") == team_id)
        team_name = row["team_name"][0] if len(row) > 0 else f"Team {team_id}"
        teams[key] = {"team_id": team_id, "team_name": team_name}
    return teams


def load_team_rosters() -> dict[str, pl.DataFrame]:
    """Load current rosters for both teams."""
    conn = get_connection()

    rosters = {}
    for team_key, team_id in MY_TEAM_IDS.items():
        df = read_sqlite_robust(f"""
            SELECT
                player_name, position, pro_team as team,
                injury_status, projected_total_points, total_points
            FROM bronze_espn_rosters
            WHERE team_id = {team_id}
            AND position IN ('QB', 'RB', 'WR', 'TE')
            ORDER BY position, projected_total_points DESC
        """, conn)
        rosters[team_key] = df

    conn.close()
    return rosters


class DashboardWidget(Static):
    """Dashboard overview widget."""

    def compose(self) -> ComposeResult:
        yield Static("Loading dashboard...", id="dashboard-content")

    def on_mount(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        teams = load_team_names()
        rosters = load_team_rosters()

        content = []
        content.append("[bold cyan]FANTASY FOOTBALL COMMAND CENTER[/bold cyan]\n")
        content.append(f"Season: {SEASON}\n\n")

        # Team summaries
        for team_key in ["ryan", "wife"]:
            team_name = teams[team_key]["team_name"]
            roster = rosters.get(team_key, pl.DataFrame())

            content.append(f"[bold]{team_name}[/bold]")

            if not roster.is_empty():
                total_proj = roster["projected_total_points"].sum() or 0
                total_pts = roster["total_points"].sum() or 0

                # Count by position
                pos_counts = roster.group_by("position").len()
                pos_str = ", ".join(
                    f"{row['position']}: {row['len']}"
                    for row in pos_counts.iter_rows(named=True)
                )

                # Injured players
                injured = roster.filter(
                    pl.col("injury_status").is_not_null() &
                    ~pl.col("injury_status").is_in(["ACTIVE", "NORMAL"])
                )

                content.append(f"  Roster: {pos_str}")
                content.append(f"  Season Pts: {total_pts:.0f} | Projected: {total_proj:.0f}")

                if not injured.is_empty():
                    inj_names = ", ".join(injured["player_name"].to_list()[:3])
                    content.append(f"  [yellow]Injured: {inj_names}[/yellow]")
            else:
                content.append("  (No roster data)")

            content.append("")

        # Quick stats
        content.append("[bold]Quick Analysis[/bold]")

        # Injury opportunities
        injuries = analyze_injury_impact_espn(SEASON)
        if injuries:
            top_opps = injuries[:3]
            content.append(f"  Top Injury Opportunities:")
            for opp in top_opps:
                content.append(f"    - {opp['backup_player']} (replaces {opp['injured_player']})")

        # Emerging players
        trends = get_snap_trends(SEASON, min_weeks=3, min_trend=15.0)
        if not trends.is_empty():
            content.append(f"  Emerging Players (snap trend):")
            for row in trends.head(3).iter_rows(named=True):
                content.append(f"    - {row['full_name']} (+{row['snap_trend']:.0f}%)")

        self.query_one("#dashboard-content").update("\n".join(content))


class InjuriesWidget(Static):
    """Injury impact analysis widget."""

    def compose(self) -> ComposeResult:
        yield DataTable(id="injuries-table")

    def on_mount(self) -> None:
        self.refresh_injuries()

    def refresh_injuries(self) -> None:
        table = self.query_one("#injuries-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Backup", "Pos", "Team", "Injured", "Status", "Score", "Rostered")

        injuries = analyze_injury_impact_espn(SEASON)

        if not injuries:
            table.add_row("No injury opportunities found", "", "", "", "", "", "")
            return

        # Dedupe by backup player
        seen = set()
        for opp in injuries[:25]:
            backup = opp["backup_player"]
            if backup in seen:
                continue
            seen.add(backup)

            rostered = opp.get("rostered_by") or "FREE"

            # Color code injury status
            status = opp["injury_status"][:8]
            if status in ["OUT", "IR"]:
                status_str = f"[bold red]{status}[/]"
            elif status in ["DOUBTFUL", "DOUBT"]:
                status_str = f"[red]{status}[/]"
            elif status in ["QUESTION", "Q"]:
                status_str = f"[yellow]{status}[/]"
            else:
                status_str = status

            # Color code rostered status
            if rostered == "FREE":
                roster_str = "[dim]free[/]"
            elif rostered.upper() == "RYAN":
                roster_str = "[cyan]RYAN[/]"
            elif rostered.upper() == "WIFE":
                roster_str = "[magenta]WIFE[/]"
            else:
                roster_str = rostered.upper()

            # Color score by opportunity level
            score = opp['opportunity_score']
            if score >= 8:
                score_str = f"[bold green]{score:.1f}[/]"
            elif score >= 5:
                score_str = f"[green]{score:.1f}[/]"
            else:
                score_str = f"{score:.1f}"

            table.add_row(
                backup[:20],
                opp["position"],
                opp["team"],
                opp["injured_player"][:18],
                status_str,
                score_str,
                roster_str,
            )


class MatchupsWidget(Static):
    """Matchup analysis widget."""

    def __init__(self, week: int = 1):
        super().__init__()
        self.week = week

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]Week {self.week} Soft Matchups[/bold]", id="matchups-header")
        yield DataTable(id="matchups-table")

    def on_mount(self) -> None:
        self.refresh_matchups()

    def refresh_matchups(self) -> None:
        table = self.query_one("#matchups-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Team", "vs", "Position", "Rank", "Pts Allowed", "Grade")

        matchups = get_soft_matchups(self.week, SEASON, top_n=25)

        if not matchups:
            table.add_row("No matchups found", "", "", "", "", "")
            return

        for m in matchups[:20]:
            grade = get_matchup_grade(m["def_rank"])
            # Color code by rank (lower rank = better matchup)
            rank = m["def_rank"]
            if rank <= 8:
                rank_str = f"[green]{rank}[/]"
            elif rank <= 16:
                rank_str = f"[cyan]{rank}[/]"
            elif rank <= 24:
                rank_str = f"[yellow]{rank}[/]"
            else:
                rank_str = f"[red]{rank}[/]"

            table.add_row(
                m["team"],
                m["opponent"],
                m["position"],
                rank_str,
                f"{m['pts_allowed']:.1f}",
                colorize_grade(grade),
            )

    def set_week(self, week: int) -> None:
        self.week = week
        self.query_one("#matchups-header").update(f"[bold]Week {week} Soft Matchups[/bold]")
        self.refresh_matchups()


class WaiversWidget(Static):
    """Waiver wire widget."""

    def __init__(self, week: int = 1, team_key: str = None):
        super().__init__()
        self.week = week
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        title = f"[bold]Waiver Wire - Week {self.week}[/bold]"
        if self.team_key:
            title += f" ({self.team_key.upper()})"
        yield Static(title, id="waivers-header")
        yield DataTable(id="waivers-table")

    def on_mount(self) -> None:
        self.refresh_waivers()

    def refresh_waivers(self) -> None:
        table = self.query_one("#waivers-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Player", "Pos", "Team", "Own%", "Match", "Score", "Reasons")

        if self.team_key:
            rankings = analyze_for_team(self.team_key, SEASON, self.week, top_n=20)
        else:
            rankings = rank_waiver_pickups(SEASON, self.week, top_n=20)

        if rankings.is_empty():
            table.add_row("No waiver targets found", "", "", "", "", "", "")
            return

        for row in rankings.iter_rows(named=True):
            matchup = row.get("matchup_grade") or "-"
            reasons = row.get("reasons", "")[:30]

            # Color score by waiver priority
            score = row['waiver_score']
            if score >= 15:
                score_str = f"[bold green]{score:.1f}[/]"
            elif score >= 10:
                score_str = f"[green]{score:.1f}[/]"
            else:
                score_str = f"{score:.1f}"

            table.add_row(
                row["player_name"][:20],
                row["position"],
                row.get("team", "")[:4],
                f"{row['pct_owned']:.0f}%",
                colorize_grade(matchup),
                score_str,
                reasons,
            )

    def set_week(self, week: int, team_key: str = None) -> None:
        self.week = week
        self.team_key = team_key
        title = f"[bold]Waiver Wire - Week {week}[/bold]"
        if team_key:
            title += f" ({team_key.upper()})"
        self.query_one("#waivers-header").update(title)
        self.refresh_waivers()


class ProjectionsWidget(Static):
    """Weekly projections widget."""

    def __init__(self, week: int = 1, team_key: str = None):
        super().__init__()
        self.week = week
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        title = f"[bold]Week {self.week} Projections[/bold]"
        if self.team_key:
            title += f" - {self.team_key.upper()}"
        yield Static(title, id="projections-header")
        yield DataTable(id="projections-table")

    def on_mount(self) -> None:
        self.refresh_projections()

    def refresh_projections(self) -> None:
        table = self.query_one("#projections-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Player", "Pos", "vs", "Match", "Proj", "Floor", "Ceil", "Form")

        projections = generate_projections(
            self.week, SEASON,
            team_key=self.team_key
        )

        if not projections:
            table.add_row("No projections available", "", "", "", "", "", "", "")
            return

        for p in projections[:25]:
            # Color code recent form
            form = p.recent_form
            if form == "Hot":
                form_str = "[bold green]Hot[/]"
            elif form == "Cold":
                form_str = "[bold red]Cold[/]"
            else:
                form_str = form

            table.add_row(
                p.player_name[:20],
                p.position,
                p.opponent,
                colorize_grade(p.matchup_grade),
                f"{p.injury_adjusted:.1f}",
                f"[dim]{p.floor:.1f}[/]",
                f"[cyan]{p.ceiling:.1f}[/]",
                form_str,
            )

    def set_week(self, week: int, team_key: str = None) -> None:
        self.week = week
        self.team_key = team_key
        title = f"[bold]Week {week} Projections[/bold]"
        if team_key:
            title += f" - {team_key.upper()}"
        self.query_one("#projections-header").update(title)
        self.refresh_projections()


class RosterWidget(Static):
    """Team roster widget."""

    def __init__(self, team_key: str):
        super().__init__()
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        teams = load_team_names()
        team_name = teams[self.team_key]["team_name"]
        yield Static(f"[bold]{team_name}[/bold]", id=f"roster-header-{self.team_key}")
        yield DataTable(id=f"roster-table-{self.team_key}")

    def on_mount(self) -> None:
        self.refresh_roster()

    def refresh_roster(self) -> None:
        table = self.query_one(f"#roster-table-{self.team_key}", DataTable)
        table.clear(columns=True)

        table.add_columns("Player", "Pos", "Team", "Pts", "Proj", "Status")

        rosters = load_team_rosters()
        roster = rosters.get(self.team_key, pl.DataFrame())

        if roster.is_empty():
            table.add_row("No roster data", "", "", "", "", "")
            return

        for row in roster.iter_rows(named=True):
            status = row.get("injury_status") or ""
            if status in ["ACTIVE", "NORMAL"]:
                status_str = "[green]OK[/]"
            elif status in ["OUT", "IR"]:
                status_str = f"[bold red]{status[:8]}[/]"
            elif status in ["DOUBTFUL"]:
                status_str = f"[red]{status[:8]}[/]"
            elif status in ["QUESTIONABLE"]:
                status_str = f"[yellow]Q[/]"
            else:
                status_str = status[:8]

            table.add_row(
                row["player_name"][:20],
                row["position"],
                row.get("team", "")[:4],
                f"{row.get('total_points', 0):.0f}",
                f"{row.get('projected_total_points', 0):.0f}",
                status_str,
            )


class TradesWidget(Static):
    """Trade values and suggestions widget."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]Trade Values & Suggestions[/bold]", id="trades-header")
        yield DataTable(id="trades-table")

    def on_mount(self) -> None:
        self.refresh_trades()

    def refresh_trades(self) -> None:
        table = self.query_one("#trades-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Player", "Pos", "Team", "Value", "Tier", "Roster")

        values = get_all_trade_values()

        if not values:
            table.add_row("No trade values available", "", "", "", "", "")
            return

        for v in values[:30]:
            roster = v.rostered_by.upper() if v.rostered_by else "FA"
            # Color code by roster ownership
            if roster == "RYAN":
                roster_str = "[cyan]RYAN[/]"
            elif roster == "WIFE":
                roster_str = "[magenta]WIFE[/]"
            else:
                roster_str = "[dim]FA[/]"

            table.add_row(
                v.player_name[:20],
                v.position,
                v.team[:4] if v.team else "",
                f"{v.final_value:.1f}",
                colorize_grade(v.tier),
                roster_str,
            )


class PlayoffsWidget(Static):
    """Playoff schedule analysis widget."""

    def __init__(self, team_key: str = None):
        super().__init__()
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        title = "[bold]Playoff Schedule (Weeks 14-17)[/bold]"
        if self.team_key:
            title += f" - {self.team_key.upper()}"
        yield Static(title, id="playoffs-header")
        yield DataTable(id="playoffs-table")

    def on_mount(self) -> None:
        self.refresh_playoffs()

    def refresh_playoffs(self) -> None:
        table = self.query_one("#playoffs-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Player", "Pos", "Team", "W14", "W15", "W16", "W17", "Grade")

        if self.team_key:
            schedules = get_team_playoff_analysis(self.team_key, SEASON)
        else:
            schedules = get_all_playoff_schedules(SEASON)

        if not schedules:
            table.add_row("No playoff schedule data", "", "", "", "", "", "", "")
            return

        for s in schedules[:25]:
            table.add_row(
                s.player_name[:20],
                s.position,
                s.team,
                colorize_grade(s.week_14["grade"]),
                colorize_grade(s.week_15["grade"]),
                colorize_grade(s.week_16["grade"]),
                colorize_grade(s.week_17["grade"]),
                colorize_grade(s.schedule_grade),
            )

    def set_team(self, team_key: str = None) -> None:
        self.team_key = team_key
        title = "[bold]Playoff Schedule (Weeks 14-17)[/bold]"
        if team_key:
            title += f" - {team_key.upper()}"
        self.query_one("#playoffs-header").update(title)
        self.refresh_playoffs()


class BenchWidget(Static):
    """Bench optimization widget."""

    def __init__(self, team_key: str = "ryan"):
        super().__init__()
        self.team_key = team_key

    def compose(self) -> ComposeResult:
        yield Static("[bold]Bench Analysis[/bold]", id="bench-header")
        yield DataTable(id="bench-table")

    def on_mount(self) -> None:
        self.refresh_bench()

    def refresh_bench(self) -> None:
        table = self.query_one("#bench-table", DataTable)
        table.clear(columns=True)

        table.add_columns("Player", "Pos", "Value", "Tier", "Rec", "Reasoning")

        analysis = get_bench_analysis(self.team_key)

        if not analysis:
            table.add_row("No bench data available", "", "", "", "", "")
            return

        for p in analysis:
            table.add_row(
                p.player_name[:20],
                p.position,
                f"{p.trade_value:.1f}",
                colorize_grade(p.tier),
                colorize_recommendation(p.recommendation),
                p.reasoning[:25],
            )

    def set_team(self, team_key: str) -> None:
        self.team_key = team_key
        self.query_one("#bench-header").update(f"[bold]Bench Analysis - {team_key.upper()}[/bold]")
        self.refresh_bench()


class MasterTUI(App):
    """Master Fantasy Football TUI Application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
    }

    #main-container {
        height: 100%;
    }

    TabbedContent {
        height: 100%;
    }

    TabPane {
        padding: 1;
    }

    DataTable {
        height: 100%;
    }

    .control-bar {
        height: 3;
        dock: top;
        background: $surface;
        padding: 0 1;
    }

    #week-select {
        width: 15;
    }

    #team-select {
        width: 15;
    }

    Button {
        margin: 0 1;
    }

    #rosters-container {
        layout: horizontal;
        height: 100%;
    }

    RosterWidget {
        width: 1fr;
        height: 100%;
        padding: 0 1;
        border: solid $primary;
    }

    .loading-indicator {
        text-align: center;
        color: $warning;
    }

    .empty-message {
        text-align: center;
        color: $text-muted;
        padding: 2;
    }

    /* Grade colors */
    .grade-elite { color: $success; }
    .grade-good { color: lime; }
    .grade-avg { color: $text; }
    .grade-bad { color: $warning; }
    .grade-terrible { color: $error; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "show_dashboard", "Dashboard", show=True),
        Binding("i", "show_injuries", "Injuries", show=True),
        Binding("m", "show_matchups", "Matchups", show=True),
        Binding("w", "show_waivers", "Waivers", show=True),
        Binding("p", "show_projections", "Projections", show=True),
        Binding("o", "show_rosters", "Rosters", show=False),
        Binding("t", "show_trades", "Trades", show=False),
        Binding("s", "show_playoffs", "Schedules", show=False),
        Binding("b", "show_bench", "Bench", show=False),
        Binding("f1", "show_help", "Help"),
        # Week selection: 1-9 for weeks 1-9, then use selector for 10+
        Binding("1", "set_week_1", "Week 1", show=False),
        Binding("2", "set_week_2", "Week 2", show=False),
        Binding("3", "set_week_3", "Week 3", show=False),
        Binding("4", "set_week_4", "Week 4", show=False),
        Binding("5", "set_week_5", "Week 5", show=False),
        Binding("6", "set_week_6", "Week 6", show=False),
        Binding("7", "set_week_7", "Week 7", show=False),
        Binding("8", "set_week_8", "Week 8", show=False),
        Binding("9", "set_week_9", "Week 9", show=False),
        Binding("tab", "toggle_team", "Team"),
    ]

    def __init__(self):
        super().__init__()
        self.current_week = 1
        self.current_team = None  # None = all, "ryan" or "wife"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Horizontal(
                Static("Week: ", classes="label"),
                Select(
                    [(f"Week {w}", w) for w in range(1, 19)],
                    value=1,
                    id="week-select",
                ),
                Static("  Team: ", classes="label"),
                Select(
                    [("All", "all"), ("Ryan", "ryan"), ("Wife", "wife")],
                    value="all",
                    id="team-select",
                ),
                Button("Refresh", id="refresh-btn", variant="primary"),
                Button("Draft TUI", id="draft-btn"),
                classes="control-bar",
            ),
            TabbedContent(
                TabPane("Dashboard", DashboardWidget(), id="tab-dashboard"),
                TabPane("Injuries", InjuriesWidget(), id="tab-injuries"),
                TabPane("Matchups", MatchupsWidget(week=1), id="tab-matchups"),
                TabPane("Waivers", WaiversWidget(week=1), id="tab-waivers"),
                TabPane("Projections", ProjectionsWidget(week=1), id="tab-projections"),
                TabPane("Rosters", Container(
                    RosterWidget("ryan"),
                    RosterWidget("wife"),
                    id="rosters-container",
                ), id="tab-rosters"),
                TabPane("Trades", TradesWidget(), id="tab-trades"),
                TabPane("Playoffs", PlayoffsWidget(), id="tab-playoffs"),
                TabPane("Bench", BenchWidget("ryan"), id="tab-bench"),
            ),
            id="main-container",
        )
        yield Footer()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "week-select":
            self.current_week = event.value
            self.update_week_dependent_widgets()
        elif event.select.id == "team-select":
            self.current_team = None if event.value == "all" else event.value
            self.update_team_dependent_widgets()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-btn":
            self.action_refresh()
        elif event.button.id == "draft-btn":
            self.action_launch_draft()

    def update_week_dependent_widgets(self) -> None:
        """Update widgets that depend on week selection."""
        try:
            matchups = self.query_one(MatchupsWidget)
            matchups.set_week(self.current_week)
        except Exception:
            pass

        try:
            waivers = self.query_one(WaiversWidget)
            waivers.set_week(self.current_week, self.current_team)
        except Exception:
            pass

        try:
            projections = self.query_one(ProjectionsWidget)
            projections.set_week(self.current_week, self.current_team)
        except Exception:
            pass

    def update_team_dependent_widgets(self) -> None:
        """Update widgets that depend on team selection."""
        try:
            waivers = self.query_one(WaiversWidget)
            waivers.set_week(self.current_week, self.current_team)
        except Exception:
            pass

        try:
            projections = self.query_one(ProjectionsWidget)
            projections.set_week(self.current_week, self.current_team)
        except Exception:
            pass

        try:
            playoffs = self.query_one(PlayoffsWidget)
            playoffs.set_team(self.current_team)
        except Exception:
            pass

        try:
            bench = self.query_one(BenchWidget)
            if self.current_team:
                bench.set_team(self.current_team)
            else:
                bench.set_team("ryan")  # Default to ryan if "all"
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refresh all widgets."""
        self.notify("Refreshing data...", timeout=1)

        try:
            self.query_one(DashboardWidget).refresh_dashboard()
        except Exception:
            pass

        try:
            self.query_one(InjuriesWidget).refresh_injuries()
        except Exception:
            pass

        self.update_week_dependent_widgets()

        try:
            for roster in self.query(RosterWidget):
                roster.refresh_roster()
        except Exception:
            pass

        try:
            self.query_one(TradesWidget).refresh_trades()
        except Exception:
            pass

        try:
            self.query_one(PlayoffsWidget).refresh_playoffs()
        except Exception:
            pass

        try:
            self.query_one(BenchWidget).refresh_bench()
        except Exception:
            pass

        self.notify("Data refreshed!", timeout=2)

    def action_show_dashboard(self) -> None:
        self.query_one(TabbedContent).active = "tab-dashboard"

    def action_show_injuries(self) -> None:
        self.query_one(TabbedContent).active = "tab-injuries"

    def action_show_matchups(self) -> None:
        self.query_one(TabbedContent).active = "tab-matchups"

    def action_show_waivers(self) -> None:
        self.query_one(TabbedContent).active = "tab-waivers"

    def action_show_projections(self) -> None:
        self.query_one(TabbedContent).active = "tab-projections"

    def action_show_rosters(self) -> None:
        self.query_one(TabbedContent).active = "tab-rosters"

    def action_show_trades(self) -> None:
        self.query_one(TabbedContent).active = "tab-trades"

    def action_show_playoffs(self) -> None:
        self.query_one(TabbedContent).active = "tab-playoffs"

    def action_show_bench(self) -> None:
        self.query_one(TabbedContent).active = "tab-bench"

    def action_show_help(self) -> None:
        """Show help/keyboard shortcuts."""
        help_text = """[bold cyan]KEYBOARD SHORTCUTS[/]

[bold]Navigation:[/]
  d - Dashboard       i - Injuries
  m - Matchups        w - Waivers
  p - Projections     o - Rosters
  t - Trades          s - Schedules (Playoffs)
  b - Bench

[bold]Controls:[/]
  1-9 - Set week (1-9)
  Tab - Toggle team (All/Ryan/Wife)
  r   - Refresh data
  q   - Quit

[bold]Tips:[/]
  Use the week dropdown for weeks 10-18
  Green grades = good, Red = bad
"""
        self.notify(help_text, title="Help", timeout=10)

    def _set_week(self, week: int) -> None:
        """Helper to set week and update UI."""
        self.current_week = week
        self.query_one("#week-select", Select).value = week
        self.update_week_dependent_widgets()

    def action_set_week_1(self) -> None:
        self._set_week(1)

    def action_set_week_2(self) -> None:
        self._set_week(2)

    def action_set_week_3(self) -> None:
        self._set_week(3)

    def action_set_week_4(self) -> None:
        self._set_week(4)

    def action_set_week_5(self) -> None:
        self._set_week(5)

    def action_set_week_6(self) -> None:
        self._set_week(6)

    def action_set_week_7(self) -> None:
        self._set_week(7)

    def action_set_week_8(self) -> None:
        self._set_week(8)

    def action_set_week_9(self) -> None:
        self._set_week(9)

    def action_toggle_team(self) -> None:
        """Toggle between all/ryan/wife."""
        if self.current_team is None:
            self.current_team = "ryan"
        elif self.current_team == "ryan":
            self.current_team = "wife"
        else:
            self.current_team = None

        select = self.query_one("#team-select", Select)
        select.value = self.current_team or "all"
        self.update_team_dependent_widgets()

    def action_launch_draft(self) -> None:
        """Launch the draft TUI (in a new terminal)."""
        import subprocess
        subprocess.Popen(
            ["uv", "run", "python", "play/draft_tui.py"],
            start_new_session=True
        )


def main():
    app = MasterTUI()
    app.title = "Fantasy Football Command Center"
    app.run()


if __name__ == "__main__":
    main()
