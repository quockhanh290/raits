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


@pytest.mark.xfail(strict=True, reason=(
    "STAGE 2 OUTSTANDING — roska4_stress emits `wide_count` and declares it nowhere. "
    "`basket_state` already returns the value, so no new seam is needed: add the declared "
    "name and the bridge entry. This turns green the moment that lands, and strict xfail "
    "then fails, which is what forces this marker to be removed."))
def test_stress_declares_every_rule_its_detector_reports():
    for gate in ("below_count", "gapdown_count", "wide_count", "avg_gap"):
        name = SIG.declared_for("roska4_stress", gate)
        assert name is not None and name in SIG.rule_names("roska4_stress"), gate


@pytest.mark.xfail(strict=True, reason=(
    "STAGE 3 OUTSTANDING — roska4_calm has NO reporter. `track1_calm_a` takes no observer "
    "and emits no gate, so its six declared entry conditions have never carried a verdict "
    "anywhere. Building that seam is the same shape of work as the Normal-R4 one and needs "
    "its own plan before the detector is touched."))
def test_calm_detector_reports_its_gates():
    import inspect

    from global_index import track1_calm_a as CA
    assert "observer" in inspect.getsource(CA)
