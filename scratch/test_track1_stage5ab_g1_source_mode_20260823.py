"""scratch/test_track1_stage5ab_g1_source_mode_20260823.py — the Stage 5AB-G1 gate.

    python -m pytest scratch/test_track1_stage5ab_g1_source_mode_20260823.py -q

Offline. No scheduler, no IBKR, no order, no dashboard write, no network. Nothing here sets
`TRACK1_ORDERS_APPROVED` or arms a real gate: the armed branch is exercised with a stub whose
only job is to answer `allow_orders`, which is all `decision_mode_for` reads.

G1
--
`run_shadow()` took `source_name` and `mode` as two independent arguments with independent
defaults, and `main()` passed only the first. So `--source live` produced records stamped
`decision_mode="replay"` — and since Stage 5Z decided binding by the MODE, the freshness gate
stopped binding on exactly the kind of run where it must.

The fix derives the mode from the source and the gate, and refuses a caller who insists on a
different one. These tests hold both halves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import run_live_day_track1 as r1  # noqa: E402
from global_index import track1_explain as tx  # noqa: E402


class ArmedGate:
    """A gate that says it is armed. Nothing else about it is real, and nothing else is read —
    `decision_mode_for` asks `allow_orders` and nothing more. Arming the genuine gate would
    need the environment approval this stage must not set."""
    allow_orders = True
    state = "armed"


# ── the contract ─────────────────────────────────────────────────────────────
def test_replay_runs_as_replay():
    assert r1.decision_mode_for("replay") is tx.REPLAY or \
        r1.decision_mode_for("replay") == tx.REPLAY


@pytest.mark.parametrize("source", ["live", "live-shadow"])
def test_a_live_source_that_is_not_armed_runs_as_shadow_live(source):
    assert r1.decision_mode_for(source, r1.OrderGate(False)) == tx.SHADOW_LIVE
    assert r1.decision_mode_for(source, None) == tx.SHADOW_LIVE


@pytest.mark.parametrize("source", ["live", "live-shadow"])
def test_a_live_source_with_an_armed_gate_runs_as_armed(source):
    assert r1.decision_mode_for(source, ArmedGate()) == tx.ARMED


def test_a_refused_gate_is_not_an_armed_one():
    """`armed_but_refused` is the state the route actually sits in while B1 is open. It must
    resolve to shadow_live — binding — not to armed."""
    gate = r1.OrderGate(True)
    assert gate.state == gate.REFUSED and gate.allow_orders is False
    assert r1.decision_mode_for("live", gate) == tx.SHADOW_LIVE


def test_every_live_mode_binds_freshness_and_replay_does_not():
    """The property the whole fix exists to protect."""
    assert tx.REPLAY not in tx.FRESHNESS_BINDING_MODES
    for source in ("live", "live-shadow"):
        assert r1.decision_mode_for(source, r1.OrderGate(False)) in tx.FRESHNESS_BINDING_MODES
        assert r1.decision_mode_for(source, ArmedGate()) in tx.FRESHNESS_BINDING_MODES


def test_an_unknown_source_is_an_error_not_a_default():
    with pytest.raises(ValueError, match="unknown source"):
        r1.decision_mode_for("something_else")


# ── mismatch is refused, not resolved ────────────────────────────────────────
def test_matching_mode_passes_through():
    assert r1.resolve_decision_mode("replay", None, tx.REPLAY) == tx.REPLAY
    assert r1.resolve_decision_mode("live", None, tx.SHADOW_LIVE) == tx.SHADOW_LIVE
    assert r1.resolve_decision_mode("live", ArmedGate(), tx.ARMED) == tx.ARMED


@pytest.mark.parametrize("source,gate,asked", [
    ("replay", None, tx.SHADOW_LIVE),
    ("replay", None, tx.ARMED),
    ("live", None, tx.REPLAY),
    ("live", ArmedGate(), tx.SHADOW_LIVE),
    ("live-shadow", None, tx.REPLAY),
])
def test_a_mismatched_mode_is_refused_by_name(source, gate, asked):
    with pytest.raises(r1.DecisionModeMismatch, match="runs as"):
        r1.resolve_decision_mode(source, gate, asked)


def test_an_invalid_mode_is_still_a_value_error():
    with pytest.raises(ValueError, match="mode must be one of"):
        r1.resolve_decision_mode("replay", None, "whatever")


def test_omitting_the_mode_derives_it():
    assert r1.resolve_decision_mode("live", None, None) == tx.SHADOW_LIVE


# ── the wiring: run_shadow and main cannot disagree ──────────────────────────
def test_run_shadow_no_longer_defaults_the_mode_independently():
    """The signature itself. A default of `replay` beside a `source_name` argument is the
    shape of the defect, so the absence of that default is worth pinning."""
    import inspect
    sig = inspect.signature(r1.run_shadow)
    assert sig.parameters["mode"].default is None, \
        "mode has an independent default again; it must derive from the source"
    assert "source_name" in sig.parameters


def test_run_shadow_refuses_a_mode_that_contradicts_its_source(tmp_path):
    with pytest.raises(r1.DecisionModeMismatch):
        r1.run_shadow(window="vault2026", source_name="replay",
                      regime_csv="spy_daily_live.csv", out_dir=str(tmp_path),
                      mode=tx.SHADOW_LIVE)


def test_main_derives_the_mode_from_the_source_it_was_given():
    """`main()` must not reach `run_shadow` without a mode. Read from the shipped source
    rather than run, because running `--source live` reaches a source that still refuses."""
    import ast

    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    main_fn = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "main")
    call = next(c for c in ast.walk(main_fn)
                if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "run_shadow")
    kw = {k.arg: k.value for k in call.keywords}
    assert "mode" in kw, "main() calls run_shadow without a mode — that is G1"
    assert isinstance(kw["mode"], ast.Call)
    assert getattr(kw["mode"].func, "id", None) == "decision_mode_for"
    assert ast.unparse(kw["source_name"]) == "a.source"


def test_a_live_run_cannot_be_stamped_replay():
    """The single sentence G1 was about, asserted over every gate state the route can be in."""
    for gate in (None, r1.OrderGate(False), r1.OrderGate(True), ArmedGate()):
        for source in ("live", "live-shadow"):
            assert r1.decision_mode_for(source, gate) != tx.REPLAY


# ── replay behaviour is unchanged ────────────────────────────────────────────
def test_a_replay_run_still_records_replay_and_does_not_cite_the_freshness_gate(tmp_path):
    """Stage 5Z's contract for replay, re-checked through the new derivation path."""
    # `root=` relocates the whole run, which is the supported way; pointing `out_dir` at a
    # bare temp directory is refused by the Stage 5Z root bound and the summary then carries a
    # `refusal` instead of the fields under test.
    summary = r1.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                            root=str(tmp_path))
    ex = summary["explanations"]
    assert ex is not None and "refusal" not in ex, ex
    assert ex["mode"] == tx.REPLAY
    assert ex["freshness_binding"] is False
    assert summary["send_order_calls"] == 0
    assert not (Path("scratch/track1_shadow")
                / f"explanations").joinpath("_stage5ab_probe").exists()


def test_the_record_field_that_said_source_now_says_what_it_holds():
    """It was keyed `source` and held the MODE. Harmless while the two coincided in replay;
    misleading the moment they stopped."""
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    assert '"decision_mode": mode, "regime_csv"' in src
    assert '"source": mode,' not in src


def test_binding_modes_still_refuse_an_admission_while_freshness_failed():
    """Stage 5Z's rule, unchanged by this stage."""
    class _Cand:
        trade_id = "t1"
        sleeve = "roska4_stress"
        instrument = "MNQ"
        entry_time = __import__("pandas").Timestamp("2026-08-24 11:00")
        direction = "SHORT"
        qty = 7
        risk_dollars = 100.0
        entry_price = 1.0
        stop_price = 2.0
        source = "x"

    class _Dec:
        candidate = _Cand()
        verdict = "take"

    for mode in sorted(tx.FRESHNESS_BINDING_MODES):
        with pytest.raises(r1.FreshnessRefused):
            r1.explanations_for([_Dec()], regime_csv="spy_daily_live.csv", data_paths={},
                                fill_law="artifact_all_bars_gappable",
                                freshness_allow=False, mode=mode)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5G — the live-frame gate, closed by moving the touchpoint not the rule
# ══════════════════════════════════════════════════════════════════════════════
def test_the_live_frame_gate_is_released_again():
    from global_index import track1_gates as gates

    ok, detail = gates.live_frame_wiring()
    assert ok is True, detail
    assert "track1_live_source" in detail


def test_b1_is_the_only_blocker_again():
    from global_index import track1_gates as gates

    # Stage 5S added PAPER_SHADOW_EVIDENCE: a MEASURED gate asking whether the shadow
    # route has produced enough judgeable days to justify an order. It cannot be signed,
    # only earned, so it holds until the evidence exists.
    assert {b.id for b in gates.blocking()} == {"B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE"}
    assert gates.self_check() == []
    assert gates.may_enable_orders()[0] is False


def test_the_entry_point_holds_no_live_bar_primitive_of_its_own():
    """The fix, stated structurally. `run_live_day_track1` may CALL the factory; it must not
    be the module that names a broker, because the rule is per module and the guard lives with
    the primitives."""
    import ast

    from global_index import track1_gates as gates

    tree = ast.parse(Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
        elif isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                names.add(n.module.rsplit(".", 1)[-1])
            names |= {a.name for a in n.names}
    assert not (names & gates.LIVE_BAR_NAMES), sorted(names & gates.LIVE_BAR_NAMES)


def test_the_module_that_does_hold_them_imports_the_guard():
    src = Path("global_index/track1_live_source.py").read_text(encoding="utf-8")
    assert "track1_live_frame" in src
    from global_index import track1_live_source as ls
    assert hasattr(ls, "build_bar_provider")


def test_an_unguarded_broker_touchpoint_would_shut_the_gate_again(tmp_path):
    """The detector still bites. Without this the move above could be mistaken for weakening
    the rule — it is not; the rule is unchanged and still refuses the shape it refused."""
    from global_index import track1_gates as gates

    root = tmp_path / "route"
    root.mkdir()
    for m in gates.route_modules():
        (root / f"{m}.py").write_text("x = 1\n", encoding="utf-8")
    (root / "track1_sleeves.py").write_text(
        "from global_index.ibkr_broker import IBKRBroker\n"
        "def provider():\n    return IBKRBroker(host='h', port=1, client_id=1)\n",
        encoding="utf-8")
    ok, detail = gates.live_frame_wiring(root)
    assert ok is False and "without the splice guard" in detail
    assert "IBKRBroker" in detail


def test_the_factory_delegates_and_opens_nothing():
    """`none` is the default so a manual run cannot dial out; `ibkr` is exercised with a fake
    class, so no broker module is imported and no connection is attempted."""
    from global_index import track1_live_source as ls

    assert r1.build_bar_provider is ls.build_bar_provider
    assert r1.build_bar_provider("none") == (None, None)

    class FakeBroker:
        def __init__(self, **kw):
            self.kw = kw
            self.connected = False

        def connect(self):
            self.connected = True

    provider, broker = r1.build_bar_provider("ibkr", broker_cls=FakeBroker)
    assert isinstance(provider, ls.IBKRBarProvider)
    assert broker.connected is True
    assert sorted(broker.kw) == ["bar_duration", "client_id", "host", "port"]
    assert "ib_insync" not in sys.modules
    assert "global_index.ibkr_broker" not in sys.modules


def test_an_unknown_provider_kind_is_refused_by_name():
    from global_index import track1_live_source as ls

    with pytest.raises(ls.LiveSourceRefused) as e:
        r1.build_bar_provider("carrier_pigeon")
    assert e.value.code == ls.UNKNOWN_BAR_PROVIDER


def test_a_live_shadow_slot_still_refuses_before_any_provider_when_the_ledger_is_off(monkeypatch):
    """Order of refusals: the ledger check comes first, so a slot that could not record its own
    run never reaches a broker at all."""
    import importlib

    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    import global_index.window_ledger as wl
    importlib.reload(wl)
    entry = importlib.reload(r1)
    try:
        assert wl.enabled() is False
        with pytest.raises(entry.ShadowRefused) as e:
            entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                                    now_et="2026-08-24 10:00")
        assert e.value.code == entry.LEDGER_NOT_CONFIGURED
    finally:
        importlib.reload(wl)
        importlib.reload(r1)
