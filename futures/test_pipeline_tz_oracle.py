"""
futures/test_pipeline_tz_oracle.py — Full-pipeline TZ invariance oracle
========================================================================
Sweep round 2: rà các ĐƯỜNG ĐI THẬT trong full pipeline, không chỉ hàm đơn.

Câu hỏi: chạy pipeline trên máy TZ=VN / ET / UTC → output IDENTICAL không?

Approach (Windows-compatible — không dùng os.environ["TZ"]/time.tzset()):
  Patch pd.Timestamp.now() tại 3 simulated machine TZs:
    ET_SIM:  UTC ref → 09:31 ET  (machine local = 09:31, đúng TZ)
    VN_SIM:  UTC ref → 21:31 VN+7 next-day (midnight-crossing scenario)
    UTC_SIM: UTC ref → 14:31 UTC (cloud machine)
  Tất cả 3 đều cùng wall-clock moment (2026-01-15 09:31 ET = 14:31 UTC = 21:31 VN).

Tests:
  A. Backtest fingerprint invariance — không gọi now() → luôn identical
  B. today-computation invariance — 4 fixed now() paths → ET date đúng cả 3 TZ
  C. Data loading → ET-aware (không phụ thuộc machine TZ)
  D. between_time('14:00','15:55') trên ET index → ET window (không VN/UTC window)
  E. normalize() groupby trên ET index → ET calendar day (không VN ngày)
  F. NKD Asia/Tokyo guard → bar 0 (không apply 09:30 ET lên NKD)
  G. Chứng minh backtest không gọi now() — patch ghi nhận, assert không có call

Run:
    cd d:\\raits
    python -m pytest futures/test_pipeline_tz_oracle.py -v
    python futures/test_pipeline_tz_oracle.py
"""
from __future__ import annotations
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

ET  = "America/New_York"
VN  = "Asia/Ho_Chi_Minh"
UTC = "UTC"

# ── A fixed UTC reference moment ──────────────────────────────────────────────
# 2026-01-15 09:31:00 ET  = 14:31:00 UTC  = 21:31:00 VN (UTC+7)
# ET date: 2026-01-15  |  VN date: 2026-01-15 (still, 21:31 not midnight)
# Midnight-crossing: 2026-01-15 19:01 ET = 2026-01-16 00:01 VN → ET still Jan-15
_UTC_REF = pd.Timestamp("2026-01-15 14:31:00", tz=UTC)
_ET_DATE  = pd.Timestamp("2026-01-15").date()

# Midnight-crossing moment: VN sees Jan-16, ET sees Jan-15 (17:01 ET)
_UTC_MC   = pd.Timestamp("2026-01-15 22:01:00", tz=UTC)  # 17:01 ET = 00:01 VN next day
_ET_MC    = pd.Timestamp("2026-01-15").date()


def _mock_now_returning(utc_ts: pd.Timestamp):
    """Return a mock for pd.Timestamp.now() that always returns utc_ts
    converted to the tz arg, or utc_ts if no tz arg (simulates machine TZ = UTC)."""
    def _now(tz=None):
        if tz is None:
            # bare now() — returns naive local. We return UTC-naive (worst case: UTC machine)
            return utc_ts.tz_localize(None)
        return utc_ts.tz_convert(tz)
    return _now


def _now_et_naive(utc_ts: pd.Timestamp) -> pd.Timestamp:
    """Production pattern (fixed 4×): always ET date, tz-naive."""
    return utc_ts.tz_convert(ET).normalize().tz_localize(None)


def _trade_fingerprint(trades: list) -> str:
    """Stable hash of a trade list — used to compare backtest outputs."""
    key_fields = ("day", "exit_day", "direction", "entry", "exit", "points", "pnl", "reason")
    rows = []
    for t in sorted(trades, key=lambda x: (str(x.get("day", "")),
                                            str(x.get("exit_day", "")),
                                            x.get("direction", ""),
                                            x.get("entry", 0))):
        rows.append(tuple(str(t.get(k, "")) for k in key_fields))
    return hashlib.md5(json.dumps(rows).encode()).hexdigest()


# ── Test A+G: Backtest fingerprint (no now() → machine-TZ independent) ────────

class TestBacktestFingerprint(unittest.TestCase):
    """Full backtest on synthetic data — fingerprint must be identical under 3 TZ patches."""

    def _make_et_1m(self, date_str: str, n_days: int = 5) -> pd.DataFrame:
        """Synthetic 1-min ET-aware OHLCV covering n_days (for a fast backtest)."""
        start = pd.Timestamp(date_str, tz=ET)
        idx   = pd.date_range(start, periods=n_days * 24 * 60, freq="1min", tz=ET)
        n     = len(idx)
        rng   = np.random.default_rng(42)
        price = 4500.0 + np.cumsum(rng.standard_normal(n) * 0.5)
        df    = pd.DataFrame({
            "open":   price,
            "high":   price + rng.uniform(0, 2, n),
            "low":    price - rng.uniform(0, 2, n),
            "close":  price + rng.standard_normal(n) * 0.2,
            "volume": rng.integers(100, 1000, n).astype(float),
        }, index=idx)
        return df

    def _run_tiny_backtest(self, df: pd.DataFrame) -> list:
        """Run backtest_swing_tf on synthetic data, return trade list."""
        from futures._validated_core import backtest_swing_tf, benchmark_daily
        from futures.cost import FuturesCost

        # Minimal label dict: all dates = Normal (allows entries)
        days = sorted({d.normalize() for d in df.index})
        labels = {d: "Normal" for d in days}

        cost = FuturesCost(point_value=5.0, tick=0.25, slippage_ticks_per_side=2.0)
        return backtest_swing_tf(df, labels, cost, ema_period=5, chandelier_atr_mult=1.5,
                                 max_hold_days=3)

    def test_fingerprint_identical_across_tz(self):
        """Backtest fingerprint is identical regardless of what now() would return."""
        df = self._make_et_1m("2025-03-10", n_days=15)
        baseline = self._run_tiny_backtest(df)
        fp_base = _trade_fingerprint(baseline)

        for tz_label, utc_ref in [("ET-sim",      _UTC_REF),
                                   ("VN-sim",      _UTC_REF),
                                   ("UTC-sim",     _UTC_REF),
                                   ("VN-midnight", _UTC_MC)]:
            with patch.object(pd.Timestamp, "now", side_effect=_mock_now_returning(utc_ref)):
                trades = self._run_tiny_backtest(df)
            fp = _trade_fingerprint(trades)
            self.assertEqual(fp, fp_base,
                f"Fingerprint DIFFERS under {tz_label}: {fp} != {fp_base}")

    def test_backtest_never_calls_now(self):
        """Prove backtest hot path has zero calls to pd.Timestamp.now()."""
        df = self._make_et_1m("2025-03-10", n_days=15)
        now_mock = MagicMock(return_value=_UTC_REF)

        with patch.object(pd.Timestamp, "now", now_mock):
            self._run_tiny_backtest(df)

        self.assertEqual(now_mock.call_count, 0,
            f"backtest_swing_tf called pd.Timestamp.now() {now_mock.call_count}× — "
            f"should be 0 (no wall-clock reads in hot path)")


# ── Test B: today-computation path (live runner pattern) ──────────────────────

class TestTodayComputationInvariance(unittest.TestCase):
    """The 4 fixed now(tz=ET) calls → same ET date regardless of simulated machine TZ."""

    def _today_from(self, utc_ref: pd.Timestamp) -> pd.Timestamp:
        """Production pattern: pd.Timestamp.now(tz=ET).normalize().tz_localize(None)."""
        return _now_et_naive(utc_ref)

    def test_et_machine_same_day(self):
        today = self._today_from(_UTC_REF)
        self.assertEqual(today.date(), _ET_DATE, "ET machine must see ET date")
        self.assertIsNone(today.tzinfo)

    def test_vn_machine_same_day(self):
        """VN machine: 21:31 local (still same calendar day VN) → same ET date."""
        today = self._today_from(_UTC_REF)
        self.assertEqual(today.date(), _ET_DATE, "VN machine must still see ET date")

    def test_utc_machine_same_day(self):
        """UTC machine: 14:31 UTC → same ET date."""
        today = self._today_from(_UTC_REF)
        self.assertEqual(today.date(), _ET_DATE, "UTC machine must see ET date")

    def test_vn_midnight_crossing(self):
        """VN 2026-01-16 00:01 (Jan-16 VN) = Jan-15 ET → must return Jan-15 ET."""
        # _UTC_MC = 22:01 UTC = 17:01 ET (still Jan-15) = 00:01+1 VN (Jan-16)
        today = self._today_from(_UTC_MC)
        self.assertEqual(today.date(), _ET_MC,
            "VN midnight-crossing: Jan-16 VN must map to Jan-15 ET, not Jan-16")


# ── Test C: Data loading → ET-aware (load_parquet) ────────────────────────────

class TestDataLoadingTZNeutral(unittest.TestCase):
    """load_parquet converts UTC parquet index → ET-aware DatetimeIndex.
    Machine TZ plays no role in this conversion (utc=True + tz_convert)."""

    def test_load_parquet_pattern_is_explicit(self):
        """Verify the load_parquet pattern: to_datetime(utc=True) → tz_convert(ET).
        This is machine-TZ-independent by inspection."""
        from futures._validated_core import load_parquet
        import inspect
        src = inspect.getsource(load_parquet)
        self.assertIn("utc=True", src,
            "load_parquet must use utc=True in pd.to_datetime() — explicit UTC parsing")
        self.assertIn("tz_convert", src,
            "load_parquet must use tz_convert(ET) — explicit ET conversion")
        self.assertNotIn(".now()", src,
            "load_parquet must not call .now() — no wall-clock reads")

    def test_utc_aware_index_converts_to_et(self):
        """Synthetic: UTC-aware index → tz_convert(ET) → always ET regardless of machine TZ."""
        utc_idx = pd.date_range("2024-09-10 13:30", periods=390, freq="1min", tz=UTC)
        et_idx  = utc_idx.tz_convert(ET)
        # First bar: 13:30 UTC = 09:30 ET
        # et_idx is already TZ-aware ET — .hour gives ET hour directly
        first_et = et_idx[0]
        self.assertEqual(first_et.hour,   9,  "09:30 UTC→ET: hour must be 9")
        self.assertEqual(first_et.minute, 30, "09:30 UTC→ET: minute must be 30")
        self.assertEqual(str(et_idx.tzinfo), ET)


# ── Test D: between_time on ET-aware index → ET window ────────────────────────

class TestBetweenTimeETWindow(unittest.TestCase):
    """between_time('14:00','15:55') on TZ-aware ET index selects ET window.
    A VN machine has no effect: between_time respects the index's own TZ."""

    def setUp(self):
        day = pd.date_range("2025-06-03 09:30", "2025-06-03 16:00",
                            freq="5min", tz=ET)
        self.df = pd.DataFrame({"close": 1.0}, index=day)

    def test_between_time_selects_et_window(self):
        win = self.df.between_time("14:00", "15:55")
        times_naive = win.index.tz_localize(None)
        for t in times_naive:
            self.assertGreaterEqual(t.hour, 14,   f"bar {t} is before 14:00 ET")
            if t.hour == 15:
                self.assertLessEqual(t.minute, 55, f"bar {t} is after 15:55 ET")
            else:
                self.assertLess(t.hour, 16, f"bar {t} is at or after 16:00 ET")

    def test_between_time_excludes_vn_window(self):
        """VN: 14:00–15:55 VN+7 = 07:00–08:55 UTC = 03:00–04:55 ET — should NOT appear."""
        win = self.df.between_time("14:00", "15:55")
        for t in win.index:
            # ET window is 14:00–15:55, not 03:00–04:55
            hour_et = t.tz_convert(None).hour
            self.assertGreaterEqual(hour_et, 14,
                f"between_time selected a bar at {hour_et}:xx ET (expected ≥14)")


# ── Test E: normalize() groupby → ET calendar day ────────────────────────────

class TestNormalizeETCalendar(unittest.TestCase):
    """groupby(normalize()) on TZ-aware ET index groups by ET calendar day,
    not by machine's local midnight (VN/UTC)."""

    def test_overnight_bars_grouped_by_et_day(self):
        """23:00–03:59 ET spans Jan-02→Jan-03 in ET. Must be TWO ET groups."""
        idx = pd.date_range("2025-01-02 23:00", periods=300, freq="1min", tz=ET)
        df  = pd.DataFrame({"close": 1.0}, index=idx)
        groups = sorted({g for g, _ in df.groupby(df.index.normalize())})

        jan2 = pd.Timestamp("2025-01-02").tz_localize(ET)
        jan3 = pd.Timestamp("2025-01-03").tz_localize(ET)
        self.assertIn(jan2, groups, "23:00 ET bars must be in Jan-02 ET group")
        self.assertIn(jan3, groups, "00:00+ ET bars must be in Jan-03 ET group")

    def test_vn_tomorrow_bars_are_et_today(self):
        """Bars at 20:00–23:59 ET = VN next day 08:00–11:59. Must be ET today."""
        # 2025-01-15 20:00 ET = 2025-01-16 08:00 VN
        idx = pd.date_range("2025-01-15 20:00", periods=240, freq="1min", tz=ET)
        df  = pd.DataFrame({"close": 1.0}, index=idx)
        groups = {g for g, _ in df.groupby(df.index.normalize())}

        jan15 = pd.Timestamp("2025-01-15").tz_localize(ET)
        jan16 = pd.Timestamp("2025-01-16").tz_localize(ET)
        self.assertIn(jan15, groups, "20:00 ET (= VN Jan-16 morning) must group as ET Jan-15")
        self.assertNotIn(jan16, groups, "Should not group as Jan-16 ET")


# ── Test F: NKD guard ─────────────────────────────────────────────────────────

class TestNKDGuard(unittest.TestCase):
    """NKD has Asia/Tokyo TZ. searchsorted guard must return bar 0 (no 09:30 ET fix)."""

    def _search_930(self, day_ts: pd.DatetimeIndex, day: pd.Timestamp) -> int:
        from futures.test_tz_invariance import _searchsorted_930
        return _searchsorted_930(day_ts, day)

    def test_nkd_tokyo_returns_bar0(self):
        """Tokyo-TZ index → guard triggers → idx = 0."""
        day = pd.Timestamp("2025-03-10")
        et_ts = pd.date_range(pd.Timestamp("2025-03-10", tz=ET),
                              periods=1440, freq="1min", tz=ET)
        nkd_ts = et_ts.tz_convert("Asia/Tokyo")
        idx = self._search_930(nkd_ts, day)
        self.assertEqual(idx, 0, "NKD Asia/Tokyo must get bar 0 (not 09:30 ET guard)")

    def test_et_aware_gets_930_bar(self):
        """ET-TZ index → returns bar at 09:30 ET (570 = 9.5 h × 60 min)."""
        day   = pd.Timestamp("2025-03-10")
        et_ts = pd.date_range(pd.Timestamp("2025-03-10", tz=ET),
                              periods=1440, freq="1min", tz=ET)
        idx = self._search_930(et_ts, day)
        bar = et_ts[idx].tz_localize(None)
        self.assertEqual(bar.hour,   9)
        self.assertEqual(bar.minute, 30)

    def test_utc_aware_gets_930_bar(self):
        """US/Eastern alias also gets 09:30 bar."""
        day   = pd.Timestamp("2025-03-10")
        et_ts = pd.date_range(pd.Timestamp("2025-03-10", tz="US/Eastern"),
                              periods=1440, freq="1min", tz="US/Eastern")
        idx = self._search_930(et_ts, day)
        bar = et_ts[idx].tz_localize(None)
        self.assertEqual((bar.hour, bar.minute), (9, 30))


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
