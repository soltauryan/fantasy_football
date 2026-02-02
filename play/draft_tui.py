#!/usr/bin/env python3
"""
Draft Assistant TUI - 2026 Fantasy Football

Rich text-based user interface for draft day.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import polars as pl
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, DataTable, Input, Button, Label,
    TabbedContent, TabPane, Log
)
from textual.binding import Binding
from textual.message import Message
from textual import events

from utils.db import get_connection, read_sqlite_robust
from utils.draft import (
    load_projections,
    add_vor_to_projections,
    add_adp_to_projections,
    get_best_available,
    calculate_position_scarcity,
    get_positional_needs,
    recommend_pick,
    analyze_pick_value,
    get_value_picks,
    get_upcoming_targets,
    get_pick_value,
    evaluate_trade,
    parse_pick_notation,
    DRAFT_TARGETS,
)


# ESPN Configuration
LEAGUE_ID = 1365062471

# Team configuration (IDs are stable)
MY_TEAM_IDS = {
    "ryan": 6,
    "wife": 9,
}


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


class DraftState:
    """Holds all draft state data."""

    def __init__(self):
        self.projections = add_adp_to_projections(
            add_vor_to_projections(load_projections())
        )
        self.teams = load_team_names()
        self.taken_players: set[str] = set()
        self.rosters = {"ryan": [], "wife": []}
        self.history = []
        self.pick_number = 0
        self.current_team = "ryan"  # Which team is drafting next

    def pick_player(self, name: str, team_key: str = None) -> dict | None:
        """Mark a player as picked. Returns player data or None."""
        player_row = self.projections.filter(
            pl.col("player_name").str.to_lowercase() == name.lower()
        )
        if len(player_row) == 0:
            # Try contains match
            player_row = self.projections.filter(
                pl.col("player_name").str.to_lowercase().str.contains(name.lower())
            )

        if len(player_row) == 0:
            return None
        if len(player_row) > 1:
            return None  # Ambiguous

        player = player_row.row(0, named=True)
        player_name = player["player_name"]

        if player_name in self.taken_players:
            return None

        self.taken_players.add(player_name)
        self.pick_number += 1
        self.history.append(("pick", player_name, team_key))

        if team_key and team_key in self.rosters:
            self.rosters[team_key].append(player)

        return player

    def undo(self) -> str | None:
        """Undo last action. Returns player name or None."""
        if not self.history:
            return None

        action, name, team_key = self.history.pop()
        self.taken_players.discard(name)
        self.pick_number -= 1

        if team_key and team_key in self.rosters:
            self.rosters[team_key] = [
                p for p in self.rosters[team_key] if p["player_name"] != name
            ]

        return name


class PlayerTable(DataTable):
    """Custom data table for players."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor_type = "row"
        self.zebra_stripes = True


class RosterPanel(Static):
    """Panel showing a team's roster."""

    def __init__(self, team_key: str, team_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team_key = team_key
        self.team_name = team_name

    def compose(self) -> ComposeResult:
        yield Label(f"[bold]{self.team_name}[/bold]", id=f"roster-title-{self.team_key}")
        yield Static("", id=f"roster-content-{self.team_key}")

    def update_roster(self, roster: list[dict], needs: dict[str, int]):
        content = self.query_one(f"#roster-content-{self.team_key}", Static)

        if not roster:
            content.update("[dim]No players drafted[/dim]")
            return

        lines = []
        by_pos = {}
        total_pts = 0

        for p in roster:
            pos = p.get("position", "?")
            if pos not in by_pos:
                by_pos[pos] = []
            by_pos[pos].append(p)
            total_pts += p.get("proj_total_points_2026", 0) or 0

        for pos in ["QB", "RB", "WR", "TE", "K", "D/ST"]:
            if pos in by_pos:
                for p in by_pos[pos]:
                    pts = p.get("proj_total_points_2026", 0) or 0
                    lines.append(f"[cyan]{pos}[/cyan] {p['player_name'][:18]:<18} {pts:>5.0f}")

        lines.append(f"[dim]{'─' * 28}[/dim]")
        lines.append(f"[bold]Total: {total_pts:.0f} pts[/bold]")

        if needs:
            needs_str = ", ".join(f"{pos}:{n}" for pos, n in needs.items())
            lines.append(f"[yellow]Need: {needs_str}[/yellow]")

        content.update("\n".join(lines))


class ScarcityPanel(Static):
    """Panel showing position scarcity."""

    def compose(self) -> ComposeResult:
        yield Label("[bold]Position Scarcity[/bold]")
        yield Static("", id="scarcity-content")

    def update_scarcity(self, scarcity: dict):
        content = self.query_one("#scarcity-content", Static)
        lines = []

        for pos, data in scarcity.items():
            elite = data["remaining_elite"]
            total = data["total_available"]

            if data["scarcity_alert"]:
                lines.append(f"[red bold]{pos}: {elite}/5 elite ({total} avail) ⚠[/red bold]")
            elif elite <= 2:
                lines.append(f"[yellow]{pos}: {elite}/5 elite ({total} avail)[/yellow]")
            else:
                lines.append(f"[green]{pos}: {elite}/5 elite ({total} avail)[/green]")

        content.update("\n".join(lines))


class DraftApp(App):
    """Main Draft Assistant TUI Application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 3;
        grid-columns: 1fr 2fr 1fr;
        grid-rows: auto 1fr auto;
    }

    #header-bar {
        column-span: 3;
        height: 3;
        background: $primary-darken-2;
        padding: 0 1;
    }

    #left-panel {
        row-span: 1;
        padding: 1;
        border: solid $primary;
    }

    #main-panel {
        row-span: 1;
        padding: 1;
        border: solid $primary;
    }

    #right-panel {
        row-span: 1;
        padding: 1;
        border: solid $primary;
    }

    #bottom-bar {
        column-span: 3;
        height: auto;
        max-height: 12;
        padding: 1;
        border: solid $primary;
    }

    #command-input {
        width: 100%;
    }

    #log-panel {
        height: 6;
        border: solid $secondary;
    }

    RosterPanel {
        height: auto;
        margin-bottom: 1;
    }

    ScarcityPanel {
        height: auto;
    }

    DataTable {
        height: 100%;
    }

    .tab-content {
        padding: 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("u", "undo", "Undo"),
        Binding("1", "filter_qb", "QB"),
        Binding("2", "filter_rb", "RB"),
        Binding("3", "filter_wr", "WR"),
        Binding("4", "filter_te", "TE"),
        Binding("0", "filter_all", "All"),
        Binding("v", "toggle_vor", "VOR/ADP"),
        Binding("tab", "switch_team", "Switch Team"),
        Binding("/", "focus_command", "Command"),
    ]

    def __init__(self):
        super().__init__()
        self.state = DraftState()
        self.position_filter = None
        self.sort_by_vor = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Header bar with status
        with Container(id="header-bar"):
            yield Static(self._get_status_text(), id="status-text")

        # Left panel - rosters
        with Vertical(id="left-panel"):
            yield RosterPanel("ryan", self.state.teams["ryan"]["team_name"], id="roster-ryan")
            yield RosterPanel("wife", self.state.teams["wife"]["team_name"], id="roster-wife")

        # Main panel - player tables
        with Vertical(id="main-panel"):
            with TabbedContent(id="player-tabs"):
                with TabPane("Best Available", id="tab-avail"):
                    yield PlayerTable(id="table-avail")
                with TabPane("By ADP", id="tab-adp"):
                    yield PlayerTable(id="table-adp")
                with TabPane("Value Picks", id="tab-value"):
                    yield PlayerTable(id="table-value")
                with TabPane("Recommendations", id="tab-rec"):
                    yield PlayerTable(id="table-rec")

        # Right panel - scarcity
        with Vertical(id="right-panel"):
            yield ScarcityPanel(id="scarcity-panel")
            yield Static("", id="pick-info")

        # Bottom bar - command input and log
        with Vertical(id="bottom-bar"):
            yield Input(placeholder="Command: pick/draft/trade/search...", id="command-input")
            yield Log(id="log-panel", highlight=True)

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the app."""
        self._refresh_all()
        self.log_message("Draft Assistant ready. Type 'help' for commands.")

    def _get_status_text(self) -> str:
        """Get status bar text."""
        pick = self.state.pick_number
        taken = len(self.state.taken_players)
        team = self.state.current_team.upper()
        team_name = self.state.teams[self.state.current_team]["team_name"]
        filter_str = f" [{self.position_filter}]" if self.position_filter else ""
        sort_str = "VOR" if self.sort_by_vor else "ADP"

        return f"[bold]Pick #{pick + 1}[/bold] | Taken: {taken} | Drafting: [cyan]{team_name}[/cyan] | Sort: {sort_str}{filter_str}"

    def _refresh_all(self) -> None:
        """Refresh all panels."""
        self._refresh_status()
        self._refresh_tables()
        self._refresh_rosters()
        self._refresh_scarcity()

    def _refresh_status(self) -> None:
        """Refresh status bar."""
        status = self.query_one("#status-text", Static)
        status.update(self._get_status_text())

    def _refresh_tables(self) -> None:
        """Refresh all player tables."""
        # Best available (VOR)
        table_avail = self.query_one("#table-avail", PlayerTable)
        table_avail.clear(columns=True)
        table_avail.add_columns("Rank", "Player", "Pos", "Pts", "VOR", "ADP")

        best = get_best_available(
            self.state.projections,
            self.state.taken_players,
            position=self.position_filter,
            limit=50,
            sort_by="vor"
        )

        for i, row in enumerate(best.iter_rows(named=True), 1):
            adp = row.get("adp")
            adp_str = f"{adp:.1f}" if adp else "N/A"
            vor = row.get("vor", 0) or 0
            pts = row.get("proj_total_points_2026", 0) or 0

            table_avail.add_row(
                str(i),
                row["player_name"],
                row["position"],
                f"{pts:.0f}",
                f"{vor:+.1f}",
                adp_str,
                key=f"avail-{i}"
            )

        # By ADP
        table_adp = self.query_one("#table-adp", PlayerTable)
        table_adp.clear(columns=True)
        table_adp.add_columns("ADP", "Player", "Pos", "Pts", "VOR")

        available = self.state.projections.filter(
            (~pl.col("player_name").is_in(list(self.state.taken_players))) &
            (pl.col("adp").is_not_null())
        )
        if self.position_filter:
            available = available.filter(pl.col("position") == self.position_filter)

        for i, row in enumerate(available.sort("adp").head(50).iter_rows(named=True), 1):
            vor = row.get("vor", 0) or 0
            pts = row.get("proj_total_points_2026", 0) or 0
            adp = row.get("adp", 0) or 0

            table_adp.add_row(
                f"{adp:.1f}",
                row["player_name"],
                row["position"],
                f"{pts:.0f}",
                f"{vor:+.1f}",
                key=f"adp-{i}"
            )

        # Value picks
        table_value = self.query_one("#table-value", PlayerTable)
        table_value.clear(columns=True)
        table_value.add_columns("Player", "Pos", "ADP", "Current", "Value")

        value_picks = get_value_picks(
            self.state.projections,
            self.state.taken_players,
            self.state.pick_number + 1
        )

        for i, row in enumerate(value_picks.head(20).iter_rows(named=True), 1):
            adp = row.get("adp", 0) or 0
            value = row.get("adp_value", 0) or 0

            table_value.add_row(
                row["player_name"],
                row["position"],
                f"{adp:.1f}",
                str(self.state.pick_number + 1),
                f"+{value:.1f}",
                key=f"value-{i}"
            )

        # Recommendations
        table_rec = self.query_one("#table-rec", PlayerTable)
        table_rec.clear(columns=True)
        table_rec.add_columns("Player", "Pos", "Pts", "VOR", "Reason")

        recs = recommend_pick(
            self.state.projections,
            self.state.taken_players,
            self.state.rosters[self.state.current_team]
        )

        for i, row in enumerate(recs.head(15).iter_rows(named=True), 1):
            vor = row.get("vor", 0) or 0
            pts = row.get("proj_pts", 0) or 0
            reason = row.get("reason", "")

            table_rec.add_row(
                row["player_name"],
                row["position"],
                f"{pts:.0f}",
                f"{vor:+.1f}",
                reason[:30],
                key=f"rec-{i}"
            )

    def _refresh_rosters(self) -> None:
        """Refresh roster panels."""
        for team_key in ["ryan", "wife"]:
            panel = self.query_one(f"#roster-{team_key}", RosterPanel)
            roster = self.state.rosters[team_key]
            needs = get_positional_needs(roster)
            panel.update_roster(roster, needs)

    def _refresh_scarcity(self) -> None:
        """Refresh scarcity panel."""
        panel = self.query_one("#scarcity-panel", ScarcityPanel)
        scarcity = calculate_position_scarcity(
            self.state.projections,
            self.state.taken_players
        )
        panel.update_scarcity(scarcity)

    def log_message(self, message: str) -> None:
        """Add message to log."""
        log = self.query_one("#log-panel", Log)
        log.write_line(message)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command input."""
        command = event.value.strip()
        event.input.value = ""

        if not command:
            return

        await self._process_command(command)

    async def _process_command(self, command: str) -> None:
        """Process a command."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            self.log_message("Commands: pick <name>, draft <team> <name>, search <name>, trade, undo, quit")
            self.log_message("Keys: 1=QB, 2=RB, 3=WR, 4=TE, 0=All, v=Toggle VOR/ADP, Tab=Switch team")

        elif cmd == "pick":
            if not args:
                self.log_message("[red]Usage: pick <player name>[/red]")
                return
            player = self.state.pick_player(args)
            if player:
                analysis = analyze_pick_value(player["player_name"], self.state.pick_number, self.state.projections)
                adp_str = f"ADP: {analysis['adp']:.1f}" if analysis['adp'] else "ADP: N/A"
                self.log_message(f"[yellow]#{self.state.pick_number}[/yellow] {player['player_name']} ({player['position']}) - {adp_str} [{analysis['assessment']}]")
                self._refresh_all()
            else:
                self.log_message(f"[red]Player not found or already taken: {args}[/red]")

        elif cmd == "draft":
            cmd_parts = args.split(maxsplit=1)
            if len(cmd_parts) < 2:
                self.log_message("[red]Usage: draft <ryan|wife> <player name>[/red]")
                return

            team_key = cmd_parts[0].lower()
            player_name = cmd_parts[1]

            if team_key not in self.state.teams:
                self.log_message(f"[red]Unknown team: {team_key}. Use 'ryan' or 'wife'[/red]")
                return

            player = self.state.pick_player(player_name, team_key)
            if player:
                team_name = self.state.teams[team_key]["team_name"]
                analysis = analyze_pick_value(player["player_name"], self.state.pick_number, self.state.projections)
                adp_str = f"ADP: {analysis['adp']:.1f}" if analysis['adp'] else "ADP: N/A"
                color = "cyan" if team_key == "ryan" else "magenta"
                self.log_message(f"[{color}]#{self.state.pick_number} {player['player_name']} -> {team_name}[/{color}] - {adp_str} [{analysis['assessment']}]")
                self._refresh_all()
            else:
                self.log_message(f"[red]Player not found or already taken: {player_name}[/red]")

        elif cmd == "search":
            if not args:
                self.log_message("[red]Usage: search <player name>[/red]")
                return

            matches = self.state.projections.filter(
                pl.col("player_name").str.to_lowercase().str.contains(args.lower())
            ).head(5)

            if len(matches) == 0:
                self.log_message(f"[red]No players found matching '{args}'[/red]")
            else:
                for row in matches.iter_rows(named=True):
                    name = row["player_name"]
                    status = "[red](TAKEN)[/red]" if name in self.state.taken_players else "[green](avail)[/green]"
                    vor = row.get("vor", 0) or 0
                    adp = row.get("adp")
                    adp_str = f"ADP:{adp:.1f}" if adp else "ADP:N/A"
                    self.log_message(f"  {name} ({row['position']}) - VOR:{vor:+.1f} {adp_str} {status}")

        elif cmd == "trade":
            self.log_message("Trade calculator: Enter 'trade <give> for <receive>'")
            self.log_message("Example: trade 10 for 20,35")

        elif cmd == "undo":
            name = self.state.undo()
            if name:
                self.log_message(f"[yellow]Undid: {name} back on board[/yellow]")
                self._refresh_all()
            else:
                self.log_message("[red]Nothing to undo[/red]")

        elif cmd in ["q", "quit", "exit"]:
            self.exit()

        else:
            self.log_message(f"[red]Unknown command: {cmd}. Type 'help' for commands.[/red]")

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()

    def action_refresh(self) -> None:
        """Refresh all panels."""
        self._refresh_all()
        self.log_message("Refreshed.")

    def action_undo(self) -> None:
        """Undo last action."""
        name = self.state.undo()
        if name:
            self.log_message(f"[yellow]Undid: {name} back on board[/yellow]")
            self._refresh_all()

    def action_filter_qb(self) -> None:
        self.position_filter = "QB"
        self._refresh_all()

    def action_filter_rb(self) -> None:
        self.position_filter = "RB"
        self._refresh_all()

    def action_filter_wr(self) -> None:
        self.position_filter = "WR"
        self._refresh_all()

    def action_filter_te(self) -> None:
        self.position_filter = "TE"
        self._refresh_all()

    def action_filter_all(self) -> None:
        self.position_filter = None
        self._refresh_all()

    def action_toggle_vor(self) -> None:
        self.sort_by_vor = not self.sort_by_vor
        self._refresh_all()

    def action_switch_team(self) -> None:
        """Switch active team."""
        self.state.current_team = "wife" if self.state.current_team == "ryan" else "ryan"
        self._refresh_all()
        team_name = self.state.teams[self.state.current_team]["team_name"]
        self.log_message(f"Switched to [bold]{team_name}[/bold]")

    def action_focus_command(self) -> None:
        """Focus the command input."""
        self.query_one("#command-input", Input).focus()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - draft player to current team."""
        if event.row_key:
            player_name = str(event.row_key.value)
            team_key = self.state.current_team

            player = self.state.pick_player(player_name, team_key)
            if player:
                team_name = self.state.teams[team_key]["team_name"]
                analysis = analyze_pick_value(player["player_name"], self.state.pick_number, self.state.projections)
                adp_str = f"ADP: {analysis['adp']:.1f}" if analysis['adp'] else "ADP: N/A"
                color = "cyan" if team_key == "ryan" else "magenta"
                self.log_message(f"[{color}]#{self.state.pick_number} {player['player_name']} -> {team_name}[/{color}] - {adp_str} [{analysis['assessment']}]")
                self._refresh_all()


def main():
    app = DraftApp()
    app.run()


if __name__ == "__main__":
    main()
