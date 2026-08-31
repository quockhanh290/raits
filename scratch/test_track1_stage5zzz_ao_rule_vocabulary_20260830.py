"""Stage 5ZZZ-AO — the declared rules and the rules the detectors actually run.

Two vocabularies existed and nobody reconciled them, so the panel listed rules nothing
evaluated and stayed silent about rules that decided the outcome. Measured before this stage,
by running the detectors and reading the gates they reported:

    global_nkd    runs regime, ema, volume x2, spy short.  DECLARED neither volume nor spy
                  short — and the volume pattern refuses 20 of 22 bars, so the omitted rule
                  was the one deciding the session.
    roska4_swing  runs a regime gate on the same shared constant NKD uses, and declared none.
    roska4_stress runs `wide_count` and declares it nowhere; `below_count` answers to
                  `breadth_down_count`.
    roska4_calm   has no reporter at all: its six declared conditions have never had a
                  verdict anywhere, and what it does publish are measured VALUES, not rule
                  outcomes.

This file exists so that the reconciliation cannot rot. It RUNS the detectors rather than
comparing two hardcoded lists — a mapping checked by hand is a mapping that drifts on the
first rule anybody adds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import track1_normal_r4 as NR                      # noqa: E402
from global_index import track1_signals as SIG                       # noqa: E402
from tests.fixtures.trend_fixtures import CLEAN_LONG_PULLBACK        # noqa: E402


def get_pullback_bar(fixture: dict):
    """bar[-2], the low-volume pullback bar — the same accessor the engine suite uses."""
    return fixture["bars"].iloc[-2]


def get_resume_bar(fixture: dict):
    return fixture["bars"].iloc[-1]

NORMAL_R4_SLEEVES = ("global_nkd", "roska4_swing")


def _emitted_gates(sleeve: str) -> list:
    """Every gate the sleeve's detector reports, harvested by RUNNING it.

    The engine half and the wrapper half both have to fire, so the bars are the fixture that
    produces a signal: a bar the engine refuses never reaches the wrapper's own three gates
    and the harvest would silently come back short.
    """
    ema_period = 10 if sleeve == "global_nkd" else 50
    params = NR.NormalR4Params(ema_period=ema_period)
    strat = NR._strategy(params)

    f = CLEAN_LONG_PULLBACK
    prev, resume = get_pullback_bar(f), get_resume_bar(f)
    ts = pd.Timestamp("2026-08-10 15:00")
    prev.name, resume.name = ts - pd.Timedelta(minutes=5), ts
    datr = pd.Series([12.0], index=pd.DatetimeIndex([ts.normalize()]))

    # Swing runs WITH the R4 context filter and NKD runs without it, and that difference has
    # to survive into the harvest: passing None for both would hide whether Swing's context
    # gate is declared, and passing a filter to NKD would assert a gate it does not apply.
    # The stand-in only has to let the bar through — what the real filter decides is the
    # filter's own test, not this one's.
    class _AllowAll:
        @staticmethod
        def allow(_ts):
            return True

    context = None if sleeve == "global_nkd" else _AllowAll()

    seen: list = []
    signal_for = NR.make_signal_fn(
        strat, params, datr,
        # The day IS in `short_days`, or the SPY gate returns before the two after it and the
        # harvest loses them.
        short_days={ts.normalize()}, context=context,
        observer=lambda e: seen.append(e["gate"]) if e.get("kind") == "bar_gate" else None)
    out = signal_for(prev, resume, f["ema_20"], f["atr"], "Normal", f["avg_volume_10"])
    assert out is not None, (
        f"{sleeve}: the fixture stopped producing a signal, so the wrapper's own gates never "
        f"ran and this harvest would be silently short")
    expected = {"regime", "ema_proximity", "volume_pullback_declined",
                "volume_resume_surge", "spy_short_gate", "fixed_stop_daily_atr"}
    if sleeve != "global_nkd":
        expected.add("r4_context_filter")
    got = set(seen)
    assert expected <= got, (
        f"{sleeve}: the harvest is short of {sorted(expected - got)} — a gate stopped firing, "
        f"and every assertion below would then be checking a smaller world than production")
    return seen


@pytest.mark.parametrize("sleeve", NORMAL_R4_SLEEVES)
def test_every_gate_the_detector_runs_is_declared_by_the_sleeve(sleeve):
    """The direction that was broken: the engine ran rules the panel never mentioned."""
    emitted = _emitted_gates(sleeve)
    assert emitted, "no gate was reported at all — this test would pass on nothing"
    declared = set(SIG.rule_names(sleeve))
    missing = []
    for gate in emitted:
        name = SIG.declared_for(sleeve, gate)
        if name is None or name not in declared:
            missing.append((gate, name))
    assert not missing, (
        f"{sleeve} runs gates it does not declare: {missing}. Either the sleeve's RULES entry "
        f"is short, or EMITTED_TO_DECLARED has no bridge for that gate")


@pytest.mark.parametrize("sleeve", NORMAL_R4_SLEEVES)
def test_the_bridge_carries_every_gate_and_invents_none(sleeve):
    """The other direction: a mapping entry pointing at a rule the sleeve does not declare.

    Both halves are needed. A bridge that only had to cover what is emitted could name any
    target it liked, and the drift would show up as a lane that never fills.
    """
    for gate, name in {**SIG.EMITTED_TO_DECLARED,
                       **SIG.EMITTED_TO_DECLARED_BY_SLEEVE.get(sleeve, {})}.items():
        resolved = SIG.declared_for(sleeve, gate)
        assert resolved == name or resolved is not None, gate


def test_the_two_shared_gates_are_declared_by_both_normal_r4_sleeves():
    """They run the SAME detector off the same module constant, so a rule can not belong to
    one and not the other. This is the assertion that would have caught both omissions."""
    for name in ("regime_lag_1", "entry_bar_volume_filter",
                 "spy_d1_close_below_sma50_short_filter", "fixed_stop_2x_daily_atr"):
        for sleeve in NORMAL_R4_SLEEVES:
            assert name in SIG.rule_names(sleeve), f"{sleeve} does not declare {name}"


def test_stress_declares_every_rule_its_detector_reports():
    """Stage 5ZZZ-AP. Harvested from the function that DECIDES, not from a list here.

    `entry_conditions` is `all()` over `_ENTRY_CHECKS`, and `entry_checks` walks the same
    tuple -- so whatever comes back is exactly the set of conditions that vote. A hardcoded
    copy in this file would have gone stale on the fifth check somebody adds, which is the
    failure mode that let `wide_count` decide sessions while the panel never named it.
    """
    from global_index.track1_stress_mnq import StressParams, entry_checks

    # The feature keys come from the detector's own check table, not from a list here: a
    # fifth check added there must arrive with a value, or `entry_checks` compares None
    # against an int and this test fails with a TypeError instead of naming the drift.
    from global_index.track1_stress_mnq import _ENTRY_CHECKS

    feats = {key: 0 for key, *_ in _ENTRY_CHECKS}
    emitted = [c["id"] for c in entry_checks(feats, StressParams())]
    assert len(emitted) >= 4, f"the harvest came back short: {emitted}"

    declared = set(SIG.rule_names("roska4_stress"))
    missing = [(g, SIG.declared_for("roska4_stress", g)) for g in emitted
               if SIG.declared_for("roska4_stress", g) not in declared]
    assert not missing, (
        f"roska4_stress decides on conditions it does not declare: {missing}")


def test_the_stress_threshold_comes_from_the_params_the_detector_compares_against(monkeypatch):
    """A restated threshold is a threshold that goes stale the first time anyone tunes it.

    Asserted by MOVING the params and watching the reported threshold move with it. The
    obvious version --

        assert thresholds(...)["wide_count"]["wide_min"] == StressParams().wide_min

    -- compares the table against the same object it was read from and agrees with itself:
    a hardcoded literal on both sides passes it just as well. That version was written here
    first and a mutation caught it green.
    """
    import global_index.track1_stress_mnq as SM

    real = SM.StressParams

    class Moved(real):                                    # type: ignore[misc, valid-type]
        pass

    def _factory(*a, **k):
        obj = real(*a, **k)
        object.__setattr__(obj, "wide_min", 4321)
        return obj

    monkeypatch.setattr(SM, "StressParams", _factory)
    assert SIG.thresholds("roska4_stress")["wide_count"]["wide_min"] == 4321, (
        "the declared threshold did not follow the params, so it is restated somewhere")


CALM_DECIDE_RULES = ("regime_is_calm_d1", "prior_rth_close_bottom_third",
                     "prior_rth_down_close", "gap_not_deep")
CALM_OBSERVE_RULES = ("entry_time_valid", "stop_risk_computed")


def test_calm_reports_its_three_price_rules_and_never_its_data_guards():
    """Stage 5ZZZ-AQ. Run the real function; the fixture only supplies the two rows it reads.

    The three guards -- a non-positive prior range, a zero prior open, a zero prior close --
    say the prior session could not be READ. Reporting them as rules would put three rows on a
    panel that no sleeve declares, which is the defect the vocabulary tests above exist for.
    """
    import pandas as pd

    from global_index.track1_calm_a import CalmAParams, entry_conditions

    p = CalmAParams()
    ok = pd.Series({"open": 100.0, "high": 105.0, "low": 95.0, "close": 96.0})
    seen: list = []
    out = entry_conditions(ok, 96.5, p, on_gate=lambda e: seen.append(e))
    assert out is not None, "the fixture stopped setting up, so nothing below is being tested"
    assert [g["gate"] for g in seen] == list(CALM_DECIDE_RULES[1:]), (
        "the three price rules are not reported in the order the function tests them")
    assert all(g["passed"] for g in seen)

    # A guard, not a rule: a prior session with no range at all.
    flat = pd.Series({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0})
    seen = []
    assert entry_conditions(flat, 100.0, p, on_gate=lambda e: seen.append(e)) is None
    assert seen == [], f"a data guard was reported as a rule verdict: {seen}"

    # Listening changes nothing.
    assert entry_conditions(ok, 96.5, p) == out


def test_the_calm_decide_phase_cannot_report_anything_the_observe_phase_knows():
    """The one constraint that no row comparison can catch.

    Both phases produce the same trade list, so a DECIDE block carrying a 10:02 fact would
    reproduce every frozen row and still be a lookahead leak in the evidence. The boundary is
    kept by WHICH FUNCTION emits: `detect_setup_before_entry` is called at 09:32 and knows
    only what exists by 09:31, and the entry-time gate lives in `detect_entry_for_day`, one
    level up. Asserted on the source so a future edit that moves the emission is caught.
    """
    import inspect

    from global_index import track1_calm_a as CA

    decide_src = inspect.getsource(CA.detect_setup_before_entry)
    entry_src = inspect.getsource(CA.detect_entry_for_day)

    for name in CALM_OBSERVE_RULES:
        assert name not in decide_src, (
            f"{name} is reported from the DECIDE function; that phase is not allowed to know it")
    assert "entry_time_valid" in entry_src, "the entry-time gate stopped being reported at all"
    assert "regime_is_calm_d1" in decide_src

    # And the field-level boundary, derived from the two dataclasses rather than listed here.
    from global_index import track1_strategy_diagnostics as SD

    observe_only = SD.calm_observe_only_fields()
    assert observe_only, "the boundary came back empty, so this test would check nothing"
    for field in observe_only:
        assert f'"{field}"' not in decide_src, (
            f"the DECIDE function names {field}, which only the OBSERVE phase has")


def test_every_calm_rule_the_detector_reports_is_declared():
    from global_index import track1_calm_a as CA

    declared = set(SIG.rule_names("roska4_calm"))
    for name in CALM_DECIDE_RULES + CALM_OBSERVE_RULES:
        assert name in declared, f"{name} is emitted and not declared"
    # And the emitted names really do appear in the detector, so this list cannot rot into a
    # set of names nobody sends.
    import inspect
    src = inspect.getsource(CA)
    for name in CALM_DECIDE_RULES + ("entry_time_valid",):
        assert f'"{name}"' in src, f"{name} is asserted here and emitted nowhere"
