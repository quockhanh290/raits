"""Stage 5ZZZ-M — the artifact regeneration must be honest about which parameters it ran.

Stage 5ZZZ-L asked for ema=50 and got an artifact byte-identical to the "ema=30 default", and
spent a stage unable to say whether the parameter had been ignored. It had not been ignored. The
regeneration performs a deliberate substitution - a request for the Rổ 4 value 30 becomes Track
1's own 50 - and nothing anywhere recorded that, so a true equivalence was indistinguishable from
a broken pipeline.

These tests pin the rule, pin the consequence, and pin the metadata that makes the difference
readable without running anything.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd                                              # noqa: E402

import scratch.track1_stage5zzzh_swing_d1_regen_20260829 as REGEN   # noqa: E402

ART = REPO / "scratch"


def sha(name: str) -> str:
    p = ART / name
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the rule, and that it is the harness's rule and not a story about it
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_substitution_lives_in_the_harness_and_is_quoted_correctly():
    """If this line moves or changes, `effective_params` is lying and every sidecar with it."""
    src = (REPO / "scratch" / "harness.py").read_text(encoding="utf-8")
    assert "if cfg.ema is not None and ema_period == 30:" in src
    assert "ema_period = cfg.ema" in src
    # and the regeneration is the caller that sets cfg.ema
    regen = (REPO / "scratch" / "normal_promotion_regen_audit_20260821.py").read_text(
        encoding="utf-8")
    assert "ema=50" in regen and "stop_basis=2.0" in regen


def test_requesting_the_legacy_ema_actually_runs_track1s_ema():
    e = REGEN.effective_params(30, 2.5)
    assert e["asked_ema_period"] == 30
    assert e["effective_ema_period"] == 50
    assert e["ema_was_substituted"] is True


@pytest.mark.parametrize("ema", [10, 20, 50])
def test_every_other_ema_passes_through_untouched(ema):
    e = REGEN.effective_params(ema, 2.0)
    assert e["effective_ema_period"] == ema
    assert e["ema_was_substituted"] is False


def test_the_default_request_is_the_substituted_one():
    """`--ema` unset means the regeneration's own hardcoded 30, which becomes 50."""
    e = REGEN.effective_params(None, None)
    assert e["asked_ema_period"] == 30
    assert e["effective_ema_period"] == 50


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. the consequence, on artifacts that exist
# ══════════════════════════════════════════════════════════════════════════════════════════

CASES = {
    "d1": (30, 2.5),          # the "default" - effectively ema 50
    "d1f": (50, 2.0),         # the WFO winner - effectively ema 50
    "t50m25": (50, 2.5),      # ema 50, the other chandelier
    "t20m25": (20, 2.5),      # effectively ema 20
    "d1r": (10, 2.5),         # effectively ema 10
}


def _present():
    out = {}
    for tag, (ema, mult) in CASES.items():
        n = f"normal_promotion_trades_vault2026_{tag}_20260829.json"
        if (ART / n).exists():
            out[tag] = (REGEN.effective_params(ema, mult)["effective_ema_period"], sha(n))
    return out


def test_artifacts_are_identical_exactly_when_the_effective_ema_matches():
    """The property Stage 5ZZZ-L could not state. Equal effective parameters must give equal
    artifacts, and different ones must give different artifacts - both directions."""
    have = _present()
    assert len(have) >= 3, f"not enough artifacts to compare: {sorted(have)}"
    tags = sorted(have)
    compared = 0
    for i, a in enumerate(tags):
        for b in tags[i + 1:]:
            ema_a, sha_a = have[a]
            ema_b, sha_b = have[b]
            compared += 1
            if ema_a == ema_b:
                assert sha_a == sha_b, (
                    f"{a} and {b} share effective ema {ema_a} but differ in bytes")
            else:
                assert sha_a != sha_b, (
                    f"{a} (ema {ema_a}) and {b} (ema {ema_b}) produced identical artifacts")
    assert compared >= 3, "the loop compared almost nothing"


def test_the_ema30_and_ema50_artifacts_are_the_same_run():
    """Not a coincidence and not a bug: they are the same effective parameter."""
    have = _present()
    if "d1" not in have or "d1f" not in have:
        pytest.skip("both artifacts are needed for this comparison")
    assert have["d1"][0] == have["d1f"][0] == 50
    assert have["d1"][1] == have["d1f"][1]


def test_the_chandelier_multiple_changes_no_decision_in_this_pipeline():
    """With ratchet False and a stop basis set, the day loop never recomputes the stop, so the
    multiple only reaches the strategy config. Asserted on artifacts, not on the docstring."""
    have = _present()
    if "d1f" not in have or "t50m25" not in have:
        pytest.skip("need ema=50 at two chandelier values")
    assert have["d1f"][0] == have["t50m25"][0] == 50
    assert have["d1f"][1] == have["t50m25"][1], (
        "the chandelier changed the artifact; `chandelier_affects_decisions` is now wrong")
    assert REGEN.effective_params(50, 2.0)["chandelier_affects_decisions"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the metadata that makes it readable
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_a_generated_artifact_carries_a_sidecar_with_its_effective_params():
    side = ART / "normal_promotion_trades_vault2026_d1f_20260829.params.json"
    if not side.exists():
        pytest.skip("the d1f sidecar has not been generated in this checkout")
    d = json.loads(side.read_text(encoding="utf-8"))
    assert d["asked_ema_period"] == 50
    assert d["effective_ema_period"] == 50
    assert d["effective_stop_basis_atr_mult"] == 2.0
    assert d["ratchet"] is False
    assert d["artifact_sha256"] == sha(d["artifact"])


def test_the_sidecar_records_the_effective_value_not_the_requested_one():
    """The whole point. A sidecar that echoed the request would be no better than the CLI."""
    e = REGEN.effective_params(30, 2.5)
    assert e["effective_ema_period"] != e["asked_ema_period"]
    assert e["effective_ema_period"] == 50


def test_the_baseline_promotion_artifacts_are_untouched():
    """Every fix in this stage is additive. The hash-pinned baselines must not move."""
    expect = {"floor": "f4d8eea7cd051b3d", "vault2025": "c7eb5dd2e375316b",
              "vault2026": "b1e85b2c9ab7019d"}
    for w, want in expect.items():
        got = sha(f"normal_promotion_trades_{w}_20260821.json")[:16]
        assert got == want, f"{w}: baseline moved {want} -> {got}"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. the cache, and why its key is complete
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_swing_cache_holds_nothing_parameter_dependent():
    """`_swing_cache` is keyed on `id(df)` alone, which would be a defect if it cached anything
    the parameters change. It caches daily ATR, the day list, per-day OHLC arrays and per-day
    5-minute frames - all price-derived. The key is complete FOR WHAT IT HOLDS."""
    import inspect

    from futures import _validated_core as VC

    # Scanned on the CODE with the docstring stripped. The first version scanned the source
    # whole and failed on the word "chandelier" inside the prose explaining why the cached
    # daily ATR needs unsliced history - the same docstring trap as Stage 5ZZZ-G.
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(VC._swing_cache)))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    src = ast.unparse(fn)
    for forbidden in ("ema_period", "chandelier", "max_hold"):
        assert forbidden not in src, (
            f"_swing_cache now stores something derived from {forbidden}; its id(df) key is "
            f"no longer complete")


def test_the_cache_does_not_leak_parameters_between_calls():
    """Behavioural, not textual: the SAME frame object through the cache twice, at two emas
    that are known to differ, must still produce different trades."""
    from futures import _validated_core as VC
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import costs_for_basket
    from futures._validated_core import benchmark_daily, label_regimes
    from global_index._core import load_parquet
    from global_index.regime import RegimeLabels

    df = load_parquet(str(REPO / "data/cache/futures/frozen_sim"
                          / data_filename(BASKET["MES"])))
    df = df[df.index >= pd.Timestamp("2023-01-01").tz_localize(df.index.tz)]
    bench = benchmark_daily("spy_daily_live.csv")
    bench = bench[bench.index <= pd.Timestamp("2024-12-31")]
    ser = pd.Series(label_regimes(bench, "2018-01-01", 3, "2022-12-31"))
    idx = pd.DatetimeIndex(ser.index)
    ser.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    lab = RegimeLabels(ser.sort_index(), lag_days=1)
    cost = costs_for_basket(slippage_ticks=2.0)["MES"]

    a = VC.backtest_swing_tf(df, lab, cost, ema_period=10, chandelier_atr_mult=2.5,
                             max_hold_days=5)
    b = VC.backtest_swing_tf(df, lab, cost, ema_period=50, chandelier_atr_mult=2.5,
                             max_hold_days=5)
    assert a and b, "no trades at all; this would pass on nothing"
    ka = {(str(t["day"]), str(t.get("direction") or t.get("dir"))) for t in a}
    kb = {(str(t["day"]), str(t.get("direction") or t.get("dir"))) for t in b}
    assert ka != kb, (
        "the same frame at ema 10 and ema 50 produced identical trades; the cache is leaking")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. safety
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_frozen_swing_param_was_not_changed():
    from futures.basket import SWING_TF_PARAM

    assert SWING_TF_PARAM == {"ema_period": 30, "chandelier_atr_mult": 2.5, "max_hold_days": 5}


def test_orders_remain_impossible():
    from global_index import track1_gates as g

    ok, _ = g.may_enable_orders()
    assert ok is False
    blocking = {b.id for b in g.blocking()}
    assert blocking and blocking <= set(g.BLOCKERS)


def test_no_order_artefacts():
    import os

    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")
