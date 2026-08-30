"""scratch/test_track1_stage5i_live_shadow_evidence_wiring_20260823.py — the Stage 5I gate.

    python -m pytest scratch/test_track1_stage5i_live_shadow_evidence_wiring_20260823.py -q

Offline. No scheduler started, no real IBKR connection, no order, no dashboard write. Every
broker is a fake class; the ledger and any explanation output go to pytest's temp directory.

Stage 5H0 found that a provider-only fix would have produced a shadow route deciding without
caps, without freshness and without an audit trail, filing its evidence under `route=legacy`.
This suite holds the four gaps closed:

    G-A  the slot runs the same freshness / caps / admission / explain machinery as the replay
    G-B  every ledger row carries route=track1_candidate
    G-C  --bar-provider is parsed, built and passed
    G-D  the broker is released in a finally
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import track1_gates as g  # noqa: E402
from global_index import track1_live_source as S  # noqa: E402

ET = "America/New_York"
DAY = pd.Timestamp("2026-08-24")
PREV = pd.Timestamp("2026-08-21")


class FakeBroker:
    """Counts its own lifecycle. Not a broker — it never speaks to anything."""
    made = []

    def __init__(self, **kw):
        self.kw = kw
        self.connects = 0
        self.disconnects = 0
        FakeBroker.made.append(self)

    def connect(self):
        self.connects += 1

    def disconnect(self):
        self.disconnects += 1

    def fetch_bars(self, inst, through):
        return None


def _frame(day, closes, start="09:30"):
    h, m = int(start[:2]), int(start[3:])
    idx = pd.date_range(pd.Timestamp(day) + pd.Timedelta(hours=h, minutes=m),
                        periods=len(closes), freq="1min", tz=ET)
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c + 0.05, "low": c - 0.05, "close": c,
                         "volume": 1000.0}, index=idx)


def frames():
    frozen, live = {}, {}
    for inst in ("MES", "MNQ"):
        frozen[inst] = pd.concat([_frame(PREV, np.linspace(100.0, 97.2, 396)),
                                  _frame(DAY, np.linspace(98.0, 97.6, 31)).iloc[:25]])
        tail = _frame(DAY, np.linspace(98.0, 97.6, 31)).iloc[25:].copy()
        tail.index = pd.DatetimeIndex(tail.index).tz_convert(ET).tz_localize(None)
        live[inst] = tail
    return frozen, live


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    monkeypatch.setenv("RAITS_ROUTE", "track1_candidate")
    import global_index.window_ledger as wl
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    yield d, wl, entry
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    monkeypatch.delenv("RAITS_ROUTE", raising=False)
    importlib.reload(wl)
    importlib.reload(entry)


def _slot_argv():
    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_track1_body":
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_run"
                        and call.args and isinstance(call.args[0], ast.List)):
                    return [e.value if isinstance(e, ast.Constant) else ast.unparse(e)
                            for e in call.args[0].elts]
    raise AssertionError("no _run([...]) inside _track1_body")


# ══════════════════════════════════════════════════════════════════════════════
# G-C — the provider selector
# ══════════════════════════════════════════════════════════════════════════════
def test_the_entry_point_parses_a_bar_provider_flag():
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    flags = [l.split('"')[1] for l in src.split("\n")
             if "ap.add_argument(" in l and '"--' in l]
    assert "--bar-provider" in flags, flags
    assert 'choices=["none", "ibkr"]' in src
    assert 'default="none"' in src, "the default must not be able to open IBKR"


def test_the_scheduler_slot_passes_ibkr_and_still_asks_for_no_orders():
    """Re-pointed by Stage 5M-B, which made `--bar-provider` a per-SLOT value.

    The old version parsed the source of `_track1_body` and required the literal "ibkr". That
    literal is now the variable `provider`, so source-parsing could only report the name of a
    variable. Reading the argv the scheduler actually builds is both what this test was always
    about and immune to the next refactor of how the value gets there.

    The sleeves this stage wired — Calm and Stress — must still be launched with `ibkr`. The
    swing slots added in 5M-B are deliberately `none` and are checked in the 5M-B suite.
    """
    import logging as _lg
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    _lg.disable(_lg.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append((label, list(args))) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True)
        for j in sched.get_jobs():
            if j.id.startswith("track1_calm") or j.id.startswith("track1_stress"):
                j.func()
    finally:
        rs._run = orig
        _lg.disable(_lg.NOTSET)

    assert seen, "no Calm or Stress slot ran — nothing was captured"
    for label, argv in seen:
        assert argv[argv.index("--bar-provider") + 1] == "ibkr", label
        assert argv[argv.index("--source") + 1] == "live-shadow", label
        for nope in ("--allow-orders", "--port", "--window"):
            assert nope not in argv, (label, nope)


def test_main_builds_the_provider_and_hands_it_to_the_slot():
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    main = src[src.index("def main("):]
    branch = main[main.index('if a.source == "live-shadow"'):]
    assert "build_bar_provider(a.bar_provider)" in branch
    assert "provider=provider" in branch


def test_a_manual_run_defaults_to_no_provider_and_refuses(ledger):
    """The default must stay safe: a hand-run slot refuses rather than dialling out."""
    d, wl, entry = ledger
    rc = entry.main(["--source", "live-shadow", "--sleeve", "roska4_calm",
                     "--slot-id", "TRACK1_CALM_1000", "--regime-csv", "spy_daily_live.csv"])
    assert rc == 0
    row = [r for r in wl.read_day(str(DAY.date()) if False else
                                  str(pd.Timestamp.now(tz=ET).date()))
           if r["event"] == "slot_observed"]
    rows = [json.loads(l) for f in d.glob("*.jsonl")
            for l in f.read_text(encoding="utf-8").splitlines()]
    obs = [r for r in rows if r["event"] == "slot_observed"]
    assert obs and obs[-1]["reason"] == entry.NO_BAR_PROVIDER
    assert "ib_insync" not in sys.modules


def test_an_unknown_provider_kind_is_refused_by_name():
    with pytest.raises(S.LiveSourceRefused) as e:
        S.build_bar_provider("carrier_pigeon")
    assert e.value.code == S.UNKNOWN_BAR_PROVIDER


# ══════════════════════════════════════════════════════════════════════════════
# G-D — the broker is released
# ══════════════════════════════════════════════════════════════════════════════
def test_a_fake_broker_is_connected_once_and_disconnected_once(ledger, monkeypatch):
    d, wl, entry = ledger
    FakeBroker.made.clear()
    monkeypatch.setattr(entry, "build_bar_provider",
                        lambda kind, **kw: S.build_bar_provider(kind, broker_cls=FakeBroker, **kw))
    rc = entry.main(["--source", "live-shadow", "--sleeve", "roska4_calm",
                     "--slot-id", "TRACK1_CALM_1000", "--bar-provider", "ibkr",
                     "--regime-csv", "spy_daily_live.csv"])
    assert rc == 0
    assert len(FakeBroker.made) == 1
    b = FakeBroker.made[0]
    assert b.connects == 1 and b.disconnects == 1, (b.connects, b.disconnects)
    assert "ib_insync" not in sys.modules


def test_the_finally_path_exists_in_source():
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    branch = src[src.index('if a.source == "live-shadow"'):]
    branch = branch[:branch.index("send_order calls")]
    assert "finally:" in branch and "disconnect" in branch


def test_the_ledger_is_required_before_a_broker_is_built(monkeypatch, tmp_path):
    """Order matters: a slot that could not record its run must not open a connection to
    discover that."""
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    import global_index.window_ledger as wl
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    FakeBroker.made.clear()
    monkeypatch.setattr(entry, "build_bar_provider",
                        lambda kind, **kw: S.build_bar_provider(kind, broker_cls=FakeBroker, **kw))
    try:
        rc = entry.main(["--source", "live-shadow", "--sleeve", "roska4_calm",
                         "--slot-id", "TRACK1_CALM_1000", "--bar-provider", "ibkr",
                         "--regime-csv", "spy_daily_live.csv"])
        assert rc == 2
        assert FakeBroker.made == [], "a broker was built despite no ledger"
    finally:
        importlib.reload(wl)
        importlib.reload(entry)


# ══════════════════════════════════════════════════════════════════════════════
# G-B — route identity on every row
# ══════════════════════════════════════════════════════════════════════════════
def test_every_ledger_row_carries_the_track1_route(ledger):
    d, wl, entry = ledger
    frozen, live = frames()
    entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                            now_et=pd.Timestamp(f"{DAY.date()} 10:00", tz=ET),
                            provider=S.FrameBarProvider(live), frozen_frames=frozen, root=str(d.parent))
    rows = [json.loads(l) for f in d.glob("*.jsonl")
            for l in f.read_text(encoding="utf-8").splitlines()]
    assert {r["event"] for r in rows} == {"window_open", "slot_observed", "window_closed"}
    for r in rows:
        assert r["route"] == "track1_candidate", (r["event"], r["route"])
    assert not [r for r in rows if r["route"] == "legacy"]


def test_the_scheduler_stamps_track1_children_and_leaves_legacy_alone(monkeypatch):
    from global_index import run_scheduler as rs
    from global_index import track1_slots as t1

    seen = {}

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.delenv("RAITS_ROUTE", raising=False)
    monkeypatch.setattr(rs.subprocess, "run",
                        lambda args, **kw: (seen.update(env=dict(kw.get("env") or {})), _R())[1])
    rs._run(["python", "-m", "global_index.run_live_day"], label="LIVE_DAY_1410", dry_run=False)
    assert seen["env"]["RAITS_ROUTE"] == "legacy"

    rs._run(["python", "-m", "global_index.run_live_day_track1"], label="TRACK1_CALM_1000",
            dry_run=False, route=t1.EVENT_ROUTE_VALUE)
    assert seen["env"]["RAITS_ROUTE"] == "track1_candidate"


def test_an_operator_export_still_wins_for_legacy(monkeypatch):
    """`setdefault` semantics for legacy are unchanged — only the Track 1 caller is explicit."""
    from global_index import run_scheduler as rs

    seen = {}

    class _R:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setenv("RAITS_ROUTE", "operator_set")
    monkeypatch.setattr(rs.subprocess, "run",
                        lambda args, **kw: (seen.update(env=dict(kw.get("env") or {})), _R())[1])
    rs._run(["python", "-m", "global_index.run_live_day"], label="LIVE_DAY_1410", dry_run=False)
    assert seen["env"]["RAITS_ROUTE"] == "operator_set"


# ══════════════════════════════════════════════════════════════════════════════
# G-A — the slot runs the route's own decision machinery
# ══════════════════════════════════════════════════════════════════════════════
def _trace_slot(entry, sleeve, slot_id, **kw):
    track = str(Path("global_index").resolve()).lower()
    seen = set()

    def tracer(fr, ev, _a):
        if ev == "call":
            fn = fr.f_code.co_filename.lower()
            if fn.startswith(track):
                seen.add((Path(fn).stem, fr.f_code.co_name))
        return None

    sys.settrace(tracer)
    try:
        res = entry.observe_live_slot(sleeve, slot_id, **kw)
    finally:
        sys.settrace(None)
    return res, seen


def test_the_slot_evaluates_freshness_builds_the_guard_and_runs_admission(ledger):
    """Traced, not asserted. Before Stage 5I none of these was reached from a live slot."""
    d, wl, entry = ledger
    frozen, live = frames()
    res, seen = _trace_slot(entry, "roska4_calm", "TRACK1_CALM_1000",
                            now_et=pd.Timestamp(f"{DAY.date()} 10:00", tz=ET),
                            provider=S.FrameBarProvider(live), frozen_frames=frozen, root=str(d.parent))
    for mod, fn in (("track1_freshness", "evaluate"),
                    ("track1_signal_layer", "make_guard"),
                    ("track1_signal_layer", "run_candidates"),
                    ("run_live_day_track1", "emit_explanations")):
        assert (mod, fn) in seen, f"{mod}.{fn} was not reached by the slot"
    assert res["freshness_allow"] is not None, "freshness was not evaluated"


def test_the_slot_reports_what_the_machinery_decided(ledger):
    d, wl, entry = ledger
    frozen, live = frames()
    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                                  now_et=pd.Timestamp(f"{DAY.date()} 10:00", tz=ET),
                                  provider=S.FrameBarProvider(live), frozen_frames=frozen, root=str(d.parent))
    for k in ("candidates", "freshness_allow", "accepted", "rejected", "explained"):
        assert k in res, k
    row = [json.loads(l) for f in d.glob("*.jsonl")
           for l in f.read_text(encoding="utf-8").splitlines()
           if json.loads(l)["event"] == "slot_observed"][0]
    for k in ("candidates", "freshness_allow", "accepted", "rejected"):
        assert k in row, k


def test_freshness_binds_so_an_admission_cannot_be_recorded_as_decided(ledger):
    """The safe direction, end to end. The route admits two candidates; the freshness gate
    refuses; the slot records a NAMED refusal and the window stays incomplete. Marking such a
    slot `decided` would let precondition 5 go green on inputs the route itself refused."""
    d, wl, entry = ledger
    sys.path.insert(0, "scratch")
    m = importlib.import_module("test_track1_stage5e_live_source_20260823")
    frozen, live = m.frames()
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), labels=m.labels(),
                             frozen_frames=frozen)
    assert len(src.candidates(m.NOW)) == 2, "the fixture must produce candidates to bind on"

    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000", now_et=m.NOW,
                                  provider=S.FrameBarProvider(live), frozen_frames=frozen,
                                  live_source=src, root=str(d.parent))
    assert res["freshness_allow"] is False
    assert res["accepted"] == 2, "the caps admitted them, which is what makes this binding"
    assert res["decided"] is False
    assert res["reason"] == entry.FRESHNESS_REFUSED
    assert "freshness gate refused" in res["detail"]

    day = str(pd.Timestamp(m.DAY).date())
    st = wl.status(wl.read_day(day), "roska4_calm", day)
    assert st["outcome"] == "incomplete" and st["observed_slots"] == 0


def test_no_order_can_be_sent_from_the_slot(ledger):
    d, wl, entry = ledger
    b = entry.NoOrderBroker()
    for meth in ("send_order", "cancel_order"):
        with pytest.raises(RuntimeError):
            getattr(b, meth)(None)

    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    calls = {getattr(c.func, "id", None) or getattr(c.func, "attr", "")
             for c in ast.walk(node) if isinstance(c, ast.Call)}
    assert "send_order" not in calls


# ══════════════════════════════════════════════════════════════════════════════
# preserved guarantees
# ══════════════════════════════════════════════════════════════════════════════
def test_the_gate_and_the_order_refusal_are_unchanged():
    assert g.live_frame_wiring()[0] is True
    assert {b.id for b in g.blocking()} == {"B1_broker_account_or_legacy_retirement"}
    assert g.self_check() == []
    assert g.may_enable_orders()[0] is False
    assert not Path(g.CONFIRMATION_PATH).exists()


def test_the_scheduler_shape_is_unchanged():
    from global_index import run_scheduler as rs
    from global_index import track1_slots as ts

    logging.disable(logging.CRITICAL)
    try:
        off = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                               track1_shadow=False).get_jobs()}
        on = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                              track1_shadow=True).get_jobs()}
    finally:
        logging.disable(logging.NOTSET)
    # Derived, not pinned. Stage 5M-B added 23 swing slots and the literal 84 turned red for
    # an intended change; the property is that the flag adds exactly the Track 1 slots and
    # displaces exactly the one stop-repair sweep inside the Stress window.
    assert len(off) == 60
    assert off - on == {"stop_repair_1220"}, off - on
    assert on - off == {s.id.lower() for s in ts.TRACK1_SLOTS}, sorted(on - off)
    assert len([i for i in on if i.startswith("track1_")]) == len(ts.TRACK1_SLOTS)
    assert len([i for i in on if i.startswith("live_day")]) == 23
    assert (off - on) == {"stop_repair_1220"}
    assert ts.parity_report(track1_shadow=False)["in_parity"]
    assert ts.parity_report(track1_shadow=True)["in_parity"]


def test_replay_still_writes_no_coverage_and_no_orders(ledger, tmp_path):
    d, wl, entry = ledger
    summary = entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                               now_et=pd.Timestamp("2026-08-21 11:00", tz=ET),
                               root=str(tmp_path))
    assert "not driven" in summary["window_ledger"]
    assert summary["send_order_calls"] == 0
    ex = summary["explanations"]
    assert ex and ex.get("mode") == "replay" and ex.get("freshness_binding") is False


def test_no_repo_route_state_was_created():
    for f in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
              "live_positions.track1.json", "runner.track1.pid",
              "global_index/replay_checkpoint.track1.json"):
        assert not Path(f).exists(), f
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None
