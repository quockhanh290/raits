"""scratch/test_track1_stage4c_live_source_20260823.py — the Stage 4C gate.

    python -m pytest scratch/test_track1_stage4c_live_source_20260823.py -q

Offline. No scheduler, no IBKR connection, no order, no dashboard write, no network.

Stage 4B left one blocker held by a measurement: the route had no live bar path at all, so the
splice guard guarded nothing. This suite is about the path that was built to close it, and
about the two failures that only appear once bars actually move:

  * the frozen half and the live half are on DIFFERENT CLOCKS by contract — parquet is UTC read
    as New York (Tokyo for the Nikkei sleeve), the broker path returns naive ET — so a
    conversion has to happen, and the conversion is where the 1,050-bar Nikkei corruption came
    from.
  * the guard alone is not enough. It refuses a live bar that lands ON history. It cannot see a
    live bar that lands PAST history, which is what the same clock error produces in the other
    direction. That gap was found by running it, not by reading it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes  # noqa: E402
from futures.swing_tf import costs_for_basket  # noqa: E402
from global_index import run_live_day_track1 as entry  # noqa: E402
from global_index import track1_calm_a as CA  # noqa: E402
from global_index import track1_gates as g  # noqa: E402
from global_index import track1_intraday as intra  # noqa: E402
from global_index import track1_live_frame as LF  # noqa: E402
from global_index import track1_live_source as S  # noqa: E402
from global_index import track1_normal_r4 as NR  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_sleeves as SL  # noqa: E402

_C: dict = {}


def frozen(inst: str):
    if inst not in _C:
        _C[inst] = S.frozen_frame(inst, entry.default_data_paths()[inst])
    return _C[inst]


def window(inst: str, lo: str, hi: str):
    df = frozen(inst)
    idx = df.index
    return df[(idx >= pd.Timestamp(lo).tz_localize(idx.tz))
              & (idx <= pd.Timestamp(hi).tz_localize(idx.tz))]


def labels():
    if "lab" not in _C:
        lab = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3, "2024-12-31")
        _C["lab"] = {pd.Timestamp(k).normalize(): v for k, v in lab.items()}
    return _C["lab"]


def as_provider_bars(df):
    """The same bars as a provider would hand them over: naive ET."""
    out = df.copy()
    out.index = pd.DatetimeIndex(df.index).tz_convert(S.PROVIDER_CLOCK).tz_localize(None)
    return out


def split(df, frac: float = 0.75):
    """(history, live-as-a-provider-would-send-it, fetch instant)."""
    cut = df.index[int(len(df) * frac)]
    hist, tail = df[df.index <= cut], df[df.index > cut]
    return hist, as_provider_bars(tail), pd.DatetimeIndex(tail.index).max()


def join(inst, hist, live, through, **kw):
    return S.live_frame(inst, frozen=hist,
                        provider=S.FrameBarProvider({inst: live}, **kw), through=through)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the conversion between the two clocks
# ══════════════════════════════════════════════════════════════════════════════
def test_the_two_halves_really_are_on_different_clocks():
    """If this ever stops being true the conversion becomes dead code, and dead code that
    used to matter is how a route ends up with a step nobody remembers is load-bearing."""
    assert str(pd.DatetimeIndex(frozen("MES").index).tz) == "America/New_York"
    assert str(pd.DatetimeIndex(frozen("MNKD").index).tz) == "Asia/Tokyo"
    assert S.session_tz("MNKD") == "Asia/Tokyo"
    assert S.session_tz("MES") == S.PROVIDER_CLOCK


def test_the_target_clock_is_read_from_the_frame_not_from_a_table(monkeypatch):
    """A constant in the module could disagree with the file on disk. The frame cannot
    disagree with itself, so the conversion asks the frame."""
    hist = window("MNKD", "2026-03-02", "2026-03-06")
    live = as_provider_bars(window("MNKD", "2026-03-06", "2026-03-10"))

    # Break the spec table. The conversion must be unaffected, because it does not read it.
    monkeypatch.setitem(S.gi_specs.SPECS, "MNKD",
                        type(S.gi_specs.SPECS["MNKD"])(
                            **{**S.gi_specs.SPECS["MNKD"].__dict__,
                               "session_tz": "America/Chicago"}))
    out = S.on_frozen_clock("MNKD", live, hist)
    assert str(pd.DatetimeIndex(out.index).tz) == "Asia/Tokyo"


@pytest.mark.parametrize("lo,hi,hours", [
    ("2026-07-06", "2026-07-10", 13),   # US on summer time: Tokyo is 13 hours ahead
    ("2026-03-02", "2026-03-06", 14),   # before the US clocks move: 14
])
def test_the_wrong_conversion_and_the_right_one_are_not_the_same_thing(lo, hi, hours):
    """The two spellings are one keystroke apart, and the gap between them is not a constant.

    The incident is always described as "thirteen hours", and in July it is. In March, before
    the US clocks move and while Japan does not move at all, the same mistake is worth
    FOURTEEN. Anything that hard-coded thirteen — a test, a guard, a reconciliation tolerance —
    would be correct for about eight months of the year and quietly wrong for the other four.
    So the size of the error is measured from the zones, and both sides of the boundary are
    pinned here.
    """
    hist = window("MNKD", "2026-01-02", lo)
    live = as_provider_bars(window("MNKD", lo, hi))
    assert len(live) > 100, len(live)

    right = S.on_frozen_clock("MNKD", live, hist)
    wrong = live.copy()
    wrong.index = pd.DatetimeIndex(live.index).tz_localize("Asia/Tokyo")   # the bug

    delta = pd.DatetimeIndex(right.index)[0] - pd.DatetimeIndex(wrong.index)[0]
    assert delta == pd.Timedelta(hours=hours), delta
    assert not pd.DatetimeIndex(right.index).equals(pd.DatetimeIndex(wrong.index))


def test_a_provider_that_lies_about_its_clock_is_refused():
    hist = window("MES", "2026-03-02", "2026-03-06")
    live = window("MES", "2026-03-06", "2026-03-10")          # still tz-aware — the lie
    with pytest.raises(S.LiveSourceRefused) as e:
        S.FrameBarProvider({"MES": live}).fetch_session_bars("MES", through=None)
    assert e.value.code == "provider_clock"

    with pytest.raises(S.LiveSourceRefused) as e2:
        S.on_frozen_clock("MES", live, hist)
    assert e2.value.code == "provider_clock"


def test_a_frozen_half_with_no_clock_is_refused():
    """`frozen_frame` always returns an aware index. A naive one means somebody loaded the
    parquet with something else, and that something else is the other loader in this repo."""
    hist = window("MES", "2026-03-02", "2026-03-06").copy()
    hist.index = pd.DatetimeIndex(hist.index).tz_localize(None)
    live = as_provider_bars(window("MES", "2026-03-06", "2026-03-10"))
    with pytest.raises(S.LiveSourceRefused) as e:
        S.on_frozen_clock("MES", live, hist)
    assert e.value.code == "frozen_clock"


def test_the_fetch_instant_is_required():
    hist, live, _through = split(window("MES", "2026-03-02", "2026-03-10"))
    with pytest.raises(S.LiveSourceRefused) as e:
        join("MES", hist, live, None)
    assert e.value.code == "no_fetch_instant"


# ══════════════════════════════════════════════════════════════════════════════
# 2. the join, on real frames, through the adapter
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("inst,lo,hi", [
    ("MES", "2026-01-02", "2026-04-30"),
    ("MNKD", "2026-01-02", "2026-04-30"),
])
def test_history_plus_today_reconstructs_the_original_frame(inst, lo, hi):
    df = window(inst, lo, hi)
    hist, live, through = split(df)
    jf = join(inst, hist, live, through)
    assert jf.report.code == LF.OK
    assert jf.appended > 0 and jf.provider_rows == jf.appended
    assert jf.frame.equals(df), f"{inst}: the join did not give the original frame back"


@pytest.mark.parametrize("inst", ["MES", "MNKD"])
def test_the_live_tail_cannot_overwrite_a_single_historical_bar(inst):
    """The direction the guard exists for: a live bar carrying a label history owns loses."""
    df = window(inst, "2026-02-02", "2026-03-06")
    hist, live, through = split(df)

    # Offer the whole frame back, not just the tail, with the overlapping part damaged.
    whole = as_provider_bars(df).copy()
    n = len(whole) - len(live)
    whole.iloc[:n, whole.columns.get_loc("close")] = -1.0
    with pytest.raises(S.LiveSourceRefused) as e:
        join(inst, hist, whole, through)
    assert e.value.code == "overlap_disagreement"

    # And with the overlap intact, it is trimmed rather than applied: history is untouched.
    jf = join(inst, hist, as_provider_bars(df), through)
    assert jf.frame.iloc[:len(hist)].equals(hist)
    assert jf.overlap_checked > 0, "no overlap was compared, so nothing was proven"


def test_the_nikkei_thirteen_hour_error_is_caught_by_price_not_by_luck():
    """The incident itself, reproduced and refused.

    A clock error puts one moment's PRICES under another moment's LABELS. When those labels
    land back inside history the guard trims them away silently — safe, but it tells nobody.
    The adapter compares the overlap instead, and the disagreement it finds is the same
    magnitude the real corruption had: roughly a thousand Nikkei points.
    """
    df = window("MNKD", "2026-06-01", "2026-08-20")
    cut = df.index[int(len(df) * 0.75)]
    hist, tail = df[df.index <= cut], df[df.index > cut]
    through = pd.DatetimeIndex(tail.index).max()

    shifted = tail.copy()
    true_et = pd.DatetimeIndex(tail.index).tz_convert(S.PROVIDER_CLOCK)
    shifted.index = (true_et - pd.Timedelta(hours=13)).tz_localize(None)

    with pytest.raises(S.LiveSourceRefused) as e:
        join("MNKD", hist, shifted, through)
    assert e.value.code == "overlap_disagreement"
    assert "Nikkei" in e.value.detail
    biggest = float(re.search(r"largest gap ([0-9]+\.[0-9]+)", e.value.detail).group(1))
    assert biggest > 100, biggest

    # Nearly every shared bar must disagree, not one of them. A check that fired on a single
    # outlier would also fire on a late correction to one print, and could not tell a clock
    # error from a data fix. Measured here: 707 of 708.
    bad, shared = (int(x) for x in re.search(r"disagree on (\d+) of (\d+)",
                                             e.value.detail).groups())
    assert shared > 100 and bad / shared > 0.9, (bad, shared)


class UntrimmedProvider:
    """A source that returns exactly what it was given, with no causal trim of its own.

    Not every source trims. `IBKRBroker.fetch_bars` does — it drops anything past `through`,
    which is why a forward clock error reaching THROUGH that provider turns into "offered many,
    appended none" rather than a refusal. The direct `reqHistoricalData` path does not trim,
    and neither would a file drop or a message queue. This models those, so the adapter's own
    check is exercised rather than assumed to be reachable.
    """

    name = "untrimmed"

    def __init__(self, frames):
        self.frames = frames

    def fetch_session_bars(self, inst, *, through):
        return self.frames.get(inst)


def test_bars_stamped_after_the_fetch_instant_are_refused():
    """The direction the guard structurally cannot see.

    A tail converted the wrong way does not always land on history. Shift it forward and every
    bar lands in empty space past the end: strictly newer, unique, ordered, same columns —
    every rule the join has, satisfied. Measuring found this; reading the guard did not.
    """
    df = window("MES", "2026-02-02", "2026-03-06")
    hist, live, through = split(df)
    ahead = live.copy()
    ahead.index = pd.DatetimeIndex(live.index) + pd.Timedelta(hours=13)

    # First: the join alone WOULD have taken it. This is the assertion that makes the rest of
    # the test mean something — without it, the refusal below could be redundant.
    aligned = S.on_frozen_clock("MES", ahead, hist)
    _frame, rep = LF.splice(hist, aligned)
    assert rep.code == LF.OK and rep.live_rows_appended == len(ahead)

    with pytest.raises(S.LiveSourceRefused) as e:
        S.live_frame("MES", frozen=hist, provider=UntrimmedProvider({"MES": ahead}),
                     through=through)
    assert e.value.code == "bars_from_the_future"


def session_split(inst, lo, hi, hours=6):
    """A realistic live half: history, then the last few HOURS as today's session.

    The earlier helper cut a frame at 75%, which makes a "live" half several days long. That is
    fine for reconstruction, and wrong for anything about clock errors — a shift is only pushed
    past the fetch instant if it is larger than the live half's own span, so a multi-day live
    half hides exactly the error a one-session live half exposes. A live fetch is one session.
    """
    df = window(inst, lo, hi)
    end = df.index[-1]
    cut = end - pd.Timedelta(hours=hours)
    hist, tail = df[df.index <= cut], df[df.index > cut]
    return hist, as_provider_bars(tail), pd.DatetimeIndex(tail.index).max()


def test_a_trimming_provider_turns_the_same_error_into_a_visible_zero():
    """The same forward error through a provider that trims, so the two behaviours are pinned
    side by side rather than one of them being a surprise later."""
    hist, live, through = session_split("MES", "2026-02-02", "2026-03-06")
    assert 100 < len(live) < 1000, len(live)
    ahead = live.copy()
    ahead.index = pd.DatetimeIndex(live.index) + pd.Timedelta(hours=13)

    jf = join("MES", hist, ahead, through)
    assert jf.appended == 0 and jf.provider_rows == 0
    assert jf.frame.equals(hist), "history changed on a fetch that landed nowhere"


def test_the_limit_of_these_checks_is_stated_rather_than_hidden():
    """A forward shift SMALLER than the live half's own span is caught by neither check.

    Said plainly because it is true. `bars_from_the_future` only sees bars past the fetch
    instant, and a shift smaller than the span leaves most of them before it. The overlap check
    only sees bars that land on history, and a forward shift lands past it. So a multi-day live
    half shifted forward by less than its own length joins cleanly and wrongly.

    What makes that acceptable rather than a hole is the size of a real live half: a session
    fetch is hours, so any shift big enough to matter — a whole-zone error is 13 or 14 — is
    larger than the span and is caught, as the test above shows. This test exists so that if a
    caller ever starts handing over multi-day live halves, the thing that stops being true is
    written down here rather than discovered afterwards.
    """
    df = window("MES", "2026-02-02", "2026-03-06")
    hist, live, through = split(df)                       # a live half several days long
    span = pd.DatetimeIndex(live.index).max() - pd.DatetimeIndex(live.index).min()
    assert span > pd.Timedelta(hours=13), span

    ahead = live.copy()
    ahead.index = pd.DatetimeIndex(live.index) + pd.Timedelta(hours=13)
    jf = join("MES", hist, ahead, through)
    assert jf.appended > 0, "if this is now zero, the checks got stronger — update the note"
    assert not jf.frame.equals(df), "the frame is wrong, and nothing refused it"


def test_offering_bars_that_all_vanish_does_not_look_like_a_quiet_session():
    """"offered 0, appended 0" and "offered 400, appended 0" must not print the same. One is a
    market that has not traded yet; the other is a feed that is not landing anywhere."""
    df = window("MES", "2026-02-02", "2026-03-06")
    hist, live, through = split(df)

    quiet = join("MES", hist, live.iloc[:0], through)
    assert quiet.provider_rows == 0 and quiet.offered_but_unused == 0

    stale = as_provider_bars(hist.tail(300))
    landing_nowhere = join("MES", hist, stale, through)
    assert landing_nowhere.provider_rows == 300
    assert landing_nowhere.appended == 0
    assert landing_nowhere.offered_but_unused == 300


# ══════════════════════════════════════════════════════════════════════════════
# 3. the sleeves decide the same on the joined frame
# ══════════════════════════════════════════════════════════════════════════════
def test_normal_r4_decides_the_same_on_a_frame_that_arrived_through_the_adapter():
    df = window("MES", "2026-01-02", "2026-04-30")
    hist, live, through = split(df)
    cost = costs_for_basket(slippage_ticks=2.0)["MES"]
    p = NR.NormalR4Params()
    short = NR.short_days_from_csv("spy_daily_live.csv")

    base, _ = NR.run_instrument(df, labels(), cost, p, short_days=short)
    assert base, "the historical run produced no trades — nothing would be compared"
    jf = join("MES", hist, live, through)
    got, _ = NR.run_instrument(jf.frame, labels(), cost, p, short_days=short)

    keys = ("day", "exit_day", "direction", "entry", "exit", "pnl")
    a = [tuple(str(t[k]) for k in keys) for t in base]
    b = [tuple(str(t[k]) for k in keys) for t in got]
    assert a == b, ("first divergence",
                    next((i for i in range(max(len(a), len(b)))
                          if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)),
                         None))


def test_the_nikkei_sleeve_decides_the_same_on_a_frame_that_arrived_through_the_adapter():
    """The instrument whose frame changes clock on the way in."""
    from global_index._core import FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels

    df = window("MNKD", "2026-01-02", "2026-06-30")
    hist, live, through = split(df)
    c = gi_specs.SPECS["MNKD"]
    cost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                slippage_ticks_per_side=2.0)
    lab = RegimeLabels(pd.Series(labels()).sort_index(), lag_days=1)
    p = NR.NormalR4Params(ema_period=10)
    short = NR.short_days_from_csv("spy_daily_live.csv")

    base, _ = NR.run_instrument(df, lab, cost, p, short_days=short,
                                apply_context_filter=False)
    assert base, "no Nikkei trades in the slice — nothing would be compared"
    jf = join("MNKD", hist, live, through)
    got, _ = NR.run_instrument(jf.frame, lab, cost, p, short_days=short,
                               apply_context_filter=False)
    keys = ("day", "exit_day", "direction", "entry", "exit", "pnl")
    assert ([tuple(str(t[k]) for k in keys) for t in base]
            == [tuple(str(t[k]) for k in keys) for t in got])


def test_calm_a_decides_the_same_on_a_frame_that_arrived_through_the_adapter():
    df = window("MES", "2026-01-02", "2026-05-29")
    hist, live, through = split(df)
    base = CA.detect(df, labels(), "MES")
    assert base, "no Calm A setups in the slice — nothing would be compared"
    jf = join("MES", hist, live, through)
    assert CA.detect(jf.frame, labels(), "MES") == base


# ══════════════════════════════════════════════════════════════════════════════
# 4. the same-session gates, on frames the adapter produced
# ══════════════════════════════════════════════════════════════════════════════
def session_frame(inst: str, day: str, upto: str):
    """Yesterday's history plus today's session up to `upto`, joined through the adapter.

    This is the shape a live slot actually holds: complete history behind, a partial session in
    front. Every earlier equivalence test cuts a finished frame; this one stops mid-session,
    which is the case no reproduction before Stage 4C had ever produced.
    """
    df = frozen(inst)
    tz = pd.DatetimeIndex(df.index).tz
    d = pd.Timestamp(day).tz_localize(tz)
    hist = df[df.index < d]
    through = pd.Timestamp(f"{day} {upto}").tz_localize(tz)
    today = df[(df.index >= d) & (df.index <= through)]
    return join(inst, hist, as_provider_bars(today), through), through


def five_min(df):
    o = df["open"].resample("5min").first()
    h = df["high"].resample("5min").max()
    lo = df["low"].resample("5min").min()
    c = df["close"].resample("5min").last()
    v = df["volume"].resample("5min").sum()
    out = pd.concat([o, h, lo, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna(subset=["open"])


def test_calm_a_gate_passes_on_a_partial_session_that_reaches_its_decision_bar():
    """Calm A needs the prior session's RTH complete and today's 09:30-10:00 contiguous."""
    jf, through = session_frame("MES", "2026-03-18", "10:00")
    bars = five_min(jf.frame)
    # Stage 5ZU: the fill reference is read from the ONE-MINUTE frame — `jf.frame` — while
    # `bars` is the resampled decision frame. Two bar sizes, two questions, and the gate
    # reports UNVERIFIED rather than a pass when nobody says where the price comes from.
    v = intra.validate("roska4_calm", bars, now_et=through.tz_convert(S.PROVIDER_CLOCK),
                       session_day=pd.Timestamp("2026-03-18"),
                       prior_session_day=pd.Timestamp("2026-03-17"),
                       entry_quote_index=jf.frame.index)
    assert v.allow, v.as_dict()


def test_the_prior_sessions_closing_bar_survives_the_join():
    """The 15:59 bar decides Calm A's close-location, one bar either side of a threshold. If
    the join lost or altered it, the gate would pass and the setup would be wrong."""
    jf, _ = session_frame("MES", "2026-03-18", "10:00")
    tz = pd.DatetimeIndex(jf.frame.index).tz
    stamp = pd.Timestamp("2026-03-17 15:59").tz_localize(tz)
    assert stamp in jf.frame.index, "the prior session's closing minute is missing"
    assert jf.frame.loc[stamp].equals(frozen("MES").loc[stamp])


def test_calm_a_gate_refuses_a_session_that_has_not_reached_its_decision_bar():
    jf, through = session_frame("MES", "2026-03-18", "09:50")
    bars = five_min(jf.frame)
    # Stage 5ZU: the fill reference is read from the ONE-MINUTE frame — `jf.frame` — while
    # `bars` is the resampled decision frame. Two bar sizes, two questions, and the gate
    # reports UNVERIFIED rather than a pass when nobody says where the price comes from.
    v = intra.validate("roska4_calm", bars, now_et=through.tz_convert(S.PROVIDER_CLOCK),
                       session_day=pd.Timestamp("2026-03-18"),
                       prior_session_day=pd.Timestamp("2026-03-17"),
                       entry_quote_index=jf.frame.index)
    assert not v.allow, "a session short of 10:00 was allowed to decide"


def test_calm_a_gate_refuses_when_a_bar_is_missing_from_the_middle():
    jf, through = session_frame("MES", "2026-03-18", "10:00")
    bars = five_min(jf.frame)
    tz = pd.DatetimeIndex(bars.index).tz
    hole = pd.Timestamp("2026-03-18 09:45").tz_localize(tz)
    assert hole in bars.index, "the bar this test removes was not there to remove"
    v = intra.validate("roska4_calm", bars.drop(index=[hole]),
                       now_et=through.tz_convert(S.PROVIDER_CLOCK),
                       session_day=pd.Timestamp("2026-03-18"),
                       prior_session_day=pd.Timestamp("2026-03-17"))
    assert not v.allow, "a session with a hole in it was allowed to decide"


def test_stress_gate_passes_on_a_partial_session_covering_0930_to_1030():
    jf, through = session_frame("MNQ", "2026-03-18", "10:40")
    bars = five_min(jf.frame)
    v = intra.validate("roska4_stress", bars, now_et=through.tz_convert(S.PROVIDER_CLOCK),
                       session_day=pd.Timestamp("2026-03-18"),
                       ledger_status={"outcome": "complete", "observed_slots": 24, "expected_slots": 24})
    assert v.allow, v.as_dict()


def test_stress_gate_refuses_a_hole_in_its_required_span():
    jf, through = session_frame("MNQ", "2026-03-18", "10:40")
    bars = five_min(jf.frame)
    tz = pd.DatetimeIndex(bars.index).tz
    hole = pd.Timestamp("2026-03-18 10:05").tz_localize(tz)
    assert hole in bars.index
    v = intra.validate("roska4_stress", bars.drop(index=[hole]),
                       now_et=through.tz_convert(S.PROVIDER_CLOCK),
                       session_day=pd.Timestamp("2026-03-18"),
                       ledger_status={"outcome": "complete", "observed_slots": 24, "expected_slots": 24})
    assert not v.allow


def test_stress_gate_refuses_an_incomplete_window_observation():
    jf, through = session_frame("MNQ", "2026-03-18", "10:40")
    bars = five_min(jf.frame)
    v = intra.validate("roska4_stress", bars, now_et=through.tz_convert(S.PROVIDER_CLOCK),
                       session_day=pd.Timestamp("2026-03-18"),
                       ledger_status={"outcome": "unobserved", "observed_slots": 0, "expected_slots": 24})
    assert not v.allow, "the window ledger said the window was not watched and it decided anyway"


# ══════════════════════════════════════════════════════════════════════════════
# 5. every way the join can be wrong, reaching it through the adapter
# ══════════════════════════════════════════════════════════════════════════════
def _base_case():
    return session_split("MES", "2026-02-02", "2026-03-06")


def test_duplicate_timestamps_are_refused():
    hist, live, through = _base_case()
    dup = pd.concat([live, live.iloc[[5]]]).sort_index()
    with pytest.raises(LF.SpliceRefused) as e:
        join("MES", hist, dup, through)
    assert e.value.code == LF.DUPLICATE_TIMESTAMPS


def test_out_of_order_bars_are_refused():
    hist, live, through = _base_case()
    shuffled = live.copy()
    idx = list(shuffled.index)
    idx[3], idx[9] = idx[9], idx[3]
    shuffled.index = pd.DatetimeIndex(idx)
    with pytest.raises(LF.SpliceRefused) as e:
        join("MES", hist, shuffled, through)
    assert e.value.code == LF.OUT_OF_ORDER


def test_mismatched_columns_are_refused():
    """Still refused, and since Stage 5Q-3 refused EARLIER and by a more specific name.

    `live_frame` now projects the live half onto the frozen frame's columns before the join,
    so a live half MISSING a frozen column is caught by the projection with
    `missing_required_columns` rather than reaching the guard and arriving as
    `column_mismatch`. The contract this test defends — a live half whose columns do not
    satisfy the frozen schema must never be joined — is unchanged; what changed is which
    layer says so, and the new message names the column.

    The guard's own `column_mismatch` is still live and still reachable: it is what stops a
    caller that skipped the projection, pinned by
    `test_the_guard_still_refuses_a_caller_that_skipped_the_projection` in the 5Q-3 suite.
    """
    hist, live, through = _base_case()
    with pytest.raises(S.LiveSourceRefused) as e:
        join("MES", hist, live.drop(columns=["volume"]), through)
    assert e.value.code == S.MISSING_REQUIRED_COLUMNS
    assert "volume" in e.value.detail


def test_extra_provider_columns_no_longer_refuse():
    """The other half of the same change, and the reason it was made: the IBKR feed carries
    `average` and `barcount`, and on 2026-08-24 that killed the first live Calm slot."""
    hist, live, through = _base_case()
    wide = live.copy()
    wide["average"] = 1.0
    wide["barcount"] = 2
    jf = join("MES", hist, wide, through)
    assert list(jf.frame.columns) == list(hist.columns)
    assert jf.dropped_columns == ("average", "barcount")


def test_a_wrong_timezone_is_refused_before_the_join_and_never_converted():
    """Two refusals, one before the other, and both matter. The adapter refuses a provider
    that hands over an aware index at all; the join refuses two frames on different zones. The
    second is the backstop for a path that ever bypasses the first."""
    hist, live, through = _base_case()
    aware = live.copy()
    aware.index = pd.DatetimeIndex(live.index).tz_localize("Asia/Tokyo")
    with pytest.raises(S.LiveSourceRefused) as e:
        join("MES", hist, aware, through)
    assert e.value.code == "provider_clock"

    with pytest.raises(LF.SpliceRefused) as e2:
        LF.splice(hist, aware)
    assert e2.value.code == LF.TZ_MISMATCH


def test_every_route_to_a_frame_passes_through_the_guard(monkeypatch):
    """Not "it imports the guard" — that the call actually happens on every branch.

    Counted by replacing the join with one that increments, so a future refactor that returns
    a frame early cannot leave the count where it was.
    """
    calls = {"n": 0}
    real = LF.splice

    def counting(frozen_half, live_half):
        calls["n"] += 1
        return real(frozen_half, live_half)

    monkeypatch.setattr(S.guard, "splice", counting)
    hist, live, through = _base_case()

    join("MES", hist, live, through)
    assert calls["n"] == 1

    join("MES", hist, live.iloc[:0], through)          # nothing to add
    assert calls["n"] == 2, "the empty-live branch returned without asking the guard"

    S.live_frame("MES", frozen=hist, provider=S.FrameBarProvider({}), through=through)
    assert calls["n"] == 3, "the no-such-instrument branch skipped the guard"


# ══════════════════════════════════════════════════════════════════════════════
# 6. the sleeves are served from the adapter
# ══════════════════════════════════════════════════════════════════════════════
def test_every_sleeve_receives_a_joined_frame_and_the_shared_instrument_is_joined_once():
    # ONE fetch instant for the whole basket, which is what a slot actually has. Splitting each
    # instrument at its own last bar and then taking the earliest of those starves whichever
    # instrument trades latest — the first version of this test did that and handed MES an
    # empty live half while reporting a clean join.
    insts = sorted({i for v in tp.SLEEVE_INSTRUMENTS.values() for i in v})
    through = pd.Timestamp("2026-03-05 14:00", tz=S.PROVIDER_CLOCK)
    opened = through - pd.Timedelta(hours=6)
    hists, lives = {}, {}
    for inst in insts:
        df = window(inst, "2026-02-02", "2026-03-06")
        idx = pd.DatetimeIndex(df.index)
        hists[inst] = df[idx < opened.tz_convert(idx.tz)]
        lives[inst] = as_provider_bars(df[(idx >= opened.tz_convert(idx.tz))
                                          & (idx <= through.tz_convert(idx.tz))])
        assert len(lives[inst]) > 0, inst

    src = SL.LiveSleeveSource(S.FrameBarProvider(lives), frozen_frames=hists)
    by_sleeve = src.frames(through=through)

    assert set(by_sleeve) == set(tp.SLEEVE_INSTRUMENTS)
    for sleeve, insts_want in tp.SLEEVE_INSTRUMENTS.items():
        assert set(by_sleeve[sleeve]) == set(insts_want), sleeve
        for inst, jf in by_sleeve[sleeve].items():
            assert jf.appended > 0, (sleeve, inst)
            assert jf.report.code == LF.OK

    # MES is read by two sleeves. They must hold the SAME object, not two joins of one file.
    assert by_sleeve["roska4_swing"]["MES"] is by_sleeve["roska4_calm"]["MES"]

    rep = S.join_report(by_sleeve)
    assert set(rep["instruments"]) == set(insts)
    assert rep["appended_total"] > 0 and rep["codes"] == [LF.OK]


def test_a_live_sleeve_source_without_a_provider_refuses_rather_than_inventing_one():
    with pytest.raises(NotImplementedError) as e:
        SL.LiveSleeveSource().frames(through=pd.Timestamp("2026-03-18 10:00"))
    assert "no bar provider" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# 7. the measurement gate
# ══════════════════════════════════════════════════════════════════════════════
def _fake_route(root, sleeves_src: str):
    root.mkdir(parents=True, exist_ok=True)
    for m in g.ROUTE_MODULES:
        (root / f"{m}.py").write_text("x = 1\n", encoding="utf-8")
    (root / "track1_sleeves.py").write_text(sleeves_src, encoding="utf-8")
    return root


def test_no_live_path_still_blocks(tmp_path):
    ok, detail = g.live_frame_wiring(_fake_route(tmp_path / "quiet", "x = 1\n"))
    assert ok is False and "no module" in detail


def test_an_unguarded_fetch_still_blocks(tmp_path):
    root = _fake_route(tmp_path / "raw",
                       "from ib_insync import IB\n"
                       "def bars(ib):\n    return ib.reqHistoricalData()\n")
    ok, detail = g.live_frame_wiring(root)
    assert ok is False and "without the splice guard" in detail


def test_a_fetch_through_a_provider_method_also_counts_as_a_fetch(tmp_path):
    """Stage 4C introduced a new verb. A rule that only knew the broker's own spelling would
    have had a hole exactly the width of the new code."""
    root = _fake_route(tmp_path / "prov",
                       "def bars(provider):\n"
                       "    return provider.fetch_session_bars('MES', through=None)\n")
    ok, detail = g.live_frame_wiring(root)
    assert ok is False and "without the splice guard" in detail
    assert "fetch_session_bars" in detail


def test_a_guarded_fetch_opens_the_gate(tmp_path):
    root = _fake_route(tmp_path / "good",
                       "from ib_insync import IB\n"
                       "from global_index import track1_live_frame\n"
                       "def bars(ib, hist):\n"
                       "    return track1_live_frame.splice(hist, ib.reqHistoricalData())\n")
    ok, detail = g.live_frame_wiring(root)
    assert ok is True, detail


def test_prose_still_does_not_count(tmp_path):
    root = _fake_route(tmp_path / "talk",
                       '"""One day this will call ib.reqHistoricalData via ib_insync."""\n'
                       "# fetch_bars, fetch_session_bars, reqMktData, IBKRBroker\n"
                       "x = 1\n")
    ok, detail = g.live_frame_wiring(root)
    assert ok is False and "no module" in detail


def test_the_real_route_now_fetches_and_is_guarded():
    """The measurement that decides the blocker, run on the shipped modules."""
    ok, detail = g.live_frame_wiring()
    assert ok is True, detail
    assert "track1_live_source" in detail
    assert "reqHistoricalData" in detail and "fetch_session_bars" in detail


def test_the_blocker_no_longer_blocks_and_b1_is_alone():
    assert g.self_check() == []
    blocking = {b.id for b in g.blocking()}
    # Stage 5S added PAPER_SHADOW_EVIDENCE: a MEASURED gate asking whether the shadow
    # route has produced enough judgeable days to justify an order. It cannot be signed,
    # only earned, so it holds until the evidence exists.
    assert blocking == {"B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE"}, blocking


def test_the_ledger_on_disk_still_agrees_with_the_registry():
    on_disk = json.loads(
        Path("scratch/track1_blocking_ledger_20260822.json").read_text(encoding="utf-8"))
    assert on_disk == g.as_ledger(), "regenerate the ledger; do not edit it"


def test_the_order_gate_still_refuses_without_a_confirmation(monkeypatch):
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    gate = entry.OrderGate(True)
    assert gate.allow_orders is False
    assert set(gate.blockers) == {"B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE"}
    assert not Path(g.CONFIRMATION_PATH).exists(), "this build must not create the file"


def test_closing_this_one_did_not_quietly_open_the_route(monkeypatch):
    """B1 is untouched, and it is still the thing standing in front of an exchange."""
    b1 = g.BLOCKERS["B1_broker_account_or_legacy_retirement"]
    assert b1.status == g.USER_DECISION_GATE and b1.blocks_orders
    assert b1.released_by == ("legacy_retired_confirmed", "separate_account_confirmed")
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert entry.OrderGate(True).allow_orders is False


# ══════════════════════════════════════════════════════════════════════════════
# 8. the broker stays untouched
# ══════════════════════════════════════════════════════════════════════════════
def test_importing_the_route_does_not_import_the_broker_library():
    """The fetch is real code, and it must still be inert on import.

    `ib_insync` is imported inside the method that needs it, not at the top of the module. If
    that ever moves, merely importing Track 1 — which the dashboard, the tests and the
    scheduler all do — would pull in a broker library, and a module that loads a broker library
    is one refactor away from loading a connection.
    """
    import subprocess
    code = ("import sys;"
            "import global_index.run_live_day_track1;"
            "import global_index.track1_live_source;"
            "import global_index.track1_sleeves;"
            "print('ib_insync' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path.cwd()))
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "False", out.stdout


def test_the_ibkr_provider_refuses_rather_than_opening_its_own_connection():
    """One Gateway login is one session. A module that dialled out on its own would be a
    second client competing with the runner for the same client id — which is the mechanism
    behind B1, arrived at from the other side."""
    p = S.IBKRBarProvider()
    with pytest.raises(S.LiveSourceRefused) as e:
        p.fetch_session_bars("MES", through="2026-03-18 10:00")
    assert e.value.code == "no_broker"
    assert "does not open its own connection" in e.value.detail


def test_the_shadow_route_still_cannot_send_an_order():
    broker = entry.NoOrderBroker()
    with pytest.raises(Exception):
        broker.send_order(object())
