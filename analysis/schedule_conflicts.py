"""
Scheduling Conflicts Analysis
Identifies weeks where multiple players on your roster are on Bye.
Infers Bye weeks from 'silver_weekly_performance' (teams not playing).
"""

import polars as pl
import os
import sys

# Add project root to path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.db import get_connection, read_sqlite_robust, DB_PATH

def infer_bye_weeks(conn):
    """
    Infer bye weeks from silver_weekly_performance.
    A team is on bye if they have NO stats in a given regular season week.
    """
    print("Inferring NFL Bye Weeks...")
    # Get latest season
    query = "SELECT MAX(season) as max_season FROM silver_weekly_performance"
    df_max = read_sqlite_robust(query, conn)
    season = df_max["max_season"][0]
    
    print(f"  Analyzing Season: {season}")
    
    # Get all team-week combos
    query_sched = f"""
    SELECT DISTINCT team, week 
    FROM silver_weekly_performance 
    WHERE season = {season} AND week <= 18
    ORDER BY week
    """
    df_sched = read_sqlite_robust(query_sched, conn)
    
    # Get all teams
    teams = df_sched["team"].unique().to_list()
    weeks = range(1, 19) # 1-18
    
    bye_data = []
    
    for team in teams:
        # Find weeks where this team is NOT in df_sched
        team_weeks = df_sched.filter(pl.col("team") == team)["week"].to_list()
        missing_weeks = [w for w in weeks if w not in team_weeks]
        
        # Filter for likely bye weeks (usually weeks 5-14, but can vary)
        # If a team is missing week 1, they might be effectively on bye or data issue?
        # Usually each team has exactly 1 bye.
        for w in missing_weeks:
            bye_data.append({"pro_team": team, "bye_week": w})
            
    df_byes = pl.DataFrame(bye_data)
    
    # Normalize check: Usually 1 bye per team.
    # Group by team and count
    counts = df_byes.group_by("pro_team").len()
    abnormal = counts.filter(pl.col("len") != 1)
    if len(abnormal) > 0:
        print(f"  Warning: Some teams have != 1 bye week inferred: {abnormal}")
    
    print(f"  Inferred {len(df_byes)} bye weeks.")
    return df_byes, season

def analyze_roster_conflicts(conn, df_byes):
    """
    Check user rosters for bye week overlap.
    """
    print("Loading User Rosters...")
    try:
        df_rosters = read_sqlite_robust("SELECT * FROM bronze_espn_rosters", conn)
    except Exception as e:
        print("  Error loading rosters. Make sure ingest_espn.py has been run.")
        print(f"  {e}")
        return

    if len(df_rosters) == 0:
        print("  No roster data found.")
        return

    # Normalize pro_team column if needed
    # (Assuming basic match for now)
    
    # Join Roster with Byes
    df_conflict = df_rosters.join(df_byes, on="pro_team", how="left")
    
    # Filter where we have bye info
    df_conflict = df_conflict.filter(pl.col("bye_week").is_not_null())
    
    # Group by User Team and Bye Week
    df_analysis = df_conflict.group_by(["team_id", "bye_week"]).agg([
        pl.col("player_name").alias("players"),
        pl.col("position").alias("positions"),
        pl.len().alias("player_count"),
        # Count starters vs bench? 
        # lineup_slot != 20 (Bench) usually, need to check mapping. 
        # For now just count all.
    ])
    
    # Filter for "Problem Weeks" (e.g. > 2 players on bye)
    df_problems = df_analysis.filter(pl.col("player_count") >= 3).sort(["team_id", "bye_week"])
    
    print("\n" + "="*60)
    print("SCHEDULING CONFLICT REPORT (3+ Players on Bye)")
    print("="*60)
    
    if len(df_problems) == 0:
        print("No major conflicts found (no weeks with 3+ players on bye).")
    
    current_team = None
    for row in df_problems.iter_rows(named=True):
        if row["team_id"] != current_team:
            print(f"\nTeam {row['team_id']}:")
            current_team = row["team_id"]
            
        print(f"  Week {row['bye_week']}: {row['player_count']} players on Bye")
        players = row["players"] # list
        positions = row["positions"] # list
        
        # formatting
        player_substrs = [f"{p} ({pos})" for p, pos in zip(players, positions)]
        print(f"    - {', '.join(player_substrs)}")

    # Also check "Position Scarcity" (e.g. 2 QBs on bye in 2QB league, or 0 QBs available)
    # If counting starters is possible, that's better.
    # Assuming standard league, maybe checking if ALL QBs are on bye?
    
    print("\n" + "="*60)
    print("POSITIONAL CONFLICTS (e.g. Startable positions depleted)")
    print("="*60)
    
    # ... logic for specific positional heavy weeks ...
    # For simplicity, let's just show the breakdown above.
    
    # Return dataframe for further inspect
    return df_analysis

def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = get_connection()
    try:
        df_byes, season = infer_bye_weeks(conn)
        analyze_roster_conflicts(conn, df_byes)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
