"""
Tests for utils/weekly.py - Weekly analysis utilities.
"""

import pytest
import polars as pl
from unittest.mock import patch, MagicMock

from utils.weekly import (
    get_snap_trends,
    get_target_share_trends,
    get_team_target_distribution,
)
from utils.matchups import get_matchup_grade


class TestSnapTrends:
    """Tests for snap count trend analysis."""

    def test_snap_trends_returns_dataframe(self):
        """Snap trends should return a DataFrame."""
        # This tests against actual data
        result = get_snap_trends(2024, min_weeks=3, min_trend=10.0)
        assert isinstance(result, pl.DataFrame)

    def test_snap_trends_has_expected_columns(self):
        """Snap trends should have expected columns."""
        result = get_snap_trends(2024, min_weeks=3, min_trend=10.0)
        if not result.is_empty():
            expected_cols = ["full_name", "position", "team", "snap_trend"]
            for col in expected_cols:
                assert col in result.columns


class TestTargetShareTrends:
    """Tests for target share trend analysis."""

    def test_target_trends_returns_dataframe(self):
        """Target trends should return a DataFrame."""
        result = get_target_share_trends(2024, min_weeks=3)
        assert isinstance(result, pl.DataFrame)

    def test_target_trends_positive_only(self):
        """Target trends should only include positive trends."""
        result = get_target_share_trends(2024, min_weeks=3)
        if not result.is_empty():
            assert (result["share_trend"] > 0).all()


class TestMatchupGrades:
    """Tests for matchup grading."""

    def test_matchup_grade_a_plus(self):
        """Rank 1-5 should be A+."""
        from utils.matchups import get_matchup_grade
        assert get_matchup_grade(1) == "A+"
        assert get_matchup_grade(5) == "A+"

    def test_matchup_grade_a(self):
        """Rank 6-10 should be A."""
        from utils.matchups import get_matchup_grade
        assert get_matchup_grade(6) == "A"
        assert get_matchup_grade(10) == "A"

    def test_matchup_grade_b(self):
        """Rank 11-15 should be B."""
        from utils.matchups import get_matchup_grade
        assert get_matchup_grade(11) == "B"
        assert get_matchup_grade(15) == "B"

    def test_matchup_grade_c(self):
        """Rank 16-20 should be C."""
        from utils.matchups import get_matchup_grade
        assert get_matchup_grade(16) == "C"
        assert get_matchup_grade(20) == "C"

    def test_matchup_grade_d(self):
        """Rank 21-26 should be D."""
        from utils.matchups import get_matchup_grade
        assert get_matchup_grade(21) == "D"
        assert get_matchup_grade(26) == "D"

    def test_matchup_grade_f(self):
        """Rank 27-32 should be F."""
        from utils.matchups import get_matchup_grade
        assert get_matchup_grade(27) == "F"
        assert get_matchup_grade(32) == "F"


class TestTeamTargetDistribution:
    """Tests for team target distribution."""

    def test_distribution_returns_dataframe(self):
        """Target distribution should return a DataFrame."""
        result = get_team_target_distribution("KC", 2024)
        assert isinstance(result, pl.DataFrame)

    def test_distribution_sorted_by_targets(self):
        """Distribution should be sorted by total targets descending."""
        result = get_team_target_distribution("KC", 2024)
        if not result.is_empty() and len(result) > 1:
            targets = result["total_targets"].to_list()
            assert targets == sorted(targets, reverse=True)
