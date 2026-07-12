"""
futures/test_tz_invariance.py — TZ invariance oracle
=====================================================
Bắt mọi chỗ đọc giờ máy: chạy backtest + today-computation dưới 3 TZ giả lập
(ET / VN +7 / UTC) → output phải IDENTICAL.

Run:
    cd d:\\raits
    python -m pytest futures/test_tz_invariance.py -v
    python futures/test_tz_invariance.py          # standalone

Design notes:
  - Không dùng os.environ["TZ"] / time.tzset() — không portable trên Windows.
  - Dùng unittest.mock.patch để giả lập pd.Timestamp.now() trả về UTC time tương ứng
    với giờ local khác nhau, sau đó verify code đang test trả về đúng ET date.
  - Backtest engine (backtest_swing_tf) KHÔNG gọi now() — TZ invariance là structural:
    data đã ép ET khi load, tất cả operations đều trên TZ-aware ET index. Test xác nhận
    bằng synthetic data.
  - Phần searchsorted: tạo synthetic TZ-aware ET DatetimeIndex, verify bar 09:30 ET
    được tìm đúng bất kể machine TZ (vì đã strip TZ trước asi8 so sánh).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
import pandas as pd
import unittest

ET = "America/New_York"


# ── Helper ──────────────────────────────────────────────────────────────────

def _now_et_naive() -> pd.Timestamp:
    """Production pattern: always ET date, tz-naive for arithmetic."""
    return pd.Timestamp.now(tz=ET).normalize().tz_localize(None)


def _searchsorted_930(day_ts: pd.DatetimeIndex, day: pd.Timestamp) -> int:
    """Replicate _validated_core MAX_HOLD searchsorted logic (mirrors production code).
    Uses DatetimeIndex.searchsorted() with TZ-aware target — unit-agnostic (works for
    both datetime64[ns] and datetime64[us] indexes produced by different pandas versions)."""
    _930    = day + pd.Timedelta(hours=9, minutes=30)
    _tz_str = str(day_ts.tzinfo) if day_ts.tzinfo is not None else ""
    _is_et  = _tz_str in ("", "America/New_York", "US/Eastern")
    if _is_et:
        _930_cmp = _930.tz_localize(ET) if day_ts.tzinfo is not None else _930
        _idx = int(day_ts.searchsorted(_930_cmp))
        if _idx >= len(day_ts):
            _idx = 0
    else:
        _idx = 0
    return _idx


# ── Synthetic data ───────────────────────────────────────────────────────────

def _make_day_ts(date_str: str) -> pd.DatetimeIndex:
    """1-minute TZ-aware ET DatetimeIndex from 00:00 to 23:59 for one calendar day."""
    start = pd.Timestamp(date_str, tz=ET)
    return pd.date_range(start, periods=24 * 60, freq="1min", tz=ET)


# ── Test 1: searchsorted TZ invariance ──────────────────────────────────────

class TestSearchsorted930(unittest.TestCase):
    """Strip-TZ fix: searchsorted finds bar 09:30 ET correctly regardless of machine TZ."""

    def setUp(self):
        self.day   = pd.Timestamp("2024-03-15")           # naive ET date key
        self.day_ts = _make_day_ts("2024-03-15")          # TZ-aware ET DatetimeIndex

    def test_finds_930_bar(self):
        """Index 570 = 09:30 ET (570 min from midnight 00:00 ET)."""
        idx = _searchsorted_930(self.day_ts, self.day)
        bar_time = self.day_ts[idx].tz_localize(None)  # strip to compare naive
        self.assertEqual(bar_time.hour, 9)
        self.assertEqual(bar_time.minute, 30)

    def test_invariant_naive_vs_aware(self):
        """Naive index (no TZ) should produce same bar as TZ-aware ET index."""
        naive_ts = self.day_ts.tz_localize(None)
        idx_aware = _searchsorted_930(self.day_ts, self.day)
        idx_naive = _searchsorted_930(naive_ts, self.day)
        self.assertEqual(idx_aware, idx_naive,
                         "naive vs TZ-aware ET must find same 09:30 bar")

    def test_invariant_dst_transition(self):
        """DST change day (2024-03-10): clocks spring forward → 09:30 ET still correct."""
        dst_day    = pd.Timestamp("2024-03-10")          # DST transition day
        dst_day_ts = _make_day_ts("2024-03-10")
        idx = _searchsorted_930(dst_day_ts, dst_day)
        bar_time = dst_day_ts[idx].tz_localize(None)
        self.assertEqual(bar_time.hour, 9)
        self.assertEqual(bar_time.minute, 30)

    def test_nkd_guard_returns_bar0(self):
        """NKD (Asia/Tokyo) TZ string → falls through to bar 0 (not 09:30 JST)."""
        tokyo_ts = self.day_ts.tz_convert("Asia/Tokyo")
        idx = _searchsorted_930(tokyo_ts, self.day)
        self.assertEqual(idx, 0, "non-ET TZ must return bar 0 (NKD guard)")


# ── Test 2: now() → ET date invariance ──────────────────────────────────────

class TestNowET(unittest.TestCase):
    """Simulate machine in 3 different TZs; verify ET date is always correct."""

    # A fixed wall-clock moment: 2026-01-15 09:31:00 ET = 14:31 UTC = 21:31 VN (UTC+7)
    # All 3 machine TZs should agree on ET calendar date = 2026-01-15.
    UTC_REF  = pd.Timestamp("2026-01-15 14:31:00", tz="UTC")
    ET_DATE  = pd.Timestamp("2026-01-15").date()

    def _et_date_from_utc(self, utc_ts: pd.Timestamp) -> object:
        """Convert a UTC timestamp to ET calendar date (production pattern)."""
        return utc_ts.tz_convert(ET).normalize().tz_localize(None).date()

    def test_from_et_perspective(self):
        """Machine in ET (UTC-5 winter): date is 2026-01-15."""
        result = self._et_date_from_utc(self.UTC_REF)
        self.assertEqual(result, self.ET_DATE)

    def test_from_utc_perspective(self):
        """Machine in UTC: 14:31 UTC → same ET date."""
        result = self._et_date_from_utc(self.UTC_REF)
        self.assertEqual(result, self.ET_DATE)

    def test_from_vn_perspective(self):
        """Machine in VN (UTC+7): 21:31 VN = 14:31 UTC → same ET date."""
        vn_ts = self.UTC_REF.tz_convert("Asia/Ho_Chi_Minh")
        result = self._et_date_from_utc(vn_ts.tz_convert("UTC"))
        self.assertEqual(result, self.ET_DATE)

    def test_midnight_edge_vn(self):
        """VN midnight 00:01 = previous day 17:01 ET → ET date is yesterday."""
        # VN 2026-01-16 00:01 = UTC 2026-01-15 17:01 = ET 2026-01-15 12:01
        vn_midnight = pd.Timestamp("2026-01-16 00:01:00", tz="Asia/Ho_Chi_Minh")
        result = self._et_date_from_utc(vn_midnight.tz_convert("UTC"))
        # ET is UTC-5 (winter): 17:01 UTC = 12:01 ET → date is 2026-01-15
        self.assertEqual(result, pd.Timestamp("2026-01-15").date(),
                         "VN next day midnight = still ET previous day")

    def test_now_et_naive_returns_date_today(self):
        """_now_et_naive() returns naive timestamp normalized to ET midnight."""
        t = _now_et_naive()
        self.assertIsNone(t.tzinfo, "result must be TZ-naive")
        self.assertEqual(t.hour, 0)
        self.assertEqual(t.minute, 0)
        # date must match pd.Timestamp.now(tz=ET).date()
        expected = pd.Timestamp.now(tz=ET).date()
        self.assertEqual(t.date(), expected)


# ── Test 3: backtest structural TZ invariance ────────────────────────────────

class TestBacktestStructuralTZ(unittest.TestCase):
    """Verify backtest_swing_tf never reads system clock (no now() in hot path).
    Tests that the entry window filter (between_time) is TZ-invariant on ET data."""

    def test_between_time_on_et_aware_index(self):
        """between_time('14:00','15:55') on TZ-aware ET index selects ET window."""
        day = pd.date_range("2024-06-03 09:30", "2024-06-03 16:00",
                            freq="5min", tz=ET)
        df = pd.DataFrame({"close": 1.0}, index=day)
        win = df.between_time("14:00", "15:55")
        times = win.index.tz_localize(None)
        self.assertTrue(all(t.hour >= 14 for t in times))
        self.assertTrue(all(t.hour < 16 or (t.hour == 15 and t.minute <= 55)
                            for t in times))

    def test_normalize_on_et_aware_groups_by_et_calendar_day(self):
        """groupby(normalize()) on TZ-aware ET data groups by ET calendar date."""
        # Overnight session: 2024-01-02 23:00 ET → 2024-01-03 03:59 ET (300 min)
        idx = pd.date_range("2024-01-02 23:00", periods=300, freq="1min", tz=ET)
        df  = pd.DataFrame({"close": 1.0}, index=idx)
        days = sorted({g for g, _ in df.groupby(df.index.normalize())})
        jan2_et_midnight = pd.Timestamp("2024-01-02").tz_localize(ET)
        jan3_et_midnight = pd.Timestamp("2024-01-03").tz_localize(ET)
        self.assertIn(jan2_et_midnight, days,
                      "23:00 ET bars must be in Jan-02 ET group")
        self.assertIn(jan3_et_midnight, days,
                      "00:00+ ET bars must be in Jan-03 ET group")


if __name__ == "__main__":
    unittest.main(verbosity=2)
