"""
global_index/test_nkd_tz.py — NKD frozen(JST) + live(ET) concat clock alignment

Bug (measured live 2026-08-03):
  run_live_day.py:166 tz_converts the NKD parquet to c_nkd.session_tz (Asia/Tokyo);
  _strip_tz then drops the tz, leaving the frozen half JST-naive. IBKR bars arrive
  ET-naive. _concat_nkd_live merged the two directly, so one index carried two wall
  clocks (JST = ET + 13h in summer). 1050 of 1590 live bars landed on frozen labels
  and overwrote them via keep="last", with ~900-1000 point price errors — corrupting
  exactly the recent window desired_position() decides on.

  Observed collision sample:
    label 2026-08-03 03:00  frozen 64,700.00 (03:00 JST)  live 63,785.00 (03:00 ET)

Fix: _to_session_naive() moves the live half onto the JST clock before merging.
JST is the clock the NKD backtest was validated on — between_time("14:00","15:55")
in _validated_core selects 14:00-15:55 JST for this instrument.

These tests exercise the conversion contract directly; they do not need IBKR.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SESSION_TZ = "Asia/Tokyo"


def to_session_naive(live_et_df, session_tz=SESSION_TZ):
    """Mirror of run_live_day._to_session_naive (closure over c_nkd there)."""
    idx = live_et_df.index
    try:
        aware = idx.tz_localize("America/New_York",
                                ambiguous="infer", nonexistent="shift_forward")
    except Exception:
        aware = idx.tz_localize("America/New_York",
                                ambiguous=True, nonexistent="shift_forward")
    out = live_et_df.copy()
    out.index = aware.tz_convert(session_tz).tz_localize(None)
    return out.sort_index()


def concat_nkd(frozen_jst, live_et):
    if live_et is None or live_et.empty:
        return frozen_jst
    merged = pd.concat([frozen_jst, to_session_naive(live_et)])
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def _bars(start, n, price, freq="1min"):
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({"open": price, "high": price, "low": price,
                         "close": price, "volume": 1.0}, index=idx)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_summer_offset_is_13h():
    """EDT: JST = ET + 13h. A 03:00 ET bar must land at 16:00 JST, not stay at 03:00."""
    live = _bars("2026-08-03 03:00", 3, 63785.0)
    out = to_session_naive(live)
    assert str(out.index[0]) == "2026-08-03 16:00:00"


def test_winter_offset_is_14h():
    """EST: JST = ET + 14h. The offset is not a constant — this is why the conversion
    goes through a real tz, not a hardcoded shift."""
    live = _bars("2026-01-15 03:00", 3, 40000.0)
    out = to_session_naive(live)
    assert str(out.index[0]) == "2026-01-15 17:00:00"


def test_no_collision_with_frozen_jst_bars():
    """The live 2026-08-03 shape: frozen JST bars and live ET bars sharing labels.
    After conversion the live half must not overwrite any frozen bar."""
    frozen = _bars("2026-08-03 03:00", 60, 64700.0)          # 03:00-03:59 JST
    live = _bars("2026-08-03 03:00", 60, 63785.0)            # 03:00-03:59 ET
    merged = concat_nkd(frozen, live)
    assert len(merged) == 120, "no label may be shared once both are on the JST clock"
    assert float(merged.loc[pd.Timestamp("2026-08-03 03:00"), "close"]) == 64700.0, \
        "frozen JST bar must survive — this is the bar the old code destroyed"
    assert float(merged.loc[pd.Timestamp("2026-08-03 16:00"), "close"]) == 63785.0


def test_unfixed_behaviour_would_have_overwritten():
    """Contrast: the pre-fix merge loses 60 frozen bars to a 13h-displaced overwrite.
    Proves the test above is actually detecting the bug, not a tautology."""
    frozen = _bars("2026-08-03 03:00", 60, 64700.0)
    live = _bars("2026-08-03 03:00", 60, 63785.0)
    bad = pd.concat([frozen, live])
    bad = bad[~bad.index.duplicated(keep="last")].sort_index()
    assert len(bad) == 60, "old path collapses both series onto one set of labels"
    assert float(bad.loc[pd.Timestamp("2026-08-03 03:00"), "close"]) == 63785.0, \
        "old path let the ET bar win — a price from 13h away"


def test_entry_window_selects_jst_afternoon():
    """between_time('14:00','15:55') must pick the JST afternoon session for NKD.
    Live bars from 01:00-02:55 ET are what land there (= 14:00-15:55 JST)."""
    live = _bars("2026-08-03 01:00", 116, 63000.0)           # 01:00-02:55 ET
    out = to_session_naive(live)
    win = out.between_time("14:00", "15:55")
    assert len(win) == 116, "the whole ET night window maps into the JST entry window"
    assert str(out.index[0]) == "2026-08-03 14:00:00"
    assert str(out.index[-1]) == "2026-08-03 15:55:00"


def test_us_afternoon_bars_fall_outside_the_nkd_window():
    """14:05 ET bars land at 03:05 JST next day — outside 14:00-15:55 JST, and on a
    different JST calendar date. This is why the current 14:05 slot cannot capture
    an NKD entry on its own."""
    live = _bars("2026-08-03 14:05", 10, 63000.0)
    out = to_session_naive(live)
    assert str(out.index[0]) == "2026-08-04 03:05:00"
    assert out.between_time("14:00", "15:55").empty


def test_empty_live_returns_frozen_unchanged():
    frozen = _bars("2026-08-03 03:00", 10, 64700.0)
    assert concat_nkd(frozen, pd.DataFrame()).equals(frozen)
    assert concat_nkd(frozen, None).equals(frozen)


def test_ordering_preserved_after_conversion():
    live = _bars("2026-08-03 20:00", 600, 63000.0)           # crosses ET midnight
    out = to_session_naive(live)
    assert out.index.is_monotonic_increasing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
