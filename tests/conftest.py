"""
Shared test fixtures for fantasy football tests.
"""

import pytest
import polars as pl
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def sample_depth_chart():
    """Sample depth chart data for testing."""
    return pl.DataFrame({
        "season": [2024] * 6,
        "week": [18] * 6,
        "team": ["KC", "KC", "KC", "SF", "SF", "SF"],
        "gsis_id": ["001", "002", "003", "004", "005", "006"],
        "full_name": [
            "Patrick Mahomes", "Carson Wentz", "Matt Moore",
            "Christian McCaffrey", "Elijah Mitchell", "Jordan Mason"
        ],
        "position": ["QB", "QB", "QB", "RB", "RB", "RB"],
        "depth_position": ["QB", "QB", "QB", "RB", "RB", "RB"],
        "pos_rank": [1, 2, 3, 1, 2, 3],
        "formation": ["Offense"] * 6,
    })


@pytest.fixture
def sample_weekly_performance():
    """Sample weekly fantasy performance data."""
    return pl.DataFrame({
        "season": [2025] * 6,
        "week": [1, 1, 2, 2, 3, 3],
        "gsis_id": ["001", "002", "001", "002", "001", "002"],
        "full_name": ["Player A", "Player B", "Player A", "Player B", "Player A", "Player B"],
        "position": ["RB", "WR", "RB", "WR", "RB", "WR"],
        "team": ["KC", "SF", "KC", "SF", "KC", "SF"],
        "fantasy_points": [18.5, 12.3, 22.1, 15.4, 16.8, 8.9],
        "targets": [4, 8, 5, 10, 3, 6],
        "receptions": [3, 6, 4, 8, 2, 5],
        "rec_yards": [25, 65, 32, 85, 18, 42],
        "rush_attempt": [15, 0, 18, 0, 12, 0],
        "rush_yards": [78, 0, 95, 0, 62, 0],
    })


@pytest.fixture
def sample_schedule():
    """Sample schedule data for testing."""
    return pl.DataFrame({
        "season": [2025] * 4,
        "week": [1, 1, 2, 2],
        "game_type": ["REG"] * 4,
        "away_team": ["KC", "SF", "KC", "SF"],
        "home_team": ["DEN", "LAR", "LAC", "SEA"],
        "away_score": [24, 21, 31, 17],
        "home_score": [17, 28, 24, 24],
        "gameday": ["2025-09-07"] * 4,
        "gametime": ["16:25"] * 4,
    })


@pytest.fixture
def sample_defense_rankings():
    """Sample defense rankings for testing."""
    return pl.DataFrame({
        "defense": ["DEN", "LAC", "SF", "SEA"] * 4,
        "position": ["RB"] * 4 + ["WR"] * 4 + ["QB"] * 4 + ["TE"] * 4,
        "pts_allowed": [
            6.5, 7.2, 9.8, 8.5,   # RB
            8.2, 9.1, 10.5, 9.8,  # WR
            15.2, 18.5, 20.1, 17.8,  # QB
            5.5, 6.8, 8.2, 7.5,   # TE
        ],
        "games": [17] * 16,
        "rank": [32, 31, 10, 20] * 4,
    })


@pytest.fixture
def sample_projections():
    """Sample projections data for testing."""
    return pl.DataFrame({
        "full_name": [
            "Josh Allen", "Lamar Jackson", "Patrick Mahomes",
            "Saquon Barkley", "Breece Hall", "Christian McCaffrey",
            "Ja'Marr Chase", "CeeDee Lamb", "Tyreek Hill",
            "Travis Kelce", "George Kittle", "Mark Andrews",
        ],
        "position": ["QB", "QB", "QB", "RB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "TE"],
        "team": ["BUF", "BAL", "KC", "PHI", "NYJ", "SF", "CIN", "DAL", "MIA", "KC", "SF", "BAL"],
        "proj_total_points_2026": [
            380.5, 365.2, 350.8,  # QB
            320.5, 295.2, 288.8,  # RB
            285.5, 275.2, 265.8,  # WR
            245.5, 225.2, 205.8,  # TE
        ],
    })
