import polars as pl
from espn_api.football import League
import traceback

# Configuration
LEAGUE_ID = 1365062471
SEASON_YEAR = 2025
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"
DB_PATH = "sqlite:///data/nfl.db"

def debug_espn():
    print(f"Connecting to ESPN League {LEAGUE_ID} ({SEASON_YEAR})...")
    try:
        league = League(league_id=LEAGUE_ID, year=SEASON_YEAR, espn_s2=ESPN_S2, swid=SWID)
        print(f"Connected: {league.settings.name}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    print("Attempting to fetch Week 1 box scores...")
    try:
        box = league.box_scores(week=1)
        print(f"Week 1 box scores type: {type(box)}")
        print(f"Week 1 box scores length: {len(box)}")
        if box:
            print(f"Sample: {box[0]}")
            print(f"Dir box[0]: {dir(box[0])}")
            print(f"Vars box[0]: {vars(box[0])}")
    except Exception as e:
        print("Error fetching week 1:")
        traceback.print_exc()

    print("\n--- Verifying bronze_espn_teams ---")
    try:
        # uri must be string
        df = pl.read_database_uri("SELECT * FROM bronze_espn_teams", DB_PATH)
        print(df)
    except Exception as e:
        print(f"Error reading teams: {e}")

if __name__ == "__main__":
    debug_espn()
