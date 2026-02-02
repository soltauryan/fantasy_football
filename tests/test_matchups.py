"""
Tests for utils/matchups.py - Matchup analysis utilities.
"""

import pytest
import polars as pl

from utils.matchups import (
    calculate_defense_rankings,
    get_position_matchups,
    get_soft_matchups,
    get_team_schedule_difficulty,
    get_matchup_grade,
    get_opponent_for_game,
    load_schedule,
)


class TestDefenseRankings:
    """Tests for defense ranking calculations."""

    def test_rankings_returns_dataframe(self):
        """Defense rankings should return a DataFrame."""
        result = calculate_defense_rankings(2024, min_games=3)
        assert isinstance(result, pl.DataFrame)

    def test_rankings_has_all_positions(self):
        """Rankings should include all fantasy positions."""
        result = calculate_defense_rankings(2024, min_games=3)
        if not result.is_empty():
            positions = result["position"].unique().to_list()
            for pos in ["QB", "RB", "WR", "TE"]:
                assert pos in positions

    def test_rankings_has_expected_columns(self):
        """Rankings should have expected columns."""
        result = calculate_defense_rankings(2024, min_games=3)
        if not result.is_empty():
            expected = ["defense", "position", "pts_allowed", "games", "rank"]
            for col in expected:
                assert col in result.columns

    def test_rankings_rank_is_positive(self):
        """All ranks should be positive integers."""
        result = calculate_defense_rankings(2024, min_games=3)
        if not result.is_empty():
            assert (result["rank"] > 0).all()


class TestPositionMatchups:
    """Tests for position-specific matchup analysis."""

    def test_position_matchups_filters_correctly(self):
        """Position matchups should only return specified position."""
        result = get_position_matchups("RB", 2024)
        if not result.is_empty():
            positions = result["position"].unique().to_list()
            assert positions == ["RB"]

    def test_position_matchups_sorted_by_rank(self):
        """Position matchups should be sorted by rank."""
        result = get_position_matchups("WR", 2024)
        if not result.is_empty() and len(result) > 1:
            ranks = result["rank"].to_list()
            assert ranks == sorted(ranks)


class TestSoftMatchups:
    """Tests for soft matchup identification."""

    def test_soft_matchups_returns_list(self):
        """Soft matchups should return a list."""
        result = get_soft_matchups(1, 2024, top_n=10)
        assert isinstance(result, list)

    def test_soft_matchups_has_expected_keys(self):
        """Each soft matchup should have expected keys."""
        result = get_soft_matchups(1, 2024, top_n=10)
        if result:
            expected_keys = ["team", "opponent", "position", "def_rank", "pts_allowed"]
            for matchup in result:
                for key in expected_keys:
                    assert key in matchup

    def test_soft_matchups_are_actually_soft(self):
        """Soft matchups should have rank <= 10."""
        result = get_soft_matchups(1, 2024, top_n=10)
        for matchup in result:
            assert matchup["def_rank"] <= 10


class TestScheduleDifficulty:
    """Tests for schedule difficulty analysis."""

    def test_schedule_difficulty_returns_dataframe(self):
        """Schedule difficulty should return a DataFrame."""
        result = get_team_schedule_difficulty("KC", 2024, "RB")
        assert isinstance(result, pl.DataFrame)

    def test_schedule_difficulty_has_all_weeks(self):
        """Schedule should have multiple weeks."""
        result = get_team_schedule_difficulty("KC", 2024, "RB")
        if not result.is_empty():
            assert len(result) >= 10  # At least 10 regular season games

    def test_schedule_difficulty_has_matchup_grade(self):
        """Schedule should include matchup grades."""
        result = get_team_schedule_difficulty("SF", 2024, "WR")
        if not result.is_empty():
            assert "matchup_grade" in result.columns
            # Grades should be valid
            valid_grades = ["A+", "A", "B", "C", "D", "F"]
            for grade in result["matchup_grade"].to_list():
                assert grade in valid_grades


class TestMatchupGrade:
    """Tests for matchup grade conversion."""

    @pytest.mark.parametrize("rank,expected", [
        (1, "A+"), (5, "A+"),
        (6, "A"), (10, "A"),
        (11, "B"), (15, "B"),
        (16, "C"), (20, "C"),
        (21, "D"), (26, "D"),
        (27, "F"), (32, "F"),
    ])
    def test_matchup_grade_mapping(self, rank, expected):
        """Test that ranks map to correct grades."""
        assert get_matchup_grade(rank) == expected


class TestOpponentLookup:
    """Tests for opponent lookup in schedule."""

    def test_get_opponent_for_game(self):
        """Should correctly identify opponent for home and away teams."""
        schedule = load_schedule(2024, week=1)
        if not schedule.is_empty():
            row = schedule.row(0, named=True)
            home = row["home_team"]
            away = row["away_team"]

            # Home team's opponent should be away team
            assert get_opponent_for_game(home, 1, schedule) == away
            # Away team's opponent should be home team
            assert get_opponent_for_game(away, 1, schedule) == home

    def test_get_opponent_no_game(self):
        """Should return None if team has no game that week."""
        schedule = load_schedule(2024, week=1)
        # Fake team should return None
        result = get_opponent_for_game("XXX", 1, schedule)
        assert result is None
