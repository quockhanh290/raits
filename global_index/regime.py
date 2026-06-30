"""
global_index/regime.py — SPY-HMM regime labels for a foreign session (lookahead-safe)
======================================================================================
"Như Rổ 4" uses the shared SPY-HMM regime brain. For a foreign index the session
clock differs, so the SPY regime must be mapped WITHOUT lookahead:

  A Nikkei session day D runs in JST. Its power hour (~14:00 JST = D 05:00 UTC)
  happens BEFORE the US cash close of day D (D ~21:00 UTC) — but AFTER the close
  of day D-1 (D-1 ~21:00 UTC). So at the moment the Nikkei power hour trades, the
  most recent KNOWN SPY regime is from day D-1. Using day D's SPY regime would be
  lookahead (SPY hasn't closed yet). We therefore label Nikkei session day D with
  the SPY regime as-of (D - 1 calendar day) — asof() handles US weekends/holidays.

Regime itself is produced by the VALIDATED path (benchmark_daily + label_regimes
from futures._validated_core), the same SPY-based 3-state HMM Rổ 4 uses. Pass the
same --regime-csv and the same hmm_fit_end as basket.py (2022-12-31).
"""
from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd


def load_spy_regime(regime_csv: str, train_end: str = "2018-01-01",
                    n_components: int = 3, hmm_fit_end: str = "2022-12-31") -> pd.Series:
    """SPY daily regime via the validated path. Returns a Series indexed by ET
    trading date (tz-naive, normalized), values 'Calm'/'Normal'/'Stress'."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # D:\raits root
    from futures._validated_core import benchmark_daily, label_regimes
    daily = benchmark_daily(regime_csv)
    reg = label_regimes(daily, train_end, n_components, hmm_fit_end)
    reg = pd.Series(reg)                       # label_regimes returns a dict {day: regime}
    idx = pd.DatetimeIndex(reg.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)            # only drop tz if present (keys may be naive)
    reg.index = idx.normalize()
    return reg.sort_index()


class RegimeLabels:
    """labels.get(day) for backtest_swing_tf. `day` is a session day in the index
    timezone (tz-aware). Returns the SPY regime as-of (session_date - lag_days),
    which is lookahead-safe for a session that leads the US close (Nikkei: lag=1).
    Days before the SPY history start return None (engine then skips → no entry)."""

    def __init__(self, spy_regime: pd.Series, lag_days: int = 1):
        self.reg = spy_regime
        self.lag = lag_days

    def get(self, day, default=None):
        d = pd.Timestamp(day)
        if d.tzinfo is not None:
            d = d.tz_localize(None)          # JST wall date, drop tz
        target = d.normalize() - pd.Timedelta(days=self.lag)
        try:
            v = self.reg.asof(target)
        except Exception:
            return default
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return str(v)
