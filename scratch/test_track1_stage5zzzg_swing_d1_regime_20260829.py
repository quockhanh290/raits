"""Stage 5ZZZ-G — which regime object the Swing detector is handed, and what the backtest uses.

The stage was opened on a proposed fix: pass a D-1/causal labels object into the Swing
detector, "same as Track 1 backtest identity". Half of that is confirmed and half of it is
contradicted by the code and by measurement, so the tests split the same way:

  * the inner detector DOES receive the raw map for Swing, and therefore sees the session's own
    label - which does not exist during the session. Confirmed, pinned below.
  * the Track 1 Swing backtest is NOT D-1. It runs the same `labels.get(day)` against the same
    raw map, and the engine's own docstring says so: "R4 reads the SPY labels directly at ema
    50, while MNKD reads them through RegimeLabels(lag_days=1)". Pinned below, because a later
    reader will otherwise re-derive the wrong conclusion from the live path alone.

So no labels object was changed. What this stage adds is the ability of the panel to SAY which
object produced the value it is showing.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd                                              # noqa: E402
from global_index import track1_normal_r4 as NR                  # noqa: E402
from global_index import track1_params as tp                     # noqa: E402
from global_index import track1_strategy_diagnostics as SD       # noqa: E402
from global_index.regime import RegimeLabels                     # noqa: E402
from monitor.backend import track1_market_view as mv             # noqa: E402

ET = "America/New_York"
DAY = "2026-08-28"          # the last session with bars before this stage ran


@pytest.fixture(scope="module")
def labels():
    return mv._label_map(REPO)


@pytest.fixture(scope="module")
def payload():
    return mv.build(REPO, now=pd.Timestamp(f"{DAY} 15:00", tz=ET))


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. what the two objects actually answer
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_map_does_not_carry_the_current_session_yet(labels):
    """The whole mechanism in one fact: the label for a session is computed from that
    session's close, so during the session it does not exist."""
    assert labels, "no labels at all; everything below would pass on nothing"
    assert max(labels) < pd.Timestamp(DAY), (
        f"the map already carries {DAY}; this test's premise no longer holds")


def test_the_two_objects_answer_differently_for_that_session(labels):
    from global_index.track1_live_source import causal_regime_label

    d = pd.Timestamp(DAY)
    lag1 = RegimeLabels(pd.Series(labels).sort_index(), lag_days=1)
    assert labels.get(d) is None, "the session's own row"
    assert causal_regime_label(labels, d) == "Calm"
    assert lag1.get(d) == "Calm"


def test_they_disagree_on_a_material_share_of_history(labels):
    """Not "sometimes". Measured, because the size of the disagreement is the size of the
    change that swapping the object would make."""
    ser = pd.Series(labels).sort_index()
    lag1 = RegimeLabels(ser, lag_days=1)
    differ = sum(1 for d in ser.index if str(ser.loc[d]) != str(lag1.get(d)))
    assert differ > 0
    share = differ / len(ser)
    assert 0.05 < share < 0.20, (
        f"{differ}/{len(ser)} = {share:.1%}; if this has moved far, the stage's conclusion "
        f"about how much a swap would change needs re-measuring")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. what the detector is handed — live, reconstruction, and backtest
# ══════════════════════════════════════════════════════════════════════════════════════════

def _src(obj) -> str:
    import inspect
    return inspect.getsource(obj)


def test_the_swing_live_path_hands_the_detector_the_raw_map():
    """Confirmed, and this is the half of the brief's premise that holds."""
    from global_index import track1_live_source as LS

    src = _src(LS)
    body = src[src.index("def _swing_candidates"):]
    body = body[:body.index("\n    def ")]
    assert "labels = self._label_map()" in body
    # Stage 5ZZZ-Q RESTATED this. The finding it recorded - that the detector was handed the
    # raw map while the outer gate used the causal helper - was acted on: the operator
    # authorised the fix, and the detector now receives RegimeLabels(lag_days=1).
    #
    # The test is kept rather than deleted because the SHAPE of the defect is worth pinning:
    # the outer gate and the detector must not read different regime objects. That is now
    # asserted in the direction the route actually runs.
    assert "detect_entry_for_slot(frame, swing_labels," in body, body[-600:]
    assert "lag_days=1" in body, "the detector is no longer handed a causal object"
    # the causal helper still guards the OUTER gate
    assert "causal_regime_label(labels, day)" in body


def test_the_nkd_live_path_hands_the_detector_a_lagged_object():
    from global_index import track1_live_source as LS

    src = _src(LS)
    body = src[src.index("def _nkd_candidates"):]
    body = body[:body.index("\n    def ")]
    assert "RegimeLabels(pd.Series(labels).sort_index(), lag_days=1)" in body
    assert "detect_entry_for_slot(frame, nlab," in body


def test_the_reconstruction_mirrors_the_live_object_for_each_sleeve():
    """The reconstruction exists to show what the slot saw. Handing it a different regime
    object would make it show what the slot did NOT see, which is worse than showing
    nothing."""
    body = _src(mv._normal_r4_reconstruction)
    assert 'if sleeve == "global_nkd":' in body
    nkd = body[body.index('if sleeve == "global_nkd":'):body.index("    else:")]
    assert "RegimeLabels(" in nkd and "lag_days=1" in nkd
    swing = body[body.index("    else:"):]
    # Stage 5ZZZ-Q: the reconstruction follows the live path, which now lags Swing's labels.
    assert "lag_days=1" in swing
    assert "labels_raw" in swing


def test_the_backtest_reads_the_same_lookup_not_a_causal_one():
    """The correction this stage had to make.

    `scan_signals` and `_replay` both gate a day on `labels.get(day)`. Whether that is causal
    depends entirely on the object the caller passes, and the engine's own docstring says what
    the Track 1 identity passes: R4 directly, MNKD lagged.
    """
    scan = _src(NR.scan_signals)
    assert "reg = labels.get(day)" in scan
    gen = _src(NR.generate)
    assert "R4 reads the SPY labels directly" in gen
    assert "MNKD reads them through" in gen and "lag_days=1" in gen


def test_the_detector_gate_reports_the_value_of_whichever_object_it_got(labels):
    """The claim, exercised rather than argued: same detector, same day, same bars - two
    objects, two reported values."""
    frame = pd.read_parquet(mv._store_path("MES"))
    params = NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
    short = NR.short_days_from_csv("spy_daily_live.csv", params.spy_short_filter)
    now = pd.Timestamp(f"{DAY} 15:00", tz=ET)
    seen = {}
    for tag, obj in (("raw", labels),
                     ("lag1", RegimeLabels(pd.Series(labels).sort_index(), lag_days=1))):
        obs = SD.NormalR4Observer()
        NR.detect_entry_for_slot(frame, obj, "MES", pd.Timestamp(DAY), now, params,
                                 short_days=short, apply_context_filter=True, observer=obs)
        g = [x for x in obs.gates if x.get("gate") == "regime"]
        assert g, f"{tag}: the detector never reached its regime gate"
        seen[tag] = (g[0]["value"], g[0]["passed"])
    assert seen["raw"] == (None, False)
    assert seen["lag1"] == ("Calm", False)
    # BOTH refuse today, for different reasons - this sleeve trades Normal and the label is
    # Calm. The outcome is the same today and the REASON is not, which is exactly why the
    # panel has to report the reason rather than the outcome.
    assert NR.ALLOWED_REGIMES == frozenset({"Normal"})


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the panel can now say which object produced the value
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_basis_is_read_off_the_object_not_off_the_sleeve_name():
    ser = pd.Series({pd.Timestamp("2026-01-02"): "Calm"})
    assert SD.regime_basis(RegimeLabels(ser, lag_days=1)) == SD.REGIME_BASIS_PREV_SESSION
    assert SD.regime_basis({}) == SD.REGIME_BASIS_SAME_SESSION
    assert SD.regime_basis(object()) == SD.REGIME_BASIS_UNKNOWN
    # a lag nobody expects is described, not silently called "previous session"
    assert "2 sessions back" == SD.regime_basis(RegimeLabels(ser, lag_days=2))
    # and the function never asks which sleeve is calling. Scanned on the CODE, with the
    # docstring stripped: the first version scanned the source whole and failed on the word
    # "sleeve" inside the prose explaining why it does not look at the sleeve.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(SD.regime_basis).lstrip())
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    for name in ("global_nkd", "roska4_swing", "sleeve"):
        assert name not in code, (name, code)


@pytest.mark.parametrize("sleeve,expected", [
    ("global_nkd", SD.REGIME_BASIS_PREV_SESSION),
    # Stage 5ZZZ-Q. Swing moved to the previous session, by an authorised decision. The
    # parametrisation records the change rather than hiding it: this row said SAME_SESSION for
    # eight stages and the whole point of that stage was to stop it being true.
    ("roska4_swing", SD.REGIME_BASIS_PREV_SESSION),
])
def test_the_payload_names_the_basis_each_sleeve_used(payload, sleeve, expected):
    block = ((payload["sleeves"][sleeve].get("strategy") or {}).get("diagnostics") or {})
    assert block.get("regime_basis") == expected, block.get("regime_basis")


def test_the_regime_row_carries_the_detectors_own_value_and_says_where_it_came_from(payload):
    """The panel once showed Calm for one sleeve and Unavailable for the other with nothing to
    explain it. Both values were right and the page could not say why they differed.

    Stage 5ZZZ-Q removed the difference at its source rather than explaining it better: both
    sleeves now read the previous session's label. What this test still has to hold - and what
    it was always really for - is that the row is the DETECTOR's own value and names where it
    came from. That property does not depend on the two sleeves disagreeing.
    """
    got = {}
    for sleeve in ("global_nkd", "roska4_swing"):
        block = ((payload["sleeves"][sleeve].get("strategy") or {}).get("diagnostics") or {})
        row = next(r for r in block["rows"] if r["label"] == "Regime")
        gate = next(g for g in block["gates"] if g["gate"] == "regime")
        # the row is the DETECTOR's value, not a second lookup
        assert row.get("value") == gate.get("value"), (sleeve, row, gate)
        assert block["regime_basis"] in (row.get("detail") or ""), (sleeve, row)
        got[sleeve] = row.get("value")
    assert got["global_nkd"] == "Calm"
    # Both sleeves now resolve, and to the same previous-session label. That agreement IS the
    # outcome of Stage 5ZZZ-Q; if it breaks, something changed one sleeve and not the other.
    assert got["roska4_swing"] == got["global_nkd"], (
        "the two Normal-R4 sleeves disagree on the regime again")


def test_the_basis_is_absent_rather_than_guessed_when_nobody_supplied_it():
    """Tri-state. A block built without a basis must not claim one."""
    obs = SD.NormalR4Observer()
    block = SD.normal_r4_block(sleeve="roska4_swing", slot_id="", ema_period=50,
                               observer=obs, setup=None)
    assert block["regime_basis"] == ""
    row = next(r for r in block["rows"] if r["label"] == "Regime")
    assert SD.REGIME_BASIS_SAME_SESSION not in (row.get("detail") or "")
    assert SD.REGIME_BASIS_PREV_SESSION not in (row.get("detail") or "")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. nothing about the decision moved
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_a_missing_label_still_fails_closed():
    """Whatever object is used, no label means no trade. This is the property that must
    survive any later decision about which object Swing should read."""
    frame = pd.read_parquet(mv._store_path("MES"))
    params = NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
    short = NR.short_days_from_csv("spy_daily_live.csv", params.spy_short_filter)
    now = pd.Timestamp(f"{DAY} 15:00", tz=ET)
    empty = RegimeLabels(pd.Series(dtype=object), lag_days=1)
    for obj in ({}, empty):
        obs = SD.NormalR4Observer()
        setup = NR.detect_entry_for_slot(frame, obj, "MES", pd.Timestamp(DAY), now, params,
                                         short_days=short, apply_context_filter=True,
                                         observer=obs)
        assert setup is None
        gate = [g for g in obs.gates if g.get("gate") == "regime"]
        assert gate and gate[0]["passed"] is False and gate[0]["value"] is None


def test_no_sleeve_changed_which_object_it_hands_the_detector():
    """A guard, not a preference.

    Swapping Swing to a D-1 object changes which days it trades - measured at 44 entries lost
    and 49 gained against the backtest identity - so it is a decision with a number attached
    and must not arrive as a quiet edit. If this test fails, that decision was made somewhere;
    find it before changing the test.
    """
    from global_index import track1_live_source as LS

    src = _src(LS)
    swing = src[src.index("def _swing_candidates"):]
    swing = swing[:swing.index("\n    def ")]
    # Stage 5ZZZ-Q. The guard has served its purpose and is inverted, not removed. It asked
    # "who decided?" - the operator did, in Stage 5ZZZ-Q, on the record and after Stage
    # 5ZZZ-H measured what the swap costs. What must hold now is the opposite, and just as
    # firmly: Swing must KEEP the causal object, and NKD must never lose it.
    assert "RegimeLabels" in swing, "Swing lost its causal object; who decided?"
    assert "lag_days=1" in swing
    nkd = src[src.index("def _nkd_candidates"):]
    nkd = nkd[:nkd.index("\n    def ")]
    assert "lag_days=1" in nkd, "NKD stopped lagging its labels"


def test_the_diagnostics_are_descriptive_only():
    """`regime_basis` may never reach a decision. It is a string for a panel."""
    import inspect

    body = inspect.getsource(NR)
    assert "regime_basis" not in body, "the detector now reads a display string"
    from global_index import track1_live_source as LS
    stash = inspect.getsource(LS.LiveTrack1Source._stash_diagnostics)
    assert "return" not in stash.split("block =")[0].split("try:")[-1], stash


def test_orders_remain_impossible():
    from global_index import track1_gates as g

    ok, _ = g.may_enable_orders()
    assert ok is False
    blocking = {b.id for b in g.blocking()}
    assert blocking and blocking <= set(g.BLOCKERS)


def test_no_order_artefacts_and_the_decision_is_intact():
    import os

    from global_index import track1_gates as g

    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")
    conf = REPO / g.CONFIRMATION_PATH
    if conf.exists():
        assert (json.loads(conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip()
