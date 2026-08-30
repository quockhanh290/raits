"""Stage 5ZZZ-Q — the live Swing detector reads the previous session's label.

For eight stages the signed paper identity said causal D-1 and the live detector read the
session's own row, and no recorded row said either. These tests pin the fix at the place it
matters: the object handed to the detector, not the sleeve's name and not a comment.
"""
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd                                              # noqa: E402
from global_index import run_live_day_track1 as RUN             # noqa: E402
from global_index import track1_live_source as LS               # noqa: E402
from global_index import track1_normal_r4 as NR                 # noqa: E402
from global_index import track1_signals as SIG                  # noqa: E402
from global_index.regime import RegimeLabels                    # noqa: E402


def _frames():
    from futures.basket import BASKET, data_filename
    from global_index._core import load_parquet

    out = {}
    for inst in ("MES", "MNQ", "M2K", "MYM"):
        p = REPO / "data/cache/futures" / data_filename(BASKET[inst])
        if p.exists():
            out[inst] = load_parquet(str(p))
    nkd = REPO / "global_index/data/NKD_continuous_1m_8y.parquet"
    if nkd.exists():
        out["MNKD"] = load_parquet(str(nkd))
    return out


class _JF:
    def __init__(self, frame):
        self.frame = frame
        self.report = types.SimpleNamespace(code="stubbed")


@pytest.fixture(scope="module")
def handed():
    """What each live sleeve actually passes its detector. The bar join is stubbed; the labels
    wiring is what is under test."""
    frames = _frames()
    if not frames:
        pytest.skip("no bar stores in this checkout")
    seen = {"roska4_swing": [], "global_nkd": []}
    orig_detect, orig_frames = NR.detect_entry_for_slot, LS.sleeve_frames
    bucket = {"name": None}

    def spy(df, labels, inst, day, now, params, **kw):
        seen[bucket["name"]].append({
            "inst": inst, "type": type(labels).__name__,
            "lag": getattr(labels, "lag", None),
            "resolved": str(labels.get(pd.Timestamp(day))) if hasattr(labels, "get") else None})
        return None

    NR.detect_entry_for_slot = spy
    LS.sleeve_frames = lambda **kw: {s: {i: _JF(f) for i, f in frames.items()}
                                     for s in ("roska4_swing", "global_nkd")}
    try:
        src = LS.LiveTrack1Source(bar_provider=object(), frozen_frames=frames)
        day, now = pd.Timestamp("2026-08-28"), pd.Timestamp("2026-08-28 15:00",
                                                            tz="America/New_York")
        for name, fn in (("roska4_swing", src._swing_candidates),
                         ("global_nkd", src._nkd_candidates)):
            bucket["name"] = name
            try:
                fn(day=day, now=now)
            except Exception:                                      # noqa: BLE001
                pass
    finally:
        NR.detect_entry_for_slot = orig_detect
        LS.sleeve_frames = orig_frames
    return seen


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the object the detector is handed
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_live_swing_receives_a_causal_d1_object(handed):
    calls = handed["roska4_swing"]
    assert calls, "the Swing detector was never reached; this would pass on nothing"
    for c in calls:
        assert c["type"] == "RegimeLabels", (c["inst"], c["type"])
        assert c["lag"] == 1, (c["inst"], c["lag"])


def test_live_swing_no_longer_receives_the_raw_map(handed):
    """The defect, stated as its own test: a plain dict is the same-day lookup."""
    for c in handed["roska4_swing"]:
        assert c["type"] != "dict", "the detector is back on the raw map"


def test_live_swing_resolves_a_label_at_slot_time(handed):
    """It used to resolve None at 14:05, because the session's own row does not exist yet.
    That is what made the sleeve refuse every session."""
    for c in handed["roska4_swing"]:
        assert c["resolved"] not in (None, "None"), c


def test_live_nkd_is_unchanged(handed):
    calls = handed["global_nkd"]
    assert calls, "the NKD detector was never reached"
    for c in calls:
        assert c["type"] == "RegimeLabels" and c["lag"] == 1, c


def test_the_two_normal_r4_sleeves_now_agree_on_the_object(handed):
    kinds = {(c["type"], c["lag"]) for c in handed["roska4_swing"] + handed["global_nkd"]}
    assert kinds == {("RegimeLabels", 1)}, kinds


def test_the_object_returns_the_previous_session_label():
    """Independent of the wiring: the object itself, on sessions where the two differ."""
    from futures._validated_core import benchmark_daily, label_regimes

    bench = benchmark_daily("spy_daily_live.csv")
    bench = bench[bench.index <= pd.Timestamp("2024-12-31")]
    ser = pd.Series(label_regimes(bench, "2018-01-01", 3, "2022-12-31"))
    idx = pd.DatetimeIndex(ser.index)
    ser.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    ser = ser.sort_index()
    lag1 = RegimeLabels(ser, lag_days=1)
    prev = ser.shift(1)
    dis = [d for d in ser.index[1:] if str(ser.loc[d]) != str(prev.loc[d])]
    assert len(dis) > 100, "too few disagreeing sessions for this to mean anything"
    for d in dis:
        assert str(lag1.get(d)) == str(prev.loc[d]) != str(ser.loc[d]), d


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. the evidence row
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_signal_row_records_the_regime_basis():
    row = SIG.build_row(sleeve="roska4_swing", slot_id="X", slot_time="14:45",
                        session_date="2026-08-31", mode="shadow_live", decided=True,
                        reason="decided",
                        regime_basis=RUN._signal_regime_basis("roska4_swing"))
    assert getattr(row, "regime_basis") == "causal_d1"


def test_the_basis_comes_from_the_call_sites_not_the_sleeve_name():
    """`SLEEVE_REGIME_BASIS` must describe what the code does. If a call site changes and this
    map does not, the row lies - so the map is checked against the live source."""
    import inspect

    src = inspect.getsource(LS)
    swing = src[src.index("def _swing_candidates"):]
    swing = swing[:swing.index("\n    def ")]
    assert RUN.SLEEVE_REGIME_BASIS["roska4_swing"] == "causal_d1"
    assert "lag_days=1" in swing, "the map says causal_d1 and the call site no longer is"
    nkd = src[src.index("def _nkd_candidates"):]
    nkd = nkd[:nkd.index("\n    def ")]
    assert RUN.SLEEVE_REGIME_BASIS["global_nkd"] == "causal_d1"
    assert "lag_days=1" in nkd


def test_a_row_written_before_this_stage_has_no_basis_and_is_not_assumed_to_match():
    """Old rows default to "" so parity reports them as not-applicable, never as a match."""
    row = SIG.build_row(sleeve="roska4_swing", slot_id="X", slot_time="14:45",
                        session_date="2026-08-28", mode="shadow_live", decided=True,
                        reason="decided")
    assert getattr(row, "regime_basis") == ""


def test_the_params_hash_is_empty_honestly_not_partially():
    """`route_params` refuses a config missing any of its 27 fields, and one of them is a
    file hash the decision path deliberately does not compute. An empty hash is the honest
    answer; a cheap one would be the partial identity that module forbids."""
    assert RUN._signal_params_hash("roska4_swing") == ""
    doc = RUN._signal_params_hash.__doc__ or ""
    assert "partial" in doc and "explanation record" in doc


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. nothing else moved
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_no_strategy_parameter_changed():
    from futures.basket import SWING_TF_PARAM

    assert SWING_TF_PARAM == {"ema_period": 30, "chandelier_atr_mult": 2.5, "max_hold_days": 5}
    p = NR.NormalR4Params()
    assert (p.ema_period, p.stop_basis_atr_mult, p.chandelier_atr_mult, p.max_hold_days) == \
        (50, 2.0, 2.5, 5)
    assert p.rel_volume_max == 2.0 and p.vol_feature == "rvol_slot20"


def test_the_metadata_cannot_open_a_gate():
    import inspect

    from global_index import track1_gates as g

    src = inspect.getsource(g)
    for token in ("regime_basis", "SLEEVE_REGIME_BASIS", "track1_replay_parity"):
        assert token not in src, token
    ok, _ = g.may_enable_orders()
    assert ok is False
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in g.blocking()}


def test_orders_remain_impossible_and_no_order_artefacts():
    import os

    from global_index import track1_gates as g

    ok, _ = g.may_enable_orders()
    assert ok is False
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")


def test_the_selected_baseline_artifacts_are_untouched():
    """The live change must not have reached the artifact path - it goes through deploy_sim,
    not through the live source."""
    import hashlib

    want = {"floor": "2474723814ae3e92", "vault2025": "c27ca3902b116912",
            "vault2026": "1ee198a9f10387c8"}
    for w, h in want.items():
        p = REPO / "scratch" / f"normal_promotion_trades_{w}_d1repro_20260829.json"
        if not p.exists():
            pytest.skip(f"{p.name} not present in this checkout")
        got = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        assert got == h, (w, want[w], got)
