"""
global_index/test_price_scale.py — back-adjusted history vs raw live bars

Measured 2026-08-04 at one shared timestamp (2026-08-04 15:24):

    inst   parquet     IBKR live   gap
    MES    7,792.25    7,780.00    +12.25
    MNQ   30,011.50   29,922.75    +88.75
    MYM   54,316.00   54,355.00    -39.00
    M2K    3,058.90    3,049.70     +9.20

update_ibkr_daily builds the parquet from ContFuture and shifts each batch so the
series stays continuous across rollovers — the scale EMA/ATR/chandelier must see.
fetch_bars returns the raw front-month contract, the scale orders fill at. Both are
correct; the old _concat_live merged them with keep="last" so live overwrote parquet
and the recent end of the series stepped by that gap, exactly where signals form.

Consequence on 2026-08-03: the live path opened MES at 7,634.75 while a replay of
the parquet alone held no MES position at ANY cutoff — 15:10, 15:55, 23:59, and the
next day. The trade came from the discontinuity, not from the strategy.

  PS1: live bars land on the parquet's scale
  PS2: bars at or before the parquet's end are not used (no overwriting history)
  PS3: no live bars → unchanged frame, zero offset
  PS4: the offset is the update_ibkr_daily anchor, not a whole-series average
  PS5: to_candidate converts entry/stop back to raw
  PS6: without the conversion a LONG stop lands above the market — the failure this
       guards against
  PS7: offset defaults to zero, so every existing caller is untouched
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.signal_layer import to_candidate

MES_GAP = 12.25          # parquet - raw, measured 2026-08-04


def _splice(frozen, live):
    """Mirror of run_live_day._splice_live (a closure over main())."""
    if live is None or live.empty:
        return frozen, 0.0
    after = live[live.index > frozen.index[-1]]
    if after.empty:
        return frozen, 0.0
    offset = float(frozen["close"].iloc[-1]) - float(after["open"].iloc[0])
    adj = after
    if abs(offset) > 1e-9:
        adj = after.copy()
        for c in ("open", "high", "low", "close"):
            if c in adj.columns:
                adj[c] = adj[c] + offset
    return pd.concat([frozen, adj]).sort_index(), offset


def _bars(start, n, px, freq="1min"):
    idx = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({"open": px, "high": px + 1.0, "low": px - 1.0,
                         "close": px, "volume": 1.0}, index=idx)


# ── splicing ──────────────────────────────────────────────────────────────────

def test_ps1_live_bars_land_on_the_parquet_scale():
    frozen = _bars("2026-08-04 13:00", 46, 7_792.25)          # adjusted
    live = _bars("2026-08-04 13:46", 10, 7_780.00)            # raw, 12.25 lower
    out, off = _splice(frozen, live)
    assert off == pytest.approx(MES_GAP)
    assert float(out["close"].iloc[-1]) == pytest.approx(7_792.25), \
        "spliced tail must continue the parquet's scale, not step down to raw"
    steps = out["close"].diff().abs().max()
    assert steps < 1.0, f"no discontinuity may survive, largest step {steps}"


def test_ps2_overlapping_bars_never_overwrite_history():
    """keep='last' let raw bars replace real adjusted history. They must be dropped."""
    frozen = _bars("2026-08-04 13:00", 46, 7_792.25)
    live = _bars("2026-08-04 13:30", 30, 7_780.00)            # 16 bars overlap
    out, _ = _splice(frozen, live)
    overlap = pd.Timestamp("2026-08-04 13:40")
    assert float(out.loc[overlap, "close"]) == pytest.approx(7_792.25), \
        "parquet bar survived"
    assert len(out) == 46 + 14, "only bars past the parquet's end are appended"


def test_ps3_no_live_bars_is_a_no_op():
    frozen = _bars("2026-08-04 13:00", 10, 7_792.25)
    out, off = _splice(frozen, pd.DataFrame())
    assert off == 0.0 and out.equals(frozen)
    out2, off2 = _splice(frozen, _bars("2026-08-04 12:00", 5, 7_780.0))
    assert off2 == 0.0 and out2.equals(frozen), "all bars older than parquet → no-op"


def test_ps4_offset_anchors_on_the_splice_bar():
    """Same anchor as update_ibkr_daily: last parquet close vs FIRST NEW bar's open.
    Averaging the overlap instead would bake real market movement into the offset."""
    frozen = _bars("2026-08-04 13:00", 46, 7_792.25)
    live = _bars("2026-08-04 13:46", 10, 7_780.00)
    live.loc[live.index[3]:, ["open", "high", "low", "close"]] += 50.0   # later move
    _, off = _splice(frozen, live)
    assert off == pytest.approx(MES_GAP), "later movement must not enter the offset"


# ── conversion back to raw ────────────────────────────────────────────────────

def test_ps5_candidate_prices_return_to_raw():
    c = to_candidate("MES", "LONG", 7_647.00, 7_639.50, "roska4_swing", 1, 5.0,
                     daily_atr=40.0, mult=2.5, price_offset=MES_GAP)
    assert c["entry"] == pytest.approx(7_634.75)
    assert c["stop"] == pytest.approx(7_627.25)


def test_ps6_unconverted_stop_would_sit_above_the_market():
    """The reason the conversion is mandatory, not cosmetic."""
    market = 7_635.00
    adjusted_stop = 7_639.50                       # what the engine produces
    assert adjusted_stop > market, "unconverted: LONG stop above market → instant fill"
    raw = to_candidate("MES", "LONG", 7_647.00, adjusted_stop, "roska4_swing", 1, 5.0,
                       daily_atr=40.0, mult=2.5, price_offset=MES_GAP)["stop"]
    assert raw < market, "converted: stop sits below the market, as a LONG stop must"


def test_ps7_default_offset_leaves_callers_untouched():
    a = to_candidate("MES", "LONG", 5000.0, 4980.0, "roska4_swing", 1, 5.0,
                     daily_atr=40.0, mult=2.5)
    b = to_candidate("MES", "LONG", 5000.0, 4980.0, "roska4_swing", 1, 5.0,
                     daily_atr=40.0, mult=2.5, price_offset=0.0)
    assert a == b and a["entry"] == 5000.0 and a["stop"] == 4980.0


def test_ps8_short_side_converts_the_same_way():
    c = to_candidate("M2K", "SHORT", 3_058.90, 3_068.10, "roska4_swing", 1, 5.0,
                     daily_atr=20.0, mult=2.5, price_offset=9.20)
    assert c["entry"] == pytest.approx(3_049.70)
    assert c["stop"] == pytest.approx(3_058.90)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
