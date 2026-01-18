import argparse
import sys
import polars as pl

# Force utf-8 output for Windows terminals
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = "sqlite:///data/nfl.db"

def load_data():
    try:
        teams = pl.read_database_uri("SELECT * FROM bronze_espn_teams", DB_PATH, engine="adbc")
        rosters = pl.read_database_uri("SELECT * FROM bronze_espn_rosters", DB_PATH, engine="adbc")
        free_agents = pl.read_database_uri("SELECT * FROM bronze_espn_free_agents", DB_PATH, engine="adbc")
        power_rankings = pl.read_database_uri("SELECT * FROM bronze_espn_power_rankings", DB_PATH, engine="adbc")
        return teams, rosters, free_agents, power_rankings
    except Exception as e:
        print(f"Error loading data: {e}")
        return None, None, None, None

def analyze_team(team_name, rosters, free_agents, teams):
    print(f"\n{'='*40}")
    print(f"Analysis for Team: {team_name}")
    print(f"{'='*40}")

    # Get team ID
    team_row = teams.filter(pl.col("team_name") == team_name)
    if team_row.is_empty():
        print(f"Team '{team_name}' not found.")
        return
    team_id = team_row["team_id"][0]

    # 1. Roster Optimization (Bench vs Start)
    print("\n--- Roster Optimization ---")
    team_roster = rosters.filter(pl.col("team_id") == team_id)
    
    # Simple heuristic: Sort all players by projected points
    sorted_roster = team_roster.sort("projected_total_points", descending=True)
    
    # Display top projected players
    print(sorted_roster.select(["player_name", "position", "projected_total_points", "total_points"]))

    # 2. Waiver Wire Targets
    print("\n--- Waiver Wire Targets ---")
    # Filter free agents with high owned % or high projected points
    # Compare with team's bottom 3 players (by total_points)
    
    bottom_players = team_roster.sort("total_points").head(3)
    avg_bottom_points = bottom_players["total_points"].mean()
    
    print("Consider Dropping:")
    for row in bottom_players.iter_rows(named=True):
        print(f" - {row['player_name']} ({row['position']}): {row['total_points']} pts")

    print("\nTop Available Free Agents:")
    # Filter by decent availability and points
    top_fa = free_agents.sort("projected_total_points", descending=True).head(5)
    for row in top_fa.iter_rows(named=True):
        diff = row['total_points'] - avg_bottom_points if avg_bottom_points else 0
        if diff > 0:
            print(f" + {row['player_name']} ({row['position']}): {row['projected_total_points']} proj / {row['total_points']} total")

    # 3. Power Ranking Context
    print("\n--- Power Ranking Context ---")
    # Not implemented fully as power rankings linking might need name match or id match
    # Assuming standard flow
    pass

def main():
    parser = argparse.ArgumentParser(description="Weekly Fantasy Football Optimizer")
    parser.add_argument("--team", type=str, help="Name of your team")
    args = parser.parse_args()

    teams, rosters, free_agents, power_rankings = load_data()
    
    if teams is None:
        return

    target_team = args.team
    if not target_team:
        # Default to the first team if none specified, or list all
        print("Available Teams:")
        print(teams.select("team_name"))
        target_team = teams["team_name"][0] # Just pick first for demo
        print(f"\nNo team specified. Running for: {target_team}")

    analyze_team(target_team, rosters, free_agents, teams)

if __name__ == "__main__":
    main()
