#!/usr/bin/env python3
"""
Draft Assistant TUI - Fantasy Football 2026

Simple player rankings with ADP/VOR sorting and position filtering.

Controls:
    1/2/3/4  - Filter by QB/RB/WR/TE
    0        - Show all positions
    v        - Toggle sort: VOR / ADP
    Space    - Mark selected player as drafted
    u        - Undo last pick
    /        - Search player
    q        - Quit
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import polars as pl
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, DataTable, Input
from textual.binding import Binding

from utils.db import get_connection, read_sqlite_robust
from utils.draft import (
    load_projections,
    add_vor_to_projections,
    add_adp_to_projections,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MY_TEAM_IDS = {"ryan": 6, "wife": 9}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA LOADING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_players() -> pl.DataFrame:
    """Load all player projections with VOR and ADP."""
    df = load_projections()
    df = add_vor_to_projections(df)
    df = add_adp_to_projections(df)
    return df


def load_team_names() -> dict:
    """Load team names from database."""
    conn = get_connection()
    df = read_sqlite_robust("SELECT team_id, team_name FROM bronze_espn_teams", conn)
    conn.close()
    return {
        key: df.filter(pl.col("team_id") == tid)["team_name"][0]
        if len(df.filter(pl.col("team_id") == tid)) > 0 else f"Team {tid}"
        for key, tid in MY_TEAM_IDS.items()
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN APPLICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DraftApp(App):
    """Simple draft assistant with player rankings."""

    CSS = """
    Screen { background: $surface; }

    #status-bar {
        dock: top;
        height: 3;
        background: $panel;
        padding: 1 2;
    }

    #main-table {
        height: 1fr;
    }

    #search-bar {
        dock: bottom;
        height: 3;
        padding: 0 2;
        display: none;
    }

    #search-bar.visible {
        display: block;
    }

    .drafted {
        color: $text-disabled;
        text-style: strike;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "filter_qb", "QB"),
        Binding("2", "filter_rb", "RB"),
        Binding("3", "filter_wr", "WR"),
        Binding("4", "filter_te", "TE"),
        Binding("0", "filter_all", "All"),
        Binding("v", "toggle_sort", "VOR/ADP"),
        Binding("space", "draft_selected", "Draft"),
        Binding("u", "undo", "Undo"),
        Binding("/", "search", "Search"),
        Binding("escape", "clear_search", "Clear", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.players = load_players()
        self.teams = load_team_names()
        self.drafted: set[str] = set()
        self.history: list[str] = []
        self.position_filter: str | None = None
        self.sort_by = "vor"  # "vor" or "adp"
        self.search_query = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="status-bar")
        yield DataTable(id="main-table", zebra_stripes=True, cursor_type="row")
        with Container(id="search-bar"):
            yield Input(placeholder="Search player name...", id="search-input")
        yield Footer()

    def on_mount(self) -> None:
        self._update_status()
        self._refresh_table()

    # ─────────────────────────────────────────────────────────────────────────
    #  Status Bar
    # ─────────────────────────────────────────────────────────────────────────

    def _update_status(self) -> None:
        pos = self.position_filter or "ALL"
        sort_label = "VOR" if self.sort_by == "vor" else "ADP"
        drafted_count = len(self.drafted)

        status = (
            f"[bold]Position:[/] [{self._pos_color(pos)}]{pos}[/]  │  "
            f"[bold]Sort:[/] [cyan]{sort_label}[/]  │  "
            f"[bold]Drafted:[/] {drafted_count}  │  "
            f"[dim]1-4=Pos  0=All  v=Sort  Space=Draft  u=Undo  /=Search[/]"
        )
        self.query_one("#status-bar", Static).update(status)

    def _pos_color(self, pos: str) -> str:
        return {"QB": "bright_red", "RB": "bright_green", "WR": "bright_blue", "TE": "bright_yellow", "ALL": "white"}.get(pos, "white")

    # ─────────────────────────────────────────────────────────────────────────
    #  Table Refresh
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_table(self) -> None:
        table = self.query_one("#main-table", DataTable)
        table.clear(columns=True)

        # Columns based on sort mode
        if self.sort_by == "vor":
            table.add_columns("#", "Player", "Pos", "Team", "PPG", "Points", "VOR", "ADP")
        else:
            table.add_columns("ADP", "Player", "Pos", "Team", "PPG", "Points", "VOR", "#")

        # Filter data
        df = self.players

        # Position filter
        if self.position_filter:
            df = df.filter(pl.col("position") == self.position_filter)

        # Search filter
        if self.search_query:
            df = df.filter(pl.col("player_name").str.to_lowercase().str.contains(self.search_query.lower()))

        # Sort
        if self.sort_by == "vor":
            df = df.sort("vor", descending=True)
        else:
            df = df.filter(pl.col("adp").is_not_null()).sort("adp")

        # Add rows
        for i, row in enumerate(df.head(100).iter_rows(named=True), 1):
            name = row["player_name"]
            pos = row["position"]
            team = row.get("team", "") or ""
            ppg = row.get("proj_ppg_2026", 0) or 0
            pts = row.get("proj_total_points_2026", 0) or 0
            vor = row.get("vor", 0) or 0
            adp = row.get("adp")

            # Format values
            adp_str = f"{adp:.1f}" if adp else "—"
            vor_str = f"{vor:+.1f}" if vor else "—"

            # Color coding
            pos_color = self._pos_color(pos)
            vor_color = "green" if vor > 0 else "red" if vor < 0 else "white"

            # Check if drafted
            is_drafted = name in self.drafted
            style = "dim strike" if is_drafted else ""

            if is_drafted:
                name_display = f"[{style}]{name}[/]"
                pos_display = f"[{style}]{pos}[/]"
            else:
                name_display = f"[bold]{name}[/]"
                pos_display = f"[{pos_color}]{pos}[/]"

            if self.sort_by == "vor":
                table.add_row(
                    str(i),
                    name_display,
                    pos_display,
                    team[:4],
                    f"{ppg:.1f}",
                    f"{pts:.0f}",
                    f"[{vor_color}]{vor_str}[/]" if not is_drafted else f"[{style}]{vor_str}[/]",
                    adp_str if not is_drafted else f"[{style}]{adp_str}[/]",
                    key=f"row-{i}"
                )
            else:
                table.add_row(
                    adp_str if not is_drafted else f"[{style}]{adp_str}[/]",
                    name_display,
                    pos_display,
                    team[:4],
                    f"{ppg:.1f}",
                    f"{pts:.0f}",
                    f"[{vor_color}]{vor_str}[/]" if not is_drafted else f"[{style}]{vor_str}[/]",
                    str(i),
                    key=f"row-{i}"
                )

    # ─────────────────────────────────────────────────────────────────────────
    #  Actions
    # ─────────────────────────────────────────────────────────────────────────

    def action_filter_qb(self) -> None:
        self.position_filter = "QB"
        self._update_status()
        self._refresh_table()

    def action_filter_rb(self) -> None:
        self.position_filter = "RB"
        self._update_status()
        self._refresh_table()

    def action_filter_wr(self) -> None:
        self.position_filter = "WR"
        self._update_status()
        self._refresh_table()

    def action_filter_te(self) -> None:
        self.position_filter = "TE"
        self._update_status()
        self._refresh_table()

    def action_filter_all(self) -> None:
        self.position_filter = None
        self._update_status()
        self._refresh_table()

    def action_toggle_sort(self) -> None:
        self.sort_by = "adp" if self.sort_by == "vor" else "vor"
        self._update_status()
        self._refresh_table()

    def action_draft_selected(self) -> None:
        table = self.query_one("#main-table", DataTable)
        if table.cursor_row is not None:
            row_data = table.get_row_at(table.cursor_row)
            # Player name is always column 1 (index 1)
            name = row_data[1]
            # Strip any markup
            import re
            name = re.sub(r'\[.*?\]', '', str(name))

            if name and name not in self.drafted:
                self.drafted.add(name)
                self.history.append(name)
                self.notify(f"Drafted: {name}", timeout=2)
                self._update_status()
                self._refresh_table()

    def action_undo(self) -> None:
        if self.history:
            name = self.history.pop()
            self.drafted.discard(name)
            self.notify(f"Undrafted: {name}", timeout=2)
            self._update_status()
            self._refresh_table()

    def action_search(self) -> None:
        search_bar = self.query_one("#search-bar")
        search_bar.add_class("visible")
        self.query_one("#search-input", Input).focus()

    def action_clear_search(self) -> None:
        self.search_query = ""
        search_bar = self.query_one("#search-bar")
        search_bar.remove_class("visible")
        self.query_one("#search-input", Input).value = ""
        self._refresh_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self.search_query = event.value
            self._refresh_table()
            # Hide search bar but keep filter active
            self.query_one("#search-bar").remove_class("visible")
            self.query_one("#main-table").focus()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    app = DraftApp()
    app.title = "Draft Assistant"
    app.sub_title = "Fantasy Football 2026"
    app.run()


if __name__ == "__main__":
    main()
