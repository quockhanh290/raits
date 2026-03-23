"""
tests/coordinator/test_conflict_resolver.py

Coverage targets
----------------
Position limits:
  - ORB capped at 2
  - VWAP_MR capped at 3
  - TREND_FOLLOW capped at 2
  - Total capped at 5

Duplicate ticker:
  - Signal rejected if ticker already in open_tickers
  - Signal rejected if same ticker accepted earlier this bar

Priority ordering:
  - TREND_FOLLOW wins over ORB on same ticker
  - ORB wins over VWAP_MR on same ticker

General:
  - Multiple tickers accepted in one bar (different strategies)
  - Empty candidates returns empty list
  - check_position_limits standalone helper
"""

import pytest
from raits.coordinator.conflict_resolver import (
    ConflictResolver, SignalPriority, ResolvedSignal, MAX_POSITIONS,
)

def sig(direction="LONG"):
    return {"direction": direction, "entry_price": 100.0,
            "stop_loss": 98.0, "target": 104.0, "rvol": 2.5}


class TestBasicAcceptance:
    def setup_method(self):
        self.r = ConflictResolver()

    def test_empty_candidates_returns_empty(self):
        result = self.r.resolve({}, set(), {})
        assert result == []

    def test_single_signal_accepted(self):
        candidates = {"ORB": {"AAPL": sig()}}
        result = self.r.resolve(candidates, set(), {"ORB": 0})
        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].strategy == "ORB"

    def test_multiple_different_tickers_accepted(self):
        candidates = {
            "ORB": {"AAPL": sig(), "TSLA": sig()},
        }
        result = self.r.resolve(candidates, set(), {"ORB": 0})
        assert len(result) == 2

    def test_signal_dict_preserved(self):
        s = sig("SHORT")
        candidates = {"ORB": {"AAPL": s}}
        result = self.r.resolve(candidates, set(), {"ORB": 0})
        assert result[0].signal == s


class TestDuplicateTicker:
    def setup_method(self):
        self.r = ConflictResolver()

    def test_open_ticker_rejected(self):
        candidates = {"ORB": {"AAPL": sig()}}
        result = self.r.resolve(candidates, {"AAPL"}, {"ORB": 0})
        assert result == []

    def test_intra_bar_duplicate_rejected(self):
        """Same ticker from two strategies — only first (higher priority) accepted."""
        candidates = {
            "TREND_FOLLOW": {"AAPL": sig()},
            "ORB":          {"AAPL": sig()},
        }
        result = self.r.resolve(candidates, set(), {"TREND_FOLLOW": 0, "ORB": 0})
        assert len(result) == 1
        assert result[0].strategy == "TREND_FOLLOW"


class TestPositionLimits:
    def setup_method(self):
        self.r = ConflictResolver()

    def test_orb_cap_at_2(self):
        candidates = {"ORB": {"AAPL": sig(), "TSLA": sig(), "NVDA": sig()}}
        result = self.r.resolve(candidates, set(), {"ORB": 0})
        orb_results = [r for r in result if r.strategy == "ORB"]
        assert len(orb_results) <= MAX_POSITIONS["ORB"]

    def test_orb_cap_with_existing(self):
        """Already have 2 ORB positions — new ones rejected."""
        candidates = {"ORB": {"AAPL": sig()}}
        result = self.r.resolve(candidates, set(), {"ORB": 2})
        assert result == []

    def test_vwap_mr_cap_at_3(self):
        candidates = {"VWAP_MR": {
            "A": sig(), "B": sig(), "C": sig(), "D": sig(),
        }}
        result = self.r.resolve(candidates, set(), {"VWAP_MR": 0})
        vwap_results = [r for r in result if r.strategy == "VWAP_MR"]
        assert len(vwap_results) <= MAX_POSITIONS["VWAP_MR"]

    def test_trend_follow_cap_at_2(self):
        candidates = {"TREND_FOLLOW": {"A": sig(), "B": sig(), "C": sig()}}
        result = self.r.resolve(candidates, set(), {"TREND_FOLLOW": 0})
        tf_results = [r for r in result if r.strategy == "TREND_FOLLOW"]
        assert len(tf_results) <= MAX_POSITIONS["TREND_FOLLOW"]

    def test_global_cap_at_5(self):
        """Already have 4 positions — only 1 more can be added."""
        candidates = {
            "ORB":    {"AAPL": sig(), "TSLA": sig()},
            "VWAP_MR": {"MSFT": sig()},
        }
        positions = {"ORB": 2, "VWAP_MR": 1, "TREND_FOLLOW": 1}  # total=4
        result = self.r.resolve(candidates, set(), positions)
        assert len(result) == 1   # only one slot left

    def test_global_cap_full_rejects_all(self):
        """Already at 5 — nothing accepted."""
        candidates = {"ORB": {"AAPL": sig()}}
        positions = {"ORB": 2, "VWAP_MR": 1, "TREND_FOLLOW": 2}  # total=5
        result = self.r.resolve(candidates, set(), positions)
        assert result == []


class TestPriorityOrdering:
    def setup_method(self):
        self.r = ConflictResolver()

    def test_trend_beats_orb_same_ticker(self):
        candidates = {
            "TREND_FOLLOW": {"AAPL": sig()},
            "ORB":          {"AAPL": sig()},
        }
        result = self.r.resolve(candidates, set(), {"TREND_FOLLOW": 0, "ORB": 0})
        assert len(result) == 1
        assert result[0].strategy == "TREND_FOLLOW"

    def test_orb_beats_vwap_same_ticker(self):
        candidates = {
            "ORB":     {"AAPL": sig()},
            "VWAP_MR": {"AAPL": sig()},
        }
        result = self.r.resolve(candidates, set(), {"ORB": 0, "VWAP_MR": 0})
        assert len(result) == 1
        assert result[0].strategy == "ORB"

    def test_trend_beats_vwap_same_ticker(self):
        candidates = {
            "TREND_FOLLOW": {"AAPL": sig()},
            "VWAP_MR":      {"AAPL": sig()},
        }
        result = self.r.resolve(candidates, set(), {"TREND_FOLLOW": 0, "VWAP_MR": 0})
        assert len(result) == 1
        assert result[0].strategy == "TREND_FOLLOW"

    def test_different_tickers_all_accepted(self):
        """Different tickers from different strategies all pass."""
        candidates = {
            "TREND_FOLLOW": {"AAPL": sig()},
            "ORB":          {"TSLA": sig()},
            "VWAP_MR":      {"MSFT": sig()},
        }
        result = self.r.resolve(candidates, set(), {"TREND_FOLLOW": 0, "ORB": 0, "VWAP_MR": 0})
        assert len(result) == 3

    def test_priority_enum_ordering(self):
        assert SignalPriority.TREND_FOLLOW < SignalPriority.ORB < SignalPriority.VWAP_MR


class TestCheckPositionLimitsHelper:
    def test_within_limits_returns_true(self):
        ok, reason = ConflictResolver.check_position_limits("ORB", {"ORB": 1}, 2)
        assert ok is True

    def test_strategy_cap_exceeded_returns_false(self):
        ok, reason = ConflictResolver.check_position_limits("ORB", {"ORB": 2}, 2)
        assert ok is False
        assert "ORB" in reason

    def test_global_cap_exceeded_returns_false(self):
        ok, reason = ConflictResolver.check_position_limits("ORB", {"ORB": 0}, 5)
        assert ok is False
        assert "Global" in reason or "cap" in reason.lower()

    def test_unknown_strategy_only_global_check(self):
        ok, _ = ConflictResolver.check_position_limits("UNKNOWN", {}, 0)
        assert ok is True
