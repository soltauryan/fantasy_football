import argparse
import sys
import time
import polars as pl
from espn_api.football import League

# Force utf-8 output for Windows terminals
sys.stdout.reconfigure(encoding='utf-8')

# ESPN Configuration (from ingest_espn.py)
LEAGUE_ID = 1365062471
SEASON_YEAR = 2025
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"

DB_PATH = "sqlite:///data/nfl.db"

# Draft target roster composition
DRAFT_TARGETS = {
    "QB": 2,
    "RB": 5,
    "WR": 5,
    "TE": 2,
    "D/ST": 1,
    "K": 1
}


def refresh_draft_data():
    """Connect to ESPN and fetch current draft state."""
    print("Connecting to ESPN...")
    try:
        league = League(league_id=LEAGUE_ID, year=SEASON_YEAR, espn_s2=ESPN_S2, swid=SWID)
    except Exception as e:
        print(f"Error connecting to ESPN: {e}")
        return None, None

    print(f"Connected to: {league.settings.name}")

    # Extract teams for name lookup
    teams_data = []
    for team in league.teams:
        teams_data.append({
            "team_id": team.team_id,
            "team_name": team.team_name,
        })
    teams_df = pl.DataFrame(teams_data)

    # Extract draft picks
    draft_data = []
    for pick in league.draft:
        draft_data.append({
            "round_num": pick.round_num,
            "round_pick": pick.round_pick,
            "team_id": pick.team.team_id if pick.team else None,
            "player_name": pick.playerName,
            "bid_amount": pick.bid_amount,
        })

    if not draft_data:
        print("No draft picks found.")
        return pl.DataFrame(), teams_df

    draft_df = pl.DataFrame(draft_data)

    # Join with teams to get team names
    draft_df = draft_df.join(teams_df, on="team_id", how="left")

    return draft_df, teams_df


def load_cached_draft():
    """Load draft data from cached ESPN tables."""
    try:
        draft = pl.read_database_uri("SELECT * FROM bronze_espn_draft", DB_PATH, engine="adbc")
        teams = pl.read_database_uri("SELECT team_id, team_name FROM bronze_espn_teams", DB_PATH, engine="adbc")
        draft = draft.join(teams, on="team_id", how="left")
        return draft, teams
    except Exception as e:
        print(f"Error loading cached draft data: {e}")
        print("Run with --refresh to fetch from ESPN")
        return None, None


def load_rankings():
    """Load player rankings from gold_master_rankings."""
    try:
        return pl.read_database_uri(
            "SELECT player_name, position, team, master_score, master_id FROM gold_master_rankings ORDER BY master_score DESC",
            DB_PATH, engine="adbc"
        )
    except Exception as e:
        print(f"Error loading rankings: {e}")
        return None


def load_value_predictions():
    """Load ML value predictions for sleeper identification."""
    try:
        return pl.read_csv("data/player_value_predictions.csv")
    except Exception as e:
        print(f"Error loading value predictions: {e}")
        return None


def extract_bye_weeks():
    """
    Extract bye weeks from bronze_schedules.
    A bye week is a week where a team has no game (neither home nor away).
    """
    try:
        schedules = pl.read_database_uri(
            f"SELECT week, home_team, away_team FROM bronze_schedules WHERE season = {SEASON_YEAR}",
            DB_PATH, engine="adbc"
        )
    except Exception as e:
        print(f"Error loading schedules: {e}")
        return None

    if schedules.is_empty():
        print(f"No schedule data found for {SEASON_YEAR}")
        return None

    # Get all unique teams (from both home and away)
    home_teams = schedules.select(pl.col("home_team").alias("team")).unique()
    away_teams = schedules.select(pl.col("away_team").alias("team")).unique()
    all_teams = pl.concat([home_teams, away_teams]).unique()

    # Get all weeks in the schedule
    all_weeks = schedules.select("week").unique()

    # Create all possible team-week combinations
    all_combinations = all_teams.join(all_weeks, how="cross")

    # Get actual games played (team appears as home or away)
    home_games = schedules.select([pl.col("week"), pl.col("home_team").alias("team")])
    away_games = schedules.select([pl.col("week"), pl.col("away_team").alias("team")])
    games_played = pl.concat([home_games, away_games]).unique()

    # Bye weeks = all combinations minus games played
    bye_weeks = all_combinations.join(
        games_played, on=["team", "week"], how="anti"
    ).rename({"week": "bye_week"})

    # Filter to regular season only (weeks 1-18)
    bye_weeks = bye_weeks.filter(pl.col("bye_week") <= 18)

    return bye_weeks


def load_espn_rosters():
    """Load ESPN rosters for position/team fallback."""
    try:
        return pl.read_database_uri(
            "SELECT player_name, position, pro_team as team FROM bronze_espn_rosters",
            DB_PATH, engine="adbc"
        )
    except:
        return None


def enrich_draft_picks(draft_df, rankings):
    """Add position and NFL team info to draft picks from rankings."""
    if draft_df is None or draft_df.is_empty():
        return draft_df

    # Normalize rankings positions (PK -> K)
    rankings_normalized = None
    if rankings is not None:
        rankings_normalized = rankings.with_columns(
            pl.when(pl.col("position") == "PK")
            .then(pl.lit("K"))
            .otherwise(pl.col("position"))
            .alias("position")
        )

    # Join on player name to get position and team from rankings
    if rankings_normalized is not None:
        enriched = draft_df.join(
            rankings_normalized.select(["player_name", "position", "team"]),
            on="player_name",
            how="left"
        )
    else:
        enriched = draft_df.with_columns([
            pl.lit(None).alias("position"),
            pl.lit(None).alias("team")
        ])

    # Use ESPN rosters as fallback for missing positions (D/ST, etc.)
    espn_rosters = load_espn_rosters()
    if espn_rosters is not None:
        # For rows where position is null, try to fill from ESPN rosters
        espn_lookup = espn_rosters.unique(subset=["player_name"])
        enriched = enriched.join(
            espn_lookup.select([
                pl.col("player_name"),
                pl.col("position").alias("espn_position"),
                pl.col("team").alias("espn_team")
            ]),
            on="player_name",
            how="left"
        )
        # Coalesce: use rankings data first, then ESPN data
        enriched = enriched.with_columns([
            pl.coalesce(["position", "espn_position"]).alias("position"),
            pl.coalesce(["team", "espn_team"]).alias("team")
        ]).drop(["espn_position", "espn_team"])

    return enriched


def analyze_bye_conflicts(my_picks, bye_weeks):
    """Analyze bye week conflicts for drafted players."""
    if bye_weeks is None or my_picks is None or my_picks.is_empty():
        return {}

    # Join picks with bye weeks on NFL team
    players_with_byes = my_picks.join(
        bye_weeks,
        left_on="team",
        right_on="team",
        how="left"
    )

    # Group by bye week
    conflicts = {}
    for row in players_with_byes.iter_rows(named=True):
        bye = row.get("bye_week")
        if bye is not None:
            if bye not in conflicts:
                conflicts[bye] = []
            conflicts[bye].append({
                "name": row["player_name"],
                "position": row.get("position", "?")
            })

    return conflicts


def check_position_balance(my_picks):
    """Check current roster balance vs. draft targets."""
    print("\n[ROSTER BALANCE]")

    if my_picks is None or my_picks.is_empty():
        print("  No picks yet.")
        return

    counts = my_picks.group_by("position").len()

    for pos, target in DRAFT_TARGETS.items():
        curr_count = 0
        row = counts.filter(pl.col("position") == pos)
        if not row.is_empty():
            curr_count = row["len"][0]

        remaining = target - curr_count
        if remaining > 0:
            print(f"  [WARNING] {pos}: {curr_count}/{target} (need {remaining} more)")
        else:
            print(f"  [OK] {pos}: {curr_count}/{target}")


def display_bye_week_conflicts(conflicts):
    """Display bye week conflicts in a visual format."""
    print("\n[BYE WEEK CONFLICTS]")

    if not conflicts:
        print("  No bye week data available.")
        return

    for week in sorted(conflicts.keys()):
        players = conflicts[week]
        if len(players) >= 2:
            print(f"  [WARNING] Week {week}: {len(players)} players on bye")
            for p in players:
                print(f"    - {p['name']} ({p['position']})")
        elif len(players) == 1:
            print(f"  Week {week}: 1 player")
            for p in players:
                print(f"    - {p['name']} ({p['position']})")


def get_best_available(all_picks, rankings, top_n=3):
    """Get best available players by position (not yet drafted)."""
    print("\n[BEST AVAILABLE]")

    if rankings is None:
        print("  Rankings not available.")
        return

    # Get list of drafted player names
    drafted_names = []
    if all_picks is not None and not all_picks.is_empty():
        drafted_names = all_picks.select("player_name").to_series().to_list()

    # Filter out drafted players
    available = rankings.filter(~pl.col("player_name").is_in(drafted_names))

    for pos in ["QB", "RB", "WR", "TE", "D/ST", "K"]:
        print(f"  {pos}:")
        pos_available = available.filter(pl.col("position") == pos).head(top_n)

        if pos_available.is_empty():
            print(f"    (none available)")
            continue

        for row in pos_available.iter_rows(named=True):
            team = row.get('team', '?')
            score = row.get('master_score', 0)
            print(f"    {row['player_name']} ({team}) - Score: {score:.1f}")


def get_sleepers(all_picks, value_predictions, top_n=10):
    """Get undervalued players (sleepers) who are still available."""
    print("\n[VALUE PICKS / SLEEPERS]")
    print("  (Players model predicts are undervalued)")

    if value_predictions is None:
        print("  Value predictions not available.")
        return

    # Get list of drafted player names
    drafted_names = []
    if all_picks is not None and not all_picks.is_empty():
        drafted_names = all_picks.select("player_name").to_series().to_list()

    # Filter for available players with positive value_delta (undervalued)
    available_sleepers = value_predictions.filter(
        (~pl.col("player_name").is_in(drafted_names)) &
        (pl.col("value_delta") > 0)
    ).sort("value_delta", descending=True)

    if available_sleepers.is_empty():
        print("  No sleepers found.")
        return

    for row in available_sleepers.head(top_n).iter_rows(named=True):
        delta = row.get('value_delta', 0)
        print(f"    {row['player_name']} ({row['position']}) - Value Delta: +{delta:.1f}")


def display_my_picks(my_picks):
    """Display the current team's draft picks."""
    print("\n[MY PICKS]")

    if my_picks is None or my_picks.is_empty():
        print("  No picks yet.")
        return

    # Sort by round/pick
    sorted_picks = my_picks.sort(["round_num", "round_pick"])

    for row in sorted_picks.iter_rows(named=True):
        rd = row.get('round_num', '?')
        pick = row.get('round_pick', '?')
        name = row.get('player_name', '?')
        pos = row.get('position', '?')
        team = row.get('team', '?')
        print(f"  Rd {rd}.{pick}: {name} ({pos}, {team})")


def run_analysis(draft_df, teams_df, rankings, value_predictions, bye_weeks, target_team):
    """Run the full draft analysis."""
    # Get team ID
    team_row = teams_df.filter(pl.col("team_name") == target_team)
    if team_row.is_empty():
        print(f"Team '{target_team}' not found.")
        print("Available teams:")
        for row in teams_df.iter_rows(named=True):
            print(f"  - {row['team_name']}")
        return

    team_id = team_row["team_id"][0]

    # Enrich draft picks with position/team info
    draft_df = enrich_draft_picks(draft_df, rankings)

    # Filter for my picks
    my_picks = None
    if draft_df is not None and not draft_df.is_empty():
        my_picks = draft_df.filter(pl.col("team_id") == team_id)

    total_picks = len(draft_df) if draft_df is not None else 0
    my_pick_count = len(my_picks) if my_picks is not None else 0

    # Header
    print(f"\n{'='*60}")
    print(f"DRAFT ANALYZER - {total_picks} total picks | {my_pick_count} by {target_team}")
    print(f"{'='*60}")

    # Show my picks
    display_my_picks(my_picks)

    # Check position balance
    check_position_balance(my_picks)

    # Bye week conflicts
    conflicts = analyze_bye_conflicts(my_picks, bye_weeks)
    display_bye_week_conflicts(conflicts)

    # Best available
    get_best_available(draft_df, rankings)

    # Sleepers
    get_sleepers(draft_df, value_predictions)


def main():
    parser = argparse.ArgumentParser(description="Fantasy Football Draft Analyzer")
    parser.add_argument("--team", type=str, help="Your fantasy team name")
    parser.add_argument("--refresh", action="store_true", help="Refresh data from ESPN")
    parser.add_argument("--watch", action="store_true", help="Live watch mode (refresh every 30s)")
    args = parser.parse_args()

    # Load static data
    rankings = load_rankings()
    value_predictions = load_value_predictions()
    bye_weeks = extract_bye_weeks()

    while True:
        # Load draft data
        if args.refresh or args.watch:
            draft_df, teams_df = refresh_draft_data()
        else:
            draft_df, teams_df = load_cached_draft()

        if teams_df is None:
            print("Failed to load data. Exiting.")
            return

        # Determine target team
        target_team = args.team
        if not target_team:
            print("\nAvailable Teams:")
            for row in teams_df.iter_rows(named=True):
                print(f"  - {row['team_name']}")
            target_team = teams_df["team_name"][0]
            print(f"\nNo team specified. Running for: {target_team}")

        # Run analysis
        run_analysis(draft_df, teams_df, rankings, value_predictions, bye_weeks, target_team)

        # Exit or continue watching
        if not args.watch:
            break

        print(f"\n{'='*60}")
        print("[Refreshing in 30 seconds... Press Ctrl+C to exit]")
        print(f"{'='*60}")
        try:
            time.sleep(30)
        except KeyboardInterrupt:
            print("\nExiting watch mode.")
            break


if __name__ == "__main__":
    main()
