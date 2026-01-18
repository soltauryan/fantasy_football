from espn_api.football import League

# Configuration
LEAGUE_ID = 1365062471
SEASON_YEAR = 2025
SWID = "{D2241401-9D06-46E7-84DB-B5878BA69DBD}"
ESPN_S2 = "AEA6s487YT1GrFEFWnpw0MpjPtXYDjNQ%2Fn%2FD%2B9A2GMwtEY5lnL%2B3rrL9bwWJX6oxs8gS4%2B3QBkDBRTCtVxeFc1SWRGYAbSZps5Jp1qFQJqWLO8KzdwVRKrIYVChYEQHqVEydsFdM30uIc3%2BFeGxjcIWln7nOJg8BFIDt0TJAhJpA6a8RgAcx9xZxIraTaia7z%2F1VXAytigfjLKy7ErgnA9SuojVObO5wsx852FuWL4K0PMl9VfIpSaVkVyq9KWtIdAmPANB4EM7boPSO9YhXrx%2FBasgmSITqBgOMzZNeJpKe4E3RX%2F1NpJmg7nmebZLcLpmdnF0Da807qmpHG5Qwfz93"

def debug_fa():
    league = League(league_id=LEAGUE_ID, year=SEASON_YEAR, espn_s2=ESPN_S2, swid=SWID)
    fas = league.free_agents(size=5)
    for p in fas:
        print(f"Name: {p.name}, Type: {type(p.name)}")
        print(f"Pos: {p.position}, Type: {type(p.position)}")
        print(f"Pro: {p.proTeam}, Type: {type(p.proTeam)}")
        print(f"Inj: {p.injuryStatus}, Type: {type(p.injuryStatus)}")
        print(f"TeamId: {p.onTeamId}, Type: {type(p.onTeamId)}")
        print("-" * 20)

if __name__ == "__main__":
    debug_fa()
