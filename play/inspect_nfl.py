import nflreadpy as nfl
import inspect

functions = [
    "load_player_stats",
    "load_team_stats",
    "load_schedules",
    "load_players",
    "load_snap_counts",
    "load_nextgen_stats",
    "load_ftn_charting",
    "load_injuries",
    "load_depth_charts",
    "load_ff_playerids",
    "load_ff_opportunity"
]

for func_name in functions:
    if hasattr(nfl, func_name):
        func = getattr(nfl, func_name)
        sig = inspect.signature(func)
        print(f"{func_name}: {sig}")
    else:
        print(f"{func_name}: NOT FOUND")
