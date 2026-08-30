"""scratch/test_track1_stage5d_shadow_live_wiring_20260823.py — the Stage 5D gate.

    python -m pytest scratch/test_track1_stage5d_shadow_live_wiring_20260823.py -q

Offline. No scheduler started, no IBKR, no order, no dashboard write. The ledger directory and
the checkpoint path are pointed at pytest's temporary directory throughout; the repo's own
route state is asserted untouched at the end.

What Stage 5D fixed, and what it did not
-----------------------------------------
Stage 5C measured that the Track 1 slots passed only `--regime-csv`, so the entry point took
its defaults and every one of the 25 slots re-ran the measured window `vault2026`. Both
`record_window_observation` and `track1_bootstrap.write` had zero callers, so no coverage and
no checkpoint could ever be produced. Stage 5D wired that half.

It did NOT implement the live candidate source. So the honest end state is: the plumbing can
reach a complete window and write a checkpoint — proved here with an injected stub source — and
a real slot today records `decided=false, reason=live_source_not_ready` and closes the window
INCOMPLETE. These tests pin both directions, because a suite that only proved the failure would
not show the mechanism works, and one that only proved the stub path would claim readiness the
route does not have.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import track1_gates as g  # noqa: E402
from global_index import track1_intraday as intra  # noqa: E402
from global_index import track1_live_source as S  # noqa: E402

ET = "America/New_York"
DAY, PREV = "2026-08-24", "2026-08-21"

LEGACY_FILES = ["live_positions.json", "global_index/live_state_data.js",
                "global_index/replay_checkpoint.json", "trade_log.jsonl"]


#: When this module was imported, i.e. before any test in it ran. Stage 5ZK. The live route
#: writes `replay_checkpoint.track1.json` and `live_positions.track1.json` in one call every
#: day a window completes — first observed 2026-08-25 15:56:19 ET — so asserting their ABSENCE
#: forbids the running system from doing what these very tests exercise. An mtime older than
#: this process says the thing actually being guarded: no test in this run touched it.
_IMPORTED_AT = __import__("time").time()


def _assert_not_written_by_this_run(name: str) -> None:
    p = Path(name)
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — every fixture must be under tmp_path")

def _fingerprint(paths):
    out = {}
    for p in paths:
        f = Path(p)
        out[p] = (f.exists(), f.stat().st_mtime if f.exists() else None,
                  f.stat().st_size if f.exists() else None)
    return out


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A live ledger directory, and freshly reloaded modules that see it."""
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    import global_index.window_ledger as wl
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    yield d, wl, entry
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    importlib.reload(wl)
    importlib.reload(entry)


class StubLiveSource:
    """Stands in for the source precondition 2b is waiting for. Returns no candidates, which is
    a legitimate live answer — the point is that it ANSWERS instead of raising."""

    def __init__(self):
        self.asked = 0

    def candidates(self, key):
        self.asked += 1
        return []

    def early_exit_valuer(self, key):
        return lambda *a, **k: None


def _frames(insts=("MES", "MNQ")):
    frozen, live = {}, {}
    for inst in insts:
        frozen[inst] = pd.concat([intra.synth_bars(PREV, "09:30", "16:00", tz=ET),
                                  intra.synth_bars(DAY, "09:30", "09:55", tz=ET)])
        tail = intra.synth_bars(DAY, "10:00", "10:00", tz=ET)
        tail.index = pd.DatetimeIndex(tail.index).tz_convert(ET).tz_localize(None)
        live[inst] = tail
    return frozen, live


# ══════════════════════════════════════════════════════════════════════════════
# 1. the slot argv — the defect Stage 5C measured
# ══════════════════════════════════════════════════════════════════════════════
def _slot_argv() -> list:
    """The argv literal the Track 1 slot builds, read by PARSING the scheduler.

    Substring-matching the function body is what the first version of this test did, and it
    failed on the comment explaining the fix — the words `--source replay --window vault2026`
    appear there precisely because they describe the defect. A comment is not an argument.
    """
    import ast

    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_track1_body"):
            continue
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", None) == "_run" and call.args):
                continue
            flat = _flatten_argv(call.args[0])
            if flat is not None:
                return flat
    raise AssertionError("no _run([...]) call found inside _track1_body")


def _flatten_argv(node):
    """The argv list, whether it is one literal or several joined with `+`.

    Stage 5ZX made the Track 1 argv a concatenation, because `--phase` belongs only to a slot
    that HAS a phase and an unsplit sleeve's command line must stay exactly what it was. The
    extractor read the first argument only when it was a single list literal, so it stopped
    finding the call at all — and reported that as "no _run call", which reads like the wiring
    was removed rather than reshaped.

    A conditional branch is rendered as its source text, so the assertions below still see
    every flag the argv can carry, and a flag REMOVED from the concatenation still disappears
    from what they read. Widening the reader does not loosen them.
    """
    import ast as _ast

    if isinstance(node, _ast.List):
        return [el.value if isinstance(el, _ast.Constant) else _ast.unparse(el)
                for el in node.elts]
    if isinstance(node, _ast.BinOp) and isinstance(node.op, _ast.Add):
        left, right = _flatten_argv(node.left), _flatten_argv(node.right)
        if left is None or right is None:
            return None
        return left + right
    # A parenthesised conditional such as `(["--phase", phase] if phase else [])`: both
    # branches are reported, so a reader asking "can this argv carry --allow-orders" gets a
    # truthful yes/no rather than an answer that depends on which branch was taken.
    if isinstance(node, _ast.IfExp):
        a, b = _flatten_argv(node.body), _flatten_argv(node.orelse)
        if a is None and b is None:
            return None
        return (a or []) + (b or [])
    return None


def test_the_slot_now_asks_for_live_shadow_and_not_for_a_replay():
    argv = _slot_argv()
    assert "--source" in argv and argv[argv.index("--source") + 1] == "live-shadow"
    assert "--sleeve" in argv and "--slot-id" in argv
    assert "--window" not in argv, f"the slot names a measured window: {argv}"
    assert not any("vault" in str(x) for x in argv), argv


def test_the_slot_still_cannot_ask_for_orders():
    argv = _slot_argv()
    assert "--allow-orders" not in argv
    assert "--port" not in argv
    assert "global_index.run_live_day_track1" in argv


def test_live_shadow_is_a_real_choice_on_the_entry_point():
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    assert 'choices=["replay", "live", "live-shadow"]' in src


def test_turning_shadow_on_still_leaves_legacy_alone():
    """The slot argv changed; the legacy schedule must not have."""
    import logging
    from global_index import run_scheduler as rs
    logging.disable(logging.CRITICAL)
    try:
        off = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                               track1_shadow=False).get_jobs()}
        on = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                              track1_shadow=True).get_jobs()}
    finally:
        logging.disable(logging.NOTSET)
    # The subject is "legacy must not change", and comparing two totals never said that.
    # `on - off` being exactly the Track 1 slot ids does, and it survives a new sleeve —
    # Stage 5M-B added 23 and the old literal 84 turned red for an intended change.
    from global_index import track1_slots as _t1
    assert len(off) == 60
    assert off - on == {"stop_repair_1220"}, off - on
    assert on - off == {s.id.lower() for s in _t1.TRACK1_SLOTS}, sorted(on - off)
    assert (off - on) == {"stop_repair_1220"}
    assert len([i for i in on if i.startswith("live_day")]) == 23


# ══════════════════════════════════════════════════════════════════════════════
# 2. fail closed
# ══════════════════════════════════════════════════════════════════════════════
def test_live_shadow_refuses_when_the_ledger_is_not_configured(monkeypatch):
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    import global_index.window_ledger as wl
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    assert wl.enabled() is False
    with pytest.raises(entry.ShadowRefused) as e:
        # No redirect needed: this refuses before anything is written, which is the point.
        entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                                now_et=pd.Timestamp(f"{DAY} 10:00", tz=ET))
    assert e.value.code == entry.LEDGER_NOT_CONFIGURED


def test_a_slot_with_no_bar_provider_records_the_refusal_rather_than_vanishing(ledger):
    d, wl, entry = ledger
    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                                  now_et=pd.Timestamp(f"{DAY} 10:00", tz=ET), root=str(d.parent))
    assert res["decided"] is False and res["reason"] == entry.NO_BAR_PROVIDER
    rows = wl.read_day(DAY)
    assert [r["event"] for r in rows] == ["window_open", "slot_observed", "window_closed"]
    st = wl.status(rows, "roska4_calm", DAY)
    assert st["outcome"] == "incomplete" and st["observed_slots"] == 0


def test_the_calm_window_decides_and_the_stress_window_answers(ledger):
    """Superseded by Stage 5E, and re-pointed rather than deleted.

    When this was written the Calm slot recorded `live_source_not_ready`, because
    `load_source("live").candidates()` raised. Stage 5E built the Calm A live source, so that
    slot now DECIDES — asserting the old reason would have pinned the gap in place. What is
    still genuinely not ready is the Stress window, whose rule lives in scratch, and that is
    what the second half checks: 24 of the 25 Track 1 slots sit there.
    """
    from global_index import track1_live_source as LS

    d, wl, entry = ledger
    frozen, live = _frames()
    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                                  now_et=pd.Timestamp(f"{DAY} 10:00", tz=ET),
                                  provider=S.FrameBarProvider(live), frozen_frames=frozen, root=str(d.parent))
    assert res["decided"] is True, res
    assert res["reason"] == entry.DECIDED
    assert res["candidates"] is not None, "the rule ran but reported no candidate count"

    # Stage 5F promoted the Stress rule, so this half was re-pointed a second time. What it
    # now asserts is that the window ANSWERS rather than refusing as not-in-package; what is
    # still untested anywhere is a broker provider, and no test can assert that offline.
    src = LS.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), frozen_frames=frozen)
    try:
        assert isinstance(src.candidates(pd.Timestamp(f"{DAY} 11:00", tz=ET)), list)
    except LS.LiveSourceRefused as exc:
        assert exc.code != LS.STRESS_RULE_NOT_IN_PACKAGE, exc.code


# ══════════════════════════════════════════════════════════════════════════════
# 3. the mechanism can reach green — with the source stubbed, and only then
# ══════════════════════════════════════════════════════════════════════════════
def test_an_injected_source_lets_the_window_complete(ledger):
    """The other direction. Without this the suite would only prove the route fails."""
    d, wl, entry = ledger
    frozen, live = _frames()
    stub = StubLiveSource()
    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000",
                                  now_et=pd.Timestamp(f"{DAY} 10:00", tz=ET),
                                  provider=S.FrameBarProvider(live), frozen_frames=frozen,
                                  live_source=stub, root=str(d.parent))
    assert res["decided"] is True and res["reason"] == entry.DECIDED
    assert stub.asked == 1, "the slot never asked the source for candidates"

    rows = wl.read_day(DAY)
    st = wl.status(rows, "roska4_calm", DAY)
    assert st["outcome"] == "complete", st
    assert st["observed_slots"] == st["expected_slots"] == 1
    assert res["closed"]["slots_decided"] == 1


def test_a_stress_window_completes_only_when_every_slot_decided(ledger):
    """24 slots, and the count that matters is how many DECIDED, not how many ran."""
    d, wl, entry = ledger
    from global_index import track1_slots as t1

    ids = [s.id for s in t1.TRACK1_SLOTS if s.sleeve == "roska4_stress"]
    assert len(ids) == 24, len(ids)

    frozen, live = {}, {}
    for inst in ("MNQ",):
        frozen[inst] = pd.concat([intra.synth_bars(PREV, "09:30", "16:00", tz=ET),
                                  intra.synth_bars(DAY, "09:30", "10:30", tz=ET)])
        tail = intra.synth_bars(DAY, "10:35", "12:30", tz=ET)
        tail.index = pd.DatetimeIndex(tail.index).tz_convert(ET).tz_localize(None)
        live[inst] = tail

    stub = StubLiveSource()
    for i, sid in enumerate(ids):
        hh, mm = int(sid[-4:-2]), int(sid[-2:])
        entry.observe_live_slot(
            "roska4_stress", sid, now_et=pd.Timestamp(f"{DAY} {hh:02d}:{mm:02d}", tz=ET),
            provider=S.FrameBarProvider(live), frozen_frames=frozen, live_source=stub,
            root=str(d.parent),
        )
        if i < len(ids) - 1:
            st = wl.status(wl.read_day(DAY), "roska4_stress", DAY)
            assert st["outcome"] == "unobserved", "the window closed before its last slot"

    st = wl.status(wl.read_day(DAY), "roska4_stress", DAY)
    assert st["outcome"] == "complete", st
    assert st["observed_slots"] == 24


def test_one_undecided_slot_keeps_the_window_incomplete(ledger):
    """The property that stops precondition 5 going green on a route that cannot trade."""
    d, wl, entry = ledger
    from global_index import track1_slots as t1

    ids = [s.id for s in t1.TRACK1_SLOTS if s.sleeve == "roska4_stress"]
    frozen = {"MNQ": pd.concat([intra.synth_bars(PREV, "09:30", "16:00", tz=ET),
                                intra.synth_bars(DAY, "09:30", "10:30", tz=ET)])}
    tail = intra.synth_bars(DAY, "10:35", "12:30", tz=ET)
    tail.index = pd.DatetimeIndex(tail.index).tz_convert(ET).tz_localize(None)
    live = {"MNQ": tail}
    stub = StubLiveSource()

    for i, sid in enumerate(ids):
        hh, mm = int(sid[-4:-2]), int(sid[-2:])
        kw = dict(now_et=pd.Timestamp(f"{DAY} {hh:02d}:{mm:02d}", tz=ET),
                  frozen_frames=frozen, live_source=stub)
        if i == 7:
            entry.observe_live_slot("roska4_stress", sid, **kw, root=str(d.parent))          # no provider: undecided
        else:
            entry.observe_live_slot("roska4_stress", sid,
                                    provider=S.FrameBarProvider(live), **kw, root=str(d.parent))

    st = wl.status(wl.read_day(DAY), "roska4_stress", DAY)
    assert st["outcome"] == "incomplete", st
    assert st["observed_slots"] == 23


# ══════════════════════════════════════════════════════════════════════════════
# 4. the checkpoint
# ══════════════════════════════════════════════════════════════════════════════
def test_the_checkpoint_writer_now_has_a_caller():
    """`track1_bootstrap.write` had zero callers before Stage 5D — the format was built and
    tested and nothing ever produced one."""
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    assert "def write_route_checkpoint(" in src
    assert "boot.write(" in src
    main = src[src.index("def main("):]
    assert "write_route_checkpoint(" in main, "main() never reaches the checkpoint writer"


def test_a_checkpoint_is_written_and_accepted_after_a_complete_window(ledger, tmp_path):
    d, wl, entry = ledger
    from global_index import track1_bootstrap as boot
    from global_index import track1_normal_r4 as NR

    ck = tmp_path / "replay_checkpoint.track1.json"
    paths = {}
    frames = {}
    idx = pd.date_range(f"{DAY} 09:30", periods=20, freq="5min", tz=ET)
    for inst in ("MES", "MNQ", "MYM", "M2K", "MNKD"):
        f = tmp_path / f"{inst}.parquet"
        f.write_bytes(inst.encode())
        paths[inst] = str(f)
        frames[inst] = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                                     "volume": 1.0}, index=idx)

    out = entry.write_route_checkpoint("roska4_calm",
                                       now_et=pd.Timestamp(f"{DAY} 10:00", tz=ET),
                                       regime_csv="spy_daily_live.csv", data_paths=paths,
                                       frames=frames, path=str(ck),
                                       book_path=str(tmp_path / "book.json"))
    assert ck.exists() and out["path"] == str(ck)

    res = boot.accepts(str(ck), sleeve="roska4_swing", inst="MES", frame=frames["MES"],
                       regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                       fill_law=NR.NormalR4Params().fill_law)
    assert bool(res) is True, getattr(res, "detail", "")
    # Stage 5ZK: mtime, not absence — see `_assert_not_written_by_this_run`.
    _assert_not_written_by_this_run("global_index/replay_checkpoint.track1.json")


def test_main_writes_no_checkpoint_when_the_window_did_not_complete():
    """Read from main() rather than run it, because running it would write the real file."""
    src = Path("global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    main = src[src.index("def main("):]
    seg = main[main.index("if res[\"closed\"]"):]
    assert "slots_decided" in seg and ">=" in seg, "the checkpoint is not gated on completeness"
    assert "NOT written" in seg, "an incomplete window says nothing about why it wrote nothing"


# ══════════════════════════════════════════════════════════════════════════════
# 5. replay must stay unable to testify
# ══════════════════════════════════════════════════════════════════════════════
def test_a_replay_writes_no_coverage_even_with_the_ledger_switched_on(ledger):
    """The distinction the whole ledger exists for. A replay of a measured window knows the
    days a trade existed; it cannot know whether anyone watched today."""
    d, wl, entry = ledger
    assert wl.enabled() is True
    summary = entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                               now_et=pd.Timestamp("2026-08-21 11:00", tz=ET),
                               out_dir=str(d.parent / "shadow"))
    assert "not driven" in summary["window_ledger"], summary["window_ledger"]
    assert wl.files() == [], "a replay wrote window coverage"
    assert summary["send_order_calls"] == 0, sorted(summary)


# ══════════════════════════════════════════════════════════════════════════════
# 6. nothing else moved
# ══════════════════════════════════════════════════════════════════════════════
def test_no_legacy_file_was_touched_by_any_of_this():
    before = _fingerprint(LEGACY_FILES)
    from global_index import run_scheduler as rs  # noqa: F401
    after = _fingerprint(LEGACY_FILES)
    assert before == after


def test_orders_are_still_impossible(monkeypatch):
    from global_index import run_live_day_track1 as entry
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    # Property, not a count. This line used to pin the blocker list to exactly one element,
    # which made it red the moment a MEASURED gate legitimately re-shut — and a measured gate
    # re-shutting is the mechanism working, not a regression. What must hold is that orders are
    # impossible and that B1 is among the reasons; an extra blocker is allowed only if it is
    # genuinely holding.
    _blockers = {b.id for b in g.blocking()}
    assert "B1_broker_account_or_legacy_retirement" in _blockers, _blockers
    assert g.may_enable_orders()[0] is False
    for _extra in _blockers - {"B1_broker_account_or_legacy_retirement"}:
        _b = g.BLOCKERS[_extra]
        assert _b.blocks_orders and not _b.released(g.NO_CONFIRMATIONS), _extra
    # Derived, not a literal: B1 plus whichever MEASURED gates are shut right now.
    # Written this way in Stage 5S because the literal had already been rewritten
    # twice by a measured gate opening and closing, and chasing that is not a test.
    _measured_shut = {b.id for b in g.BLOCKERS.values()
                      if b.released_by_measurement and not b.measure()[0]}
    assert _blockers == {"B1_broker_account_or_legacy_retirement"} | _measured_shut, _blockers
    assert g.self_check() == []
    gate = entry.OrderGate(True)
    assert gate.allow_orders is False
    assert not Path(g.CONFIRMATION_PATH).exists()


def test_the_route_state_this_stage_must_not_create_is_absent():
    for f in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
              "runner.track1.pid"):
        assert not Path(f).exists(), f
    # Stage 5ZK: the two route artefacts came off the absence list. The live close
    # writes both, in one call, every day a window completes.
    for f in ("live_positions.track1.json",
              "global_index/replay_checkpoint.track1.json"):
        _assert_not_written_by_this_run(f)


# ══════════════════════════════════════════════════════════════════════════════
# 7. the runbook no longer says starting fixes 5 and 6
# ══════════════════════════════════════════════════════════════════════════════
def test_the_runbook_retracts_the_starting_is_what_fixes_them_claim():
    txt = Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md").read_text(encoding="utf-8")
    idx = txt.index("Preconditions 5 and 6 are EXPECTED to fail")
    seg = txt[idx:idx + 3000]
    assert "Correction (Stage 5D)" in seg
    assert "zero callers" in seg, "the runbook does not say why starting could not have worked"
    assert "live_source_not_ready" in seg, "the runbook does not name what still holds them"

    # The bare claim must not survive as an unqualified sentence anywhere.
    for line in txt.split("\n"):
        if "starting is what fixes them" in line:
            assert line.lstrip().startswith(">"), \
                f"the retracted claim is still stated as fact: {line!r}"
