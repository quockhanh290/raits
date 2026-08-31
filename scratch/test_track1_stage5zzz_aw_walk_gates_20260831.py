"""Stage 5ZZZ-AW. The observation walk reports per-bar VERDICTS, not only readings.

Three defects, one measured cause each, and every test here was watched to fail with the fix
removed before it was kept.

  1. `observe_window_only` built its signal function WITHOUT the observer, so on a day the
     regime gate refuses, the walk filled the panel's eight measurement rows and left the
     per-bar grid empty -- 12 bars evaluated, zero grid rows, measured on 2026-08-31.
  2. The `Regime` row printed "NOT REPORTED" beside a verdict sitting a few fields away in the
     same block. Copied now, never recomputed: the seven rows around it stay verdict-free for
     the reason written over "Close minus EMA".
  4. The row labelled "Daily ATR" was a fourteen-bar ATR on the FIVE-MINUTE frame -- about
     seventy minutes. Measured on MNKD 2026-08-28: the row read 55, the daily ATR the stop is
     sized from read 1,548.93, and that number appeared nowhere on the page.
  3. Nothing said whether the newest bar had CLOSED. NKD slots fire on the five-minute
     boundary, so the bar the detector last evaluated is seconds old and reads volume 0.
"""
from __future__ import annotations

import inspect

import pandas as pd
import pytest

from global_index import specs as gi_specs
from global_index import track1_normal_r4 as NR
from global_index import track1_params as tp
from global_index import track1_strategy_diagnostics as SD
from global_index._core import load_parquet as gi_load
from monitor.backend import track1_market_view as MV

DAY = pd.Timestamp("2026-08-28").normalize()
TZ = gi_specs.SPECS["MNKD"].session_tz


@pytest.fixture(scope="module")
def nkd_frame():
    """The frame the LIVE slot is handed: tz-aware, carried on the instrument's own clock.

    Not the raw store. Reading between_time("14:00", "15:55") off the tz-naive parquet lands on
    a different part of the day entirely and the window comes back empty -- which is how this
    fixture came to exist rather than as a precaution.
    """
    df = gi_load(str(MV._store_path("MNKD")))
    df.index = df.index.tz_convert(TZ)
    return df


def _params() -> NR.NormalR4Params:
    return NR.NormalR4Params(ema_period=10, fill_law=tp.LIVE_FILL_LAW)


def _run(frame, regime: str, now: str) -> SD.NormalR4Observer:
    obs = SD.NormalR4Observer()
    NR.detect_entry_for_slot(frame, {DAY: regime}, "MNKD", DAY, pd.Timestamp(now, tz=TZ),
                             _params(), short_days=set(), apply_context_filter=True,
                             observer=obs)
    return obs


# -- 1. the walk reaches the per-bar gates ------------------------------------------------
def test_the_refused_regime_day_still_reports_per_bar_verdicts(nkd_frame):
    """The whole point of the walk: a Calm day must not come back with an empty grid."""
    obs = _run(nkd_frame, "Calm", "2026-08-28 15:05")
    assert obs.bars_seen > 0, "the walk did not run at all"
    grid = obs.bar_gate_grid()
    assert grid.get("rows"), "bars were walked but no per-bar verdict was reported"
    names = [r["gate"] for r in grid["rows"]]
    assert "regime" in names, names
    row = next(r for r in grid["rows"] if r["gate"] == "regime")
    assert row["reached"] == obs.bars_seen and row["passed"] == 0
    assert set(row["cells"]) == {"F"}, row["cells"]


def test_the_funnel_narrows_and_every_step_accounts_for_the_one_above(nkd_frame):
    """Each gate is REACHED exactly as often as the gate above it PASSED.

    An arithmetic self-check the grid cannot satisfy by accident: a gate wired to the wrong
    channel, or counted per slot instead of per bar, breaks the chain immediately.
    """
    grid = _run(nkd_frame, "Normal", "2026-08-28 15:55").bar_gate_grid()
    rows = grid["rows"]
    assert len(rows) >= 4, [r["gate"] for r in rows]
    for above, below in zip(rows, rows[1:]):
        assert below["reached"] == above["passed"], (
            below["gate"] + " was asked " + str(below["reached"]) + " times but "
            + above["gate"] + " only let " + str(above["passed"]) + " through")


def test_the_walk_never_pollutes_the_slot_level_gates(nkd_frame):
    """`first_failed_gate` reads `gates` IN ORDER; a per-bar refusal there would outrank it."""
    obs = _run(nkd_frame, "Calm", "2026-08-28 15:05")
    assert obs.bar_gates, "nothing reached the per-bar channel"
    slot_names = [g.get("gate") for g in obs.gates]
    assert slot_names == ["session_bars", "regime"], slot_names
    assert (obs.first_failed_gate or {}).get("gate") == "regime"


# -- 2. the Regime row carries the verdict that already exists ----------------------------
@pytest.mark.parametrize("regime, expected", [("Normal", True), ("Calm", False)])
def test_the_regime_row_reports_the_gate_the_detector_returned(nkd_frame, regime, expected):
    obs = _run(nkd_frame, regime, "2026-08-28 15:05")
    row = next(r for r in obs.rows(ema_period=10) if r["label"] == "Regime")
    assert row["passed"] is expected
    assert row["value"] == regime
    assert row["threshold"] == ["Normal"]
    gate = next(g for g in obs.gates if g.get("gate") == "regime")
    assert row["passed"] is gate["passed"], "the row disagreed with the gate it copies"


def test_the_measurement_rows_still_carry_no_verdict(nkd_frame):
    """Deliberate, and the reason is measured: stamping one agreed with its gate 52.7%.

    This test must go red if anyone ever "fixes" the remaining NOT REPORTED cells by computing
    a verdict here -- which would be a second implementation of a rule that trades.
    """
    rows = _run(nkd_frame, "Normal", "2026-08-28 15:05").rows(ema_period=10)
    verdicts = {r["label"]: r["passed"] for r in rows}
    assert verdicts.pop("Regime") is True
    assert len(verdicts) == 8, sorted(verdicts)
    assert set(verdicts.values()) == {None}, {k: v for k, v in verdicts.items() if v is not None}


def test_the_two_atrs_are_separate_rows_and_are_not_the_same_number(nkd_frame):
    """The row that says "Daily ATR" must be the daily range, not a seventy-minute one.

    Measured on MNKD for 2026-08-28: the five-minute ATR reads about 55 and the daily ATR the
    stop is sized from reads 1,548.93 -- twenty-eight times apart, and for years only the first
    of them was on the page, under the second one's name.

    Pinned as an ORDER OF MAGNITUDE, not as two literals: the numbers move with the market and
    a test that froze them would be re-fitted the first time it went red. What cannot happen is
    the two rows carrying the same value, or the daily one being the smaller.
    """
    by = {r["label"]: r["value"] for r in _run(nkd_frame, "Normal", "2026-08-28 15:05")
          .rows(ema_period=10)}
    five = by["ATR (14 x 5-min bars)"]
    daily = by["Daily ATR"]
    assert five is not None and daily is not None, by
    assert daily > five * 5, ("the daily ATR is not meaningfully larger than the five-minute "
                              f"one: daily={daily} five-min={five}")


def test_the_daily_atr_row_is_copied_from_the_gate_not_recomputed(nkd_frame):
    """A second implementation of the number the stop is built from is the defect to avoid."""
    obs = _run(nkd_frame, "Normal", "2026-08-28 15:05")
    gate = next(g for g in obs.gates if g.get("gate") == "daily_atr")
    row = next(r for r in obs.rows(ema_period=10) if r["label"] == "Daily ATR")
    assert row["value"] == gate["value"], (row["value"], gate["value"])


# -- 3. whether the newest bar had closed -------------------------------------------------
def test_the_forming_bar_is_reported_as_not_yet_closed(nkd_frame):
    """A slot firing on the boundary evaluates a bar seconds old -- the volume-0 case."""
    obs = _run(nkd_frame, "Normal", "2026-08-28 15:05")
    assert str(obs.last_bar["bar_ts"]).startswith("2026-08-28 15:05")
    assert SD._bar_had_closed(str(obs.last_bar["bar_ts"]), obs.clock["now"]) is False


def test_a_bar_that_closed_long_ago_is_not_reported_as_forming(nkd_frame):
    """The other direction. Without this the field could be hardcoded False and pass above.

    Measured: at 15:52 the detector's last evaluated bar is 15:25, closed twenty-seven minutes
    earlier. The first version of this flag read the last bar of the WINDOW instead and called
    that "still forming".
    """
    obs = _run(nkd_frame, "Normal", "2026-08-28 15:52")
    assert str(obs.last_bar["bar_ts"]).startswith("2026-08-28 15:25")
    assert SD._bar_had_closed(str(obs.last_bar["bar_ts"]), obs.clock["now"]) is True


def test_an_unmeasured_clock_is_none_and_never_false():
    """"We did not look" must not render as "the bar is still open"."""
    assert SD._bar_had_closed(None, "2026-08-28 15:05:00") is None
    assert SD._bar_had_closed("2026-08-28 15:05:00", None) is None
    assert SD._bar_had_closed("not a timestamp", "2026-08-28 15:05:00") is None


def test_the_clock_survives_a_frame_carried_on_a_different_zone(nkd_frame):
    """The tz trap this stage already fell into once, guarded so it cannot come back silently.

    The bar stamp keeps the frame's zone while `now` is dropped to naive by the truncation.
    Comparing them raises, and the seam swallows exceptions -- so the failure showed up as an
    empty clock on every NKD slot and nowhere else.
    """
    obs = _run(nkd_frame, "Normal", "2026-08-28 15:05")
    assert obs.clock.get("now"), "the clock event never arrived"
    assert "+09:00" in str(obs.last_bar["bar_ts"])
    assert SD._bar_had_closed(str(obs.last_bar["bar_ts"]), obs.clock["now"]) is not None


# -- the seam stays inert for the backtest ------------------------------------------------
def test_the_backtest_path_is_handed_no_observer():
    """`run_instrument` must not be able to start reporting -- checked at the CALL SITE."""
    assert "observer=" not in inspect.getsource(NR.run_instrument)
