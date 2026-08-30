"""scratch/test_track1_stage4_production_clean_20260823.py — the Stage 4 gate.

    python -m pytest scratch/test_track1_stage4_production_clean_20260823.py -q
    TRACK1_STAGE4_ALL=1 python -m pytest scratch/test_track1_stage4_production_clean_20260823.py -q

Offline. No scheduler started, no IBKR, no order, no dashboard write.

vault2026 runs by default (~35 s for Normal-R4, ~60 s for Calm A). vault2025 and floor are
opt-in because floor alone is ~4 minutes; both were run and are recorded in the report.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes  # noqa: E402
from futures.swing_tf import costs_for_basket  # noqa: E402
from global_index import specs as gi_specs  # noqa: E402
from global_index import track1_calm_a as CA  # noqa: E402
from global_index import track1_gates as g  # noqa: E402
from global_index import track1_intraday as intra  # noqa: E402
from global_index import track1_normal_filters as NF  # noqa: E402
from global_index import track1_normal_r4 as NR  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_slots as slots  # noqa: E402
from global_index._core import FuturesCost as GIFC  # noqa: E402
from global_index.regime import RegimeLabels  # noqa: E402
from scratch.normal_promotion_variant_matrix_20260821 import load_frames  # noqa: E402
from scratch.normal_sleeve_fill_audit import R4  # noqa: E402

ALL = os.environ.get("TRACK1_STAGE4_ALL") == "1"
WINDOWS = ["vault2026"] + (["vault2025", "floor"] if ALL else [])
CALM_WINDOW_MAP = {"floor": "IS_2018_2024", "vault2025": "OOS_2025",
                   "vault2026": "SANITY_2026"}
KEYS = ("day", "exit_day", "direction", "entry", "exit", "pnl")

_FRAMES: dict = {}


def _argv_val(a, f):
    return a[a.index(f) + 1] if f in a else None


def _committed(window: str) -> dict:
    return json.loads(Path(f"scratch/normal_promotion_trades_{window}_20260821.json")
                      .read_text(encoding="utf-8"))


def _frames(window: str, *, clipped: bool):
    key = (window, clipped)
    if key not in _FRAMES:
        raw = _committed(window)
        if clipped:
            _FRAMES[key] = load_frames(raw)
        else:
            argv = list(raw["argv"])
            for flag in ("--start", "--end"):
                if flag in argv:
                    i = argv.index(flag)
                    argv = argv[:i] + argv[i + 2:]
            _FRAMES[key] = load_frames({**raw, "argv": argv})
    return _FRAMES[key]


def _labels(window: str):
    fit = _argv_val(_committed(window)["argv"], "--hmm-fit-end")
    lab = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3, fit)
    return {pd.Timestamp(k).normalize(): v for k, v in lab.items()}


def _rows(trades) -> list:
    return [tuple(str(t.get(k)) for k in KEYS) for t in trades]


# ══════════════════════════════════════════════════════════════════════════════
# A. Normal-R4 — promoted, and exact
# ══════════════════════════════════════════════════════════════════════════════
def _run_normal(window: str) -> dict:
    raw = _committed(window)
    frames = _frames(window, clipped=True)
    nkd = raw["nkd_instrument"]
    lab = _labels(window)
    nlab = RegimeLabels(pd.Series(lab).sort_index(), lag_days=1)
    costs = costs_for_basket(slippage_ticks=2.0)
    c = gi_specs.SPECS[nkd]
    costs[nkd] = GIFC(point_value=c.point_value, tick=c.tick,
                      commission_rt=c.commission_rt, slippage_ticks_per_side=2.0)
    # `fill_law` is stated, not defaulted — Stage 5M-1 moved the dataclass default to the
    # PRODUCTION law, which is what the live route runs. These rows were generated under the
    # artifact law, so reproducing them means asking for it by name. That is the right way
    # round: the live law is the default and reproducing history is the explicit case.
    p_r4 = NR.NormalR4Params(fill_law=NR.FILL_ARTIFACT)
    p_nkd = NR.NormalR4Params(ema_period=10, fill_law=NR.FILL_ARTIFACT)
    return NR.generate(frames,
                       {**{i: lab for i in R4}, nkd: nlab},
                       costs,
                       {**{i: p_r4 for i in R4}, nkd: p_nkd},
                       context_filter_for=set(R4))


@pytest.mark.parametrize("window", WINDOWS)
def test_a_normal_r4_reproduces_the_committed_rows_exactly(window):
    raw = _committed(window)
    got = _run_normal(window)
    total = 0
    for inst in list(R4) + [raw["nkd_instrument"]]:
        a = _rows(raw["filtered"].get(inst, []))
        b = _rows(got[inst]["trades"])
        assert a, f"{window}/{inst}: the committed side is empty — the comparison would pass on nothing"
        first = next((i for i in range(max(len(a), len(b)))
                      if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)),
                     None)
        assert first is None, (
            f"{window}/{inst} first divergence at row {first}: "
            f"committed={a[first] if first < len(a) else '(none)'} "
            f"mine={b[first] if first < len(b) else '(none)'}")
        assert len(a) == len(b)
        total += len(a)
    assert total > 0


def test_a_the_generator_replaces_no_production_symbol():
    """The whole reason this promotion exists.

    Identity, not equality: the scratch path rebinds these names on the module and restores
    them in a `finally`, so a test that only checked afterwards would pass on it too. What
    fails here is a run that leaves ANY of them bound to a different object — and, more to the
    point, `run_instrument` never rebinds them at all.
    """
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import futures.swing_tf as ST
    import raits.strategies.trend_follow as TF

    watched = {
        "backtest_swing_tf": lambda: VC.backtest_swing_tf,
        "_swing_cache": lambda: VC._swing_cache,
        "generate_signal": lambda: TF.TrendFollowStrategy.generate_signal,
        "SwingTFEngine": lambda: ST.SwingTFEngine,
        "StressMidEngine": lambda: SM.StressMidEngine,
    }
    before = {k: id(v()) for k, v in watched.items()}
    cfg_before = dict(TF.DEFAULT_CONFIG)

    window = "vault2026"
    frames = _frames(window, clipped=True)
    lab = _labels(window)
    NR.run_instrument(frames["MES"], lab, costs_for_basket(slippage_ticks=2.0)["MES"],
                      NR.NormalR4Params(fill_law=NR.FILL_ARTIFACT),
                      short_days=NF.short_days_from_csv("spy_daily_live.csv"))

    after = {k: id(v()) for k, v in watched.items()}
    assert after == before, [k for k in before if before[k] != after[k]]
    assert dict(TF.DEFAULT_CONFIG) == cfg_before, "DEFAULT_CONFIG was mutated"


def test_a_the_promoted_filters_agree_with_the_scratch_originals():
    """A promotion, not a re-derivation — so the two have to be shown identical.

    The scratch filter library says there is exactly one implementation on purpose. This
    keeps that true by asserting the promoted copy answers the same for every 5-minute bar of
    a real instrument, rather than by hoping the copy was faithful.
    """
    import scratch.normal_promotion_filter_lib_20260821 as orig
    from scratch.directional_market_filter_probe import (allowed_short_days as o_short,
                                                         feature_frame as o_feat)

    assert NF.FLOOR_RANGE_P90 == orig.FLOOR_RANGE_P90
    assert NF.VOL_LE == orig.VOL_LE

    df = _frames("vault2026", clipped=True)["MES"]
    a = orig.R4ContextFilter(df)
    b = NF.R4ContextFilter(df)
    bars = NF.bars_5m(df).index
    assert len(bars) > 5000, "too few bars to be evidence"
    verdicts_a = [a.allow(t) for t in bars]
    verdicts_b = [b.allow(t) for t in bars]
    assert verdicts_a == verdicts_b
    assert a.stats() == b.stats()
    assert a.stats()["passed"] > 0 and a.stats()["passed"] < a.stats()["seen"], \
        "the filter passed everything or nothing — the comparison proves little"

    assert o_short(o_feat("spy_daily_live.csv"), "below_sma50") == \
        NF.short_days_from_csv("spy_daily_live.csv", "below_sma50")


def test_a_the_spy_short_gate_is_still_causal_at_d_minus_1(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=140)
    close = pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)
    csv = tmp_path / "spy.csv"
    pd.DataFrame({"date": dates, "close": close.values}).to_csv(csv, index=False)
    base = NF.short_days_from_csv(str(csv))

    d = dates[120]
    bumped = close.copy()
    bumped.loc[d] = float(bumped.loc[d]) * 10.0
    csv2 = tmp_path / "spy2.csv"
    pd.DataFrame({"date": dates, "close": bumped.values}).to_csv(csv2, index=False)
    after = NF.short_days_from_csv(str(csv2))

    assert (d in base) == (d in after), "the verdict at D moved when D's own close moved"
    changed = {x for x in dates if (x in base) != (x in after)}
    assert changed, "nothing moved — the mutation proved nothing"
    assert min(changed) > d


def test_a_params_match_the_route_identity():
    p = NR.NormalR4Params()
    cfg = tp.sleeve_config("roska4_swing", "MES", regime_csv="spy_daily_live.csv",
                           data_path="data/cache/futures/ES_continuous_1m_8y.parquet",
                           fill_law=p.fill_law)
    # Stage 4B: the law is part of the identity now, and it comes from the sleeve rather than
    # from a literal in the route. Until then the route declared the production law while
    # every row behind it had been generated under the artifact one.
    assert cfg["fill_law"] == p.fill_law
    assert p.ema_period == cfg["ema_period"] == 50
    assert p.stop_basis_atr_mult == cfg["stop_multiple"] == 2.0
    assert cfg["stop_basis"] == "fixed_entry_atr" and cfg["stop_anchor"] == "entry"
    assert p.ratchet is False and cfg["ratchet"] is False
    assert cfg["arm_hour"] == "14:05"
    assert abs(p.arm_hours - (14 + 5 / 60)) < 1e-9
    assert p.max_hold_days == cfg["max_hold_days"] == 5
    assert p.range_max == cfg["r4_range_threshold"]
    assert p.rel_volume_max == cfg["r4_rel_volume_max"]
    assert p.spy_short_filter == "below_sma50"
    assert cfg["spy_short_filter"] == "d1_spy_close_below_sma50_for_shorts_only"


def test_a_an_unknown_fill_law_is_refused():
    with pytest.raises(ValueError):
        NR.NormalR4Params(fill_law="whatever_is_convenient")


# ══════════════════════════════════════════════════════════════════════════════
# B. Calm A — a detector, not a frozen list
# ══════════════════════════════════════════════════════════════════════════════
def _calm_ref(window: str) -> pd.DataFrame:
    csv = pd.read_csv("scratch/calm_pcloc_not_deep_gap_trade_list.csv")
    return csv[csv.window == CALM_WINDOW_MAP[window]]


def _calm_detect(window: str, inst: str) -> list:
    raw = _committed(window)
    frames = _frames(window, clipped=False)
    got = CA.detect(frames[inst], _labels(window), inst)
    start, end = _argv_val(raw["argv"], "--start"), _argv_val(raw["argv"], "--end")
    if start:
        got = [s for s in got if s.day >= pd.Timestamp(start)]
    if end:
        got = [s for s in got if s.day <= pd.Timestamp(end)]
    return got


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("inst", ["MES", "MNQ"])
def test_b_calm_a_detector_reproduces_the_frozen_list_row_for_row(window, inst):
    ref = _calm_ref(window)
    r = ref[ref.inst == inst]
    want = {(str(pd.Timestamp(row["day"]).date()), round(float(row["entry"]), 4),
             round(float(row["exit"]), 4)) for _i, row in r.iterrows()}
    assert want, f"{window}/{inst}: the frozen side is empty"
    got = {(str(s.day.date()), round(float(s.entry), 4), round(float(s.exit), 4))
           for s in _calm_detect(window, inst)}
    missing, extra = sorted(want - got), sorted(got - want)
    assert not missing and not extra, (
        f"{window}/{inst}: first missing={missing[0] if missing else None} "
        f"first extra={extra[0] if extra else None}")


def test_b_the_detector_features_match_the_frozen_columns():
    """Not just the same DAYS — the same numbers behind them.

    Matching the selected set could happen with a slightly wrong feature and a compensating
    threshold. Matching the recorded feature values to 1e-9 cannot.
    """
    window, inst = "vault2026", "MES"
    ref = _calm_ref(window)
    r = ref[ref.inst == inst].set_index("day")
    got = {str(s.day.date()): s for s in _calm_detect(window, inst)}
    assert len(got) >= 10
    for day, s in got.items():
        row = r.loc[day]
        assert str(pd.Timestamp(row["prev_session_day"]).date()) == \
            str(s.prev_session_day.date()), day
        for col, val in (("gap_from_prev_rth_close", s.gap_from_prev_rth_close),
                         ("prev_close_loc", s.prev_close_loc),
                         ("prev_rth_ret", s.prev_rth_ret),
                         ("open_loc_prev_range", s.open_loc_prev_range)):
            assert abs(float(row[col]) - float(val)) < 1e-9, (day, col, row[col], val)


def test_b_the_detector_path_reads_no_frozen_csv(monkeypatch):
    """The point of the promotion. Any read of the setup list during detection fails here."""
    import builtins
    real_open = builtins.open
    real_read_csv = pd.read_csv
    banned = "calm_pcloc_not_deep_gap_trade_list"

    def guard_open(file, *a, **k):
        if banned in str(file):
            raise AssertionError(f"the detector opened the frozen list: {file}")
        return real_open(file, *a, **k)

    def guard_csv(path, *a, **k):
        if banned in str(path):
            raise AssertionError(f"the detector read the frozen list: {path}")
        return real_read_csv(path, *a, **k)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(pd, "read_csv", guard_csv)
    got = CA.detect(_frames("vault2026", clipped=False)["MES"], _labels("vault2026"), "MES")
    assert got, "the detector produced nothing — the guard proved nothing"


def test_b_only_sessions_that_ran_to_the_close_count_as_prior():
    """The rule that decides which session is PRIOR, and it is not a calendar.

    CME equity-index futures print RTH bars on an early-close holiday, so "the previous day
    with bars" is not "the previous session". The record settles it: its own prev_session_day
    column skips Christmas Eve, Black Friday and Presidents' Day.

    A calendar was tried first and is the wrong tool — `raits.live.trading_calendar` calls
    Christmas Eve and Black Friday trading days, which they are, the exchange being open. What
    this detector cannot use is a session with no 15:59 bar, because its close and its range
    would be measured at 13:00 and mean something else. With the calendar rule floor lost 5
    rows and gained 2; with this rule it is exact.
    """
    df = _frames("vault2026", clipped=False)["MES"]
    kept = CA.rth_sessions(df)
    everything = CA.rth_sessions(df, CA.CalmAParams(require_full_rth_session=False))
    dropped = sorted(set(everything.index) - set(kept.index))
    assert dropped, "no early-close session in this window — the rule is untested here"

    # Every dropped session must genuinely lack the RTH end bar, and every kept one must have
    # it. Asserted both ways, so the rule cannot pass by dropping the wrong days.
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    end_t = pd.Timestamp(CA.CalmAParams().rth_end).time()
    for d in dropped:
        sel = idx[idx.normalize() == d]
        assert not (sel.time == end_t).any(), f"{d.date()} was dropped but ran to the close"
    for d in list(kept.index)[:40]:
        sel = idx[idx.normalize() == d]
        assert (sel.time == end_t).any(), f"{d.date()} was kept but never reached the close"


@pytest.mark.skipif(not ALL, reason="the holiday case lives in vault2025; needs TRACK1_STAGE4_ALL=1")
def test_b_the_presidents_day_case_is_the_one_that_was_measured():
    """2025-02-18's prior session is 2025-02-14, not Presidents' Day 2025-02-17.

    Pinned because it is the row that found the rule: using 02-17 gives close-location 0.907
    and a gap of -0.043%; using 02-14 gives 0.308 and +0.181%. The first fails the bottom-third
    test and the day never sets up — one holiday, one lost trade.
    """
    df = _frames("vault2025", clipped=False)["MES"]
    sessions = CA.rth_sessions(df)
    assert pd.Timestamp("2025-02-17") not in sessions.index
    assert pd.Timestamp("2025-02-14") in sessions.index

    got = {str(s.day.date()): s for s in _calm_detect("vault2025", "MES")}
    assert "2025-02-18" in got, "the row this rule exists for is missing"
    assert str(got["2025-02-18"].prev_session_day.date()) == "2025-02-14"


def test_b_the_rth_window_ends_at_1559_not_1600():
    """The one bar that moves prev_close_loc across the threshold."""
    p = CA.CalmAParams()
    assert (p.rth_start, p.rth_end) == ("09:30", "15:59")
    df = _frames("vault2026", clipped=False)["MES"]
    a = CA.rth_sessions(df, p)
    b = CA.rth_sessions(df, CA.CalmAParams(rth_end="16:00"))
    common = a.index.intersection(b.index)
    assert len(common) > 50
    assert not (a.loc[common, "close"] == b.loc[common, "close"]).all(), \
        "the two windows close identically — this test is not measuring anything"


def test_b_a_partial_or_stale_frame_is_refused_by_the_intraday_gate():
    day, prior = pd.Timestamp("2026-03-02"), pd.Timestamp("2026-02-27")
    # Stage 5ZU. Calm's requirement spans two bar sizes, so every call says where the 10:00
    # OPEN is read from. Without it the verdict is UNVERIFIED — deliberately not a pass — and
    # each assertion below would be answering a question it is not about.
    quote = pd.date_range(day + pd.Timedelta(hours=9, minutes=30),
                          day + pd.Timedelta(hours=10), freq="1min")
    good = pd.concat([intra.synth_bars(prior, "09:30", "16:00"),
                      intra.synth_bars(day, "09:30", "10:00")])
    assert intra.validate("roska4_calm", good, now_et=day + pd.Timedelta(hours=10),
                          session_day=day, prior_session_day=prior,
                          entry_quote_index=quote).allow
    partial = pd.concat([intra.synth_bars(prior, "09:30", "16:00"),
                         intra.synth_bars(day, "09:45", "10:00")])
    v = intra.validate("roska4_calm", partial, now_et=day + pd.Timedelta(hours=10),
                       session_day=day, prior_session_day=prior, entry_quote_index=quote)
    assert not v.allow and intra.PARTIAL_COVERAGE in v.codes
    v = intra.validate("roska4_calm", good, now_et=day + pd.Timedelta(hours=9, minutes=45),
                       session_day=day, prior_session_day=prior, entry_quote_index=quote)
    assert not v.allow and intra.TOO_EARLY in v.codes


def test_b_the_calm_params_match_the_route_identity():
    cfg = tp.sleeve_config("roska4_calm", "MES", regime_csv="spy_daily_live.csv",
                           data_path="data/cache/futures/ES_continuous_1m_8y.parquet",
                           fill_law=NR.NormalR4Params().fill_law)
    p = CA.CalmAParams()
    assert p.instruments == tp.SLEEVE_INSTRUMENTS["roska4_calm"]
    assert cfg["label_lag_days"] == p.regime_lag_sessions == 1
    assert cfg["arm_hour"] == p.entry_time == "10:00"
    assert "pcloc_bottom_third" in cfg["calm_gate_definition"]
    assert "gap_from_prev_rth_close>=-0.01" in cfg["calm_gate_definition"]
    assert p.gap_min == -0.010
    assert "entry=10:00 exit=15:55" in cfg["calm_gate_definition"]
    assert p.exit_time == "15:55"


# ══════════════════════════════════════════════════════════════════════════════
# C. Scheduler / dashboard wiring — additive, and off by default
# ══════════════════════════════════════════════════════════════════════════════
# 60 until 2026-08-24. Stage 5Q-5 added `spy_refresh_pm` at 16:20 ET in all three modes
# (60->61 / 129->130 / 100->101): the post-close SPY refresh, shared infrastructure that a
# legacy retirement must not remove. Deliberate; pinned again at its new value.
LEGACY_JOB_COUNT = 61


def test_c_the_legacy_schedule_is_unchanged_when_track1_is_off():
    ids = slots.scheduler_slot_ids(track1_shadow=False)
    assert len(ids) == LEGACY_JOB_COUNT, len(ids)
    assert not any(i.startswith("track1_") for i in ids)
    assert "stop_repair_1220" in ids, \
        "the 12:20 sweep vanished with Track 1 OFF — legacy behaviour changed"


def test_c_enabling_track1_adds_its_slots_and_frees_the_stress_window():
    off = slots.scheduler_slot_ids(track1_shadow=False)
    on = slots.scheduler_slot_ids(track1_shadow=True)
    added, removed = on - off, off - on
    # Derived, not pinned — the `== 25` literal turned red when Stage 5M-B added the 23
    # Normal-R4 slots, a change this test has no opinion about. What it asserts is that the
    # flag adds exactly the Track 1 slots and frees exactly the one sweep inside the Stress
    # window.
    assert added, "the flag added nothing — the assertions below would pass on nothing"
    assert len(added) == len(slots.TRACK1_SLOTS)
    assert all(a.startswith("track1_") for a in added)
    assert removed == {"stop_repair_1220"}, removed


def test_c_the_entry_window_constant_is_not_duplicated():
    from global_index import run_scheduler as rs
    assert rs._TRACK1_STRESS_WINDOW == slots.REQUIRED_ENTRY_WINDOW == ((10, 35), (12, 30))
    from monitor.backend import schedule_status as ss
    assert ss.TRACK1_STRESS_WINDOW == rs._TRACK1_STRESS_WINDOW


@pytest.mark.parametrize("track1", [False, True])
def test_c_the_scheduler_and_the_dashboard_mirror_agree_in_both_modes(track1):
    r = slots.parity_report(track1_shadow=track1)
    assert r["scheduler_jobs"] > 50 and r["mirror_rows"] > 50
    assert r["in_parity"], {"only_in_scheduler": r["only_in_scheduler"],
                            "only_in_dashboard_mirror": r["only_in_dashboard_mirror"]}
    assert r["track1_shadow"] is track1


def test_c_the_parity_check_still_goes_red_when_one_side_moves(monkeypatch):
    monkeypatch.setitem(slots.MIRROR_EXEMPT, "stop_repair_0020", "pretend")
    assert not slots.parity_report()["in_parity"]


def test_c_the_dashboard_mirror_is_off_unless_the_environment_says_so(monkeypatch):
    from monitor.backend import schedule_status as ss
    monkeypatch.delenv("RAITS_TRACK1_SHADOW", raising=False)
    assert ss.track1_shadow_enabled() is False
    assert (12, 20) in ss._stop_repair_slots()
    monkeypatch.setenv("RAITS_TRACK1_SHADOW", "1")
    assert ss.track1_shadow_enabled() is True
    assert (12, 20) not in ss._stop_repair_slots()


def test_c_the_legacy_argv_is_byte_identical(monkeypatch):
    """Three log readers parse the command the scheduler prints. It must not move."""
    from global_index import run_scheduler as rs
    seen = []
    monkeypatch.setattr(rs, "_run", lambda args, label, dry_run, timeout=None:
                        seen.append((label, list(args))) or True)
    # The slot fails closed on a missing pre-flight record before it ever builds an argv, so
    # the flag is seeded for the ET date. Seeded in MEMORY only — nothing here calls
    # `_save_preflight_state`, so the operator's file is untouched.
    monkeypatch.setitem(rs._preflight_ok, rs._et_today().isoformat(), True)
    sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True)
    job = next(j for j in sched.get_jobs() if j.id == "live_day")
    job.func()
    assert seen, "the slot body did not run — the pre-flight gate was not satisfied"
    label, args = seen[0]
    assert label == "LIVE_DAY_1405"
    assert args[1:] == ["-m", "global_index.run_live_day",
                        "--data-dir", "data/cache/futures",
                        "--nkd-parquet", "global_index/data/NKD_continuous_1m_8y.parquet",
                        "--regime-csv", "spy_daily_live.csv",
                        "--live-state-path", "global_index/live_state_data.js",
                        "--clusters", "all", "--port", "4002"], args


def test_c_a_track1_slot_calls_the_shadow_route_and_nothing_else(monkeypatch):
    from global_index import run_scheduler as rs
    seen = []
    # `route=` is accepted because the real `_run` grew it in Stage 5I, when the Track 1 slot
    # started stamping `RAITS_ROUTE` on its child. A stub whose signature is narrower than the
    # function it replaces does not fail as a mismatch — it fails as a TypeError raised from
    # inside production code, which reads like the production call is wrong.
    monkeypatch.setattr(rs, "_run", lambda args, label, dry_run, timeout=None, route=None:
                        seen.append((label, list(args))) or True)
    sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True)
    job = next(j for j in sched.get_jobs() if j.id == "track1_calm_1000")
    job.func()
    label, args = seen[0]
    assert label == "TRACK1_CALM_1000"
    assert args[1:3] == ["-m", "global_index.run_live_day_track1"]
    assert "--allow-orders" not in args
    assert "--port" not in args, "the shadow route was handed a broker port"


def test_c_no_track1_order_path_without_both_factors(monkeypatch):
    from global_index import run_live_day_track1 as entry
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    assert entry.OrderGate(True).allow_orders is False
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert entry.OrderGate(True).allow_orders is False, "blockers stopped blocking"
    assert g.blocking(), "the registry reports nothing blocking"


def test_c_the_confirmation_file_still_does_not_exist():
    assert not Path(g.CONFIRMATION_PATH).exists()
