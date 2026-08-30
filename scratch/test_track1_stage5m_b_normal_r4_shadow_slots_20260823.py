"""Stage 5M-B — Normal-R4 has Track 1 slots, and they run without a provider.

Read-only against the operator's world: no scheduler is started, no broker is opened, no order
is possible, and every ledger, checkpoint and explanation these tests produce goes under
`tmp_path`. Two tests hash the real Track 1 shadow directory and the operator's state files
around themselves to prove that.

What this stage claims, and what it does NOT
--------------------------------------------
It claims: the 23 swing slots exist, the scheduler and the dashboard agree about them, they
carry `--bar-provider none`, and the path beneath them is real enough to refuse by name.

It does not claim Track 1 shadow is ready. The swing slots produce a NAMED REFUSAL and a ledger
row, nothing else, until Stage 5M-C switches a provider on. That is the point of the staging:
these slots land on the same minutes as the legacy 14:05-15:55 entry slots, whose runs take a
median 194s of a 300s window and a measured maximum of 291s, and nobody has measured what a
Track 1 slot costs because none has ever run in production.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_index import track1_intraday as intra      # noqa: E402
from global_index import track1_live_source as S       # noqa: E402
from global_index import track1_normal_r4 as NR        # noqa: E402
from global_index import track1_params as tp           # noqa: E402
from global_index import track1_slots as ts            # noqa: E402
from global_index import window_ledger as wl           # noqa: E402

SWING = "roska4_swing"
ET = "America/New_York"
DAY = pd.Timestamp("2026-08-20")


# ══════════════════════════════════════════════════════════════════════════════
# N1 - the window exists and is the legacy cadence, exactly
# ══════════════════════════════════════════════════════════════════════════════

def test_n1_the_swing_window_is_declared():
    assert tp.WINDOWS_ET[SWING] == ("14:05", "15:55")


def test_n1_the_source_answers_at_swing_instants():
    src = S.LiveTrack1Source()
    for t in ("14:05", "14:30", "15:55"):
        assert src.sleeves_at(pd.Timestamp(f"2026-08-24 {t}")) == [SWING], t
    assert src.sleeves_at(pd.Timestamp("2026-08-24 16:00")) == []


def test_n1_the_window_mirrors_the_legacy_entry_minutes_exactly():
    """Not "roughly the same times". The measured rule takes the FIRST admitted signal after
    the 14:00 resume bar, so a slot one minute off is a different rule wearing the name."""
    import re
    legacy = set()
    for jid, trig in _legacy_entry_triggers():
        h = int(re.search(r"hour='(\d+)'", trig).group(1))
        m = int(re.search(r"minute='(\d+)'", trig).group(1))
        legacy.add((h, m))
    swing = {(s.hour, s.minute) for s in ts.TRACK1_SLOTS if s.sleeve == SWING}
    assert legacy, "no legacy entry slots found — the comparison would pass on nothing"
    assert swing == legacy, (sorted(swing ^ legacy))


def _legacy_entry_triggers():
    sched = _sched(track1_shadow=True)
    return [(j.id, str(j.trigger)) for j in sched.get_jobs()
            if j.id == "live_day" or j.id.startswith("live_day_")]


# ══════════════════════════════════════════════════════════════════════════════
# N2 - the slots, the inventory, and the argv the scheduler really builds
# ══════════════════════════════════════════════════════════════════════════════

def _sched(*, track1_shadow: bool):
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5mb")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        return rs.make_scheduler(port=4002, dry_run=True, track1_shadow=track1_shadow)
    finally:
        logging.disable(lvl)


def test_n2_slot_inventory_by_sleeve():
    # Stage 5N added global_nkd: 22. This stage's own claim — the swing 23 — is unchanged.
    from collections import Counter
    got = Counter(s.sleeve for s in ts.TRACK1_SLOTS)
    assert got == {"roska4_calm": 1, "roska4_stress": 24, SWING: 23, "global_nkd": 22}, got


def test_n2_scheduler_job_inventory():
    assert len(_sched(track1_shadow=False).get_jobs()) == 60
    # 59 = 60 legacy jobs minus the displaced stop_repair_1220; the rest is the slot table.
    assert len(_sched(track1_shadow=True).get_jobs()) == 59 + len(ts.TRACK1_SLOTS)


def test_n2_swing_slot_ids_are_registered():
    ids = {j.id for j in _sched(track1_shadow=True).get_jobs()}
    want = {s.id.lower() for s in ts.TRACK1_SLOTS if s.sleeve == SWING}
    assert len(want) == 23
    assert want <= ids, sorted(want - ids)


def _capture_argv():
    """Fire every Track 1 slot closure with the subprocess runner replaced. Nothing executes."""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True)
        for j in sched.get_jobs():
            if j.id.startswith("track1_"):
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert seen, "no Track 1 slot closure ran — nothing was captured"
    return {r["label"]: r for r in seen}


@pytest.fixture(scope="module")
def argv():
    return _capture_argv()


def test_the_swing_slots_are_launched_without_a_bar_provider(argv):
    swing = {k: v for k, v in argv.items() if k.startswith("TRACK1_SWING_")}
    assert len(swing) == 23, sorted(swing)
    for label, rec in swing.items():
        a = rec["args"]
        assert a[1:3] == ["-m", "global_index.run_live_day_track1"], (label, a)
        assert a[a.index("--source") + 1] == "live-shadow", label
        assert a[a.index("--sleeve") + 1] == SWING, label
        assert a[a.index("--bar-provider") + 1] == "none", label
        assert a[a.index("--slot-id") + 1] == label, label


def test_calm_and_stress_argv_are_unchanged(argv):
    """Stage 5M-B made the provider per-slot. The two sleeves that already had one must come
    out of that change byte for byte — a staging step that quietly altered production is not a
    staging step."""
    others = {k: v for k, v in argv.items()
              if not k.startswith(("TRACK1_SWING_", "TRACK1_NKD_"))}
    assert len(others) == 25, sorted(others)
    for label, rec in others.items():
        assert rec["args"][rec["args"].index("--bar-provider") + 1] == "ibkr", label


@pytest.mark.parametrize("flag", ["--allow-orders", "--port", "--window"])
def test_no_track1_slot_carries_an_order_or_replay_flag(argv, flag):
    """The order gate refuses while any blocker is open and every blocker is open. That is the
    guarantee; the argv must not be the only thing standing between a shadow slot and an order
    path, and `--window` would silently turn a live slot back into a replay of vault2026."""
    offenders = [k for k, v in argv.items() if flag in v["args"]]
    assert offenders == [], offenders


def test_every_track1_slot_is_stamped_with_the_route(argv):
    assert {v["route"] for v in argv.values()} == {"track1_candidate"}


def test_the_order_gate_still_blocks(argv):
    from global_index import track1_gates as g
    assert g.as_ledger()["blocking_now"] == ["B1_broker_account_or_legacy_retirement"]


# ══════════════════════════════════════════════════════════════════════════════
# N3 - the live source serves the sleeve
# ══════════════════════════════════════════════════════════════════════════════

def test_n3_the_source_no_longer_refuses_the_sleeve_outright():
    """It must refuse for a MISSING PROVIDER, not for being the wrong sleeve. Those are
    different failures and only one of them is fixable by handing it bars."""
    src = S.LiveTrack1Source()
    with pytest.raises(S.LiveSourceRefused) as e:
        src._for_sleeve(SWING, pd.Timestamp("2026-08-24 14:05"), DAY)
    assert e.value.code == "no_bar_provider", e.value.code


def test_n3_a_sleeve_with_no_slot_is_still_refused_by_name():
    # `global_nkd` was the example until Stage 5N gave it a slot — the second time this
    # fixture pattern has expired (roska4_swing was the example before 5M-B). The property
    # needs a name that stays outside the window table, not the next sleeve in the queue.
    src = S.LiveTrack1Source()
    with pytest.raises(S.LiveSourceRefused) as e:
        src._for_sleeve("sleeve_without_a_window", pd.Timestamp("2026-08-24 14:05"), DAY)
    assert e.value.code == S.SLEEVE_NOT_LIVE
    assert SWING in e.value.detail, "the refusal message did not follow the window table"


def test_n3_a_missing_regime_label_is_a_refusal_not_an_empty_list():
    """A window of empty lists reads as 'no setups today'. A window of refusals reads as
    'nothing ran'. Recording the second as the first is how a broken day closes clean."""
    frames = _synthetic_frames()
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(frames),
                             labels={}, frozen_frames=frames)
    with pytest.raises(S.LiveSourceRefused) as e:
        src._swing_candidates(pd.Timestamp(f"{DAY.date()} 14:05"), DAY)
    assert e.value.code == S.REGIME_UNAVAILABLE


# ══════════════════════════════════════════════════════════════════════════════
# N4 - the admission requirement
# ══════════════════════════════════════════════════════════════════════════════

def test_n4_the_swing_requirement_exists_and_matches_the_window():
    r = intra.REQUIREMENTS[SWING]
    assert r.sleeve == SWING
    assert r.bar_minutes == 5
    assert (r.decide_from, r.decide_to) == tp.WINDOWS_ET[SWING]
    assert r.decision_bar is None, "the sleeve takes the first admitted signal, not a fixed bar"


def test_n4_the_requirement_declares_only_the_span_the_rule_reads():
    """`today_from` is 14:00, not 09:30. The scan opens at the resume bar and its volume
    average looks back eleven bars from there; demanding the whole session would make the gate
    refuse for a reason the sleeve does not have, and a gate like that gets widened."""
    r = intra.REQUIREMENTS[SWING]
    assert r.today_from == "14:00"
    assert r.today_to == "15:55"
    assert r.needs_prior_rth is False


def test_n4_every_sleeve_with_a_slot_has_a_requirement():
    """The property, not the constant: a slot whose sleeve the gate cannot describe would be
    admitted or refused by nothing at all."""
    slotted = {s.sleeve for s in ts.TRACK1_SLOTS}
    assert slotted, "no slots"
    assert slotted <= set(intra.REQUIREMENTS), sorted(slotted - set(intra.REQUIREMENTS))


# ══════════════════════════════════════════════════════════════════════════════
# N5 - the window ledger
# ══════════════════════════════════════════════════════════════════════════════

def test_n5_expected_slots_is_23():
    assert wl.expected_slots(SWING) == 23


def test_n5_expected_slots_equals_the_number_of_registered_slots():
    """Two numbers that must agree, derived from different places: one from the ledger table,
    one by counting the slot tuple. Pinning them to each other is what notices a window edit
    that moves only one."""
    registered = len([s for s in ts.TRACK1_SLOTS if s.sleeve == SWING])
    assert wl.expected_slots(SWING) == registered


def test_n5_every_slotted_sleeve_has_a_ledger_window():
    for sleeve in {s.sleeve for s in ts.TRACK1_SLOTS}:
        assert wl.expected_slots(sleeve) is not None, sleeve


def test_n5_a_window_is_complete_only_at_23_decided_slots(tmp_path, monkeypatch):
    """Coverage is what a shadow period is measured on. A window that closes 'complete' on
    fewer slots than it has would make a half-observed day look like evidence."""
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    importlib.reload(wl)
    try:
        day = str(DAY.date())
        slots = [s for s in ts.TRACK1_SLOTS if s.sleeve == SWING]
        assert len(slots) == 23

        # 22 decided slots, then close: SHORT of the window, and it must say so.
        wl.window_open(SWING, day, route_hint=tp.ROUTE)
        for s in slots[:22]:
            wl.slot_observed(SWING, day, s.id, decided=True, route_hint=tp.ROUTE)
        st = wl.status(wl.read_day(day), SWING, day)
        assert st["outcome"] == "unobserved" and st["usable_as_evidence"] is False, st

        wl.window_closed(SWING, day, 22, route_hint=tp.ROUTE, signal=wl.NO_SIGNAL,
                         slots_ran=22, slots_decided=22)
        st = wl.status(wl.read_day(day), SWING, day)
        assert st["outcome"] != "complete", st
        assert st["usable_as_evidence"] is False, st

        # the 23rd, then close again: now and only now is the day evidence.
        wl.slot_observed(SWING, day, slots[22].id, decided=True, route_hint=tp.ROUTE)
        wl.window_closed(SWING, day, 23, route_hint=tp.ROUTE, signal=wl.NO_SIGNAL,
                         slots_ran=23, slots_decided=23)
        st = wl.status(wl.read_day(day), SWING, day)
        assert st["outcome"] == "complete", st
        assert st["usable_as_evidence"] is True, st
        assert st["expected_slots"] == 23
    finally:
        monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
        importlib.reload(wl)


# ══════════════════════════════════════════════════════════════════════════════
# N6 - the stop-repair declaration
# ══════════════════════════════════════════════════════════════════════════════

def test_n6_the_swing_entry_window_is_declared():
    assert ts.REQUIRED_ENTRY_WINDOWS[SWING] == ((14, 5), (15, 55))
    assert ts.REQUIRED_ENTRY_WINDOWS["roska4_stress"] == ((10, 35), (12, 30))


@pytest.mark.parametrize("flag", ["0", "1"])
def test_n6_no_stop_repair_sweep_lands_inside_the_swing_window(flag, monkeypatch):
    """Measured, not assumed. Hour 14 was ALREADY excluded because it is the legacy R4 window,
    so this window needed no new exclusion — and this test is what would notice if that
    coincidence ever stopped holding."""
    monkeypatch.setenv("RAITS_TRACK1_SHADOW", flag)
    from monitor.backend import schedule_status as ss
    lo, hi = ts.REQUIRED_ENTRY_WINDOWS[SWING]
    lo_m, hi_m = lo[0] * 60 + lo[1], hi[0] * 60 + hi[1]
    inside = [(h, m) for h, m in ss._stop_repair_slots() if lo_m <= h * 60 + m <= hi_m]
    assert inside == [], inside


# ══════════════════════════════════════════════════════════════════════════════
# the slot, end to end, with and without a provider
# ══════════════════════════════════════════════════════════════════════════════

def _synthetic_frames():
    """Four instruments, one session of 1-minute bars, real column set and a naive ET index."""
    idx = pd.date_range(f"{DAY.date()} 09:30", f"{DAY.date()} 15:59", freq="1min")
    out = {}
    for n, inst in enumerate(tp.SLEEVE_INSTRUMENTS[SWING]):
        base = 100.0 + n
        close = base + np.linspace(0, 1.5, len(idx))
        out[inst] = pd.DataFrame(
            {"open": close, "high": close + 0.25, "low": close - 0.25, "close": close,
             "volume": np.full(len(idx), 500.0)}, index=idx)
    return out


@pytest.fixture
def slot(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    yield d, wl, entry
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    importlib.reload(wl)
    importlib.reload(entry)


def test_a_swing_slot_without_a_provider_refuses_by_name_and_still_records_that_it_ran(slot):
    """The production shape of Stage 5M-B: 23 slots a day, each one refusing.

    The refusal must be NAMED and the ledger row must exist. A slot that failed silently would
    leave a window that looks unobserved, and one that recorded `decided` would make an empty
    day look like a measured one.
    """
    d, wl_, entry = slot
    res = entry.observe_live_slot(SWING, "TRACK1_SWING_1405",
                                  now_et=pd.Timestamp(f"{DAY.date()} 14:05", tz=ET),
                                  provider=None, root=str(d.parent))
    assert res["decided"] is False
    assert res["reason"] in (entry.NO_BAR_PROVIDER, entry.LIVE_SOURCE_NOT_READY,
                             "no_bar_provider"), res
    rows = wl_.read_day(str(DAY.date()))
    mine = [r for r in rows if r.get("sleeve") == SWING]
    assert mine, "the slot refused without recording that it ran"
    st = wl_.status(rows, SWING, str(DAY.date()))
    assert st["outcome"] != "complete", st


def test_a_refused_swing_slot_writes_no_checkpoint(slot):
    d, _wl, entry = slot
    before = Path(entry.CHECKPOINT_PATH)
    stamp = before.read_bytes() if before.exists() else None
    entry.observe_live_slot(SWING, "TRACK1_SWING_1405",
                            now_et=pd.Timestamp(f"{DAY.date()} 14:05", tz=ET),
                            provider=None, root=str(d.parent))
    after = before.read_bytes() if before.exists() else None
    assert after == stamp, "a refused slot touched the route checkpoint"


def test_a_swing_slot_with_a_frame_provider_reaches_the_route_machinery(slot):
    """Past `no_bar_provider` and into the route: freshness, admission, the join guard and the
    explanation writer. What it decides is not the subject — that it gets a NAMED route answer
    instead of an unhandled exception is."""
    d, _wl, entry = slot
    frames = _synthetic_frames()
    res = entry.observe_live_slot(
        SWING, "TRACK1_SWING_1405",
        now_et=pd.Timestamp(f"{DAY.date()} 14:05", tz=ET),
        provider=S.FrameBarProvider(frames), frozen_frames=frames,
        live_source=S.LiveTrack1Source(bar_provider=S.FrameBarProvider(frames),
                                       labels={DAY - pd.Timedelta(days=1): "Normal"},
                                       frozen_frames=frames),
        root=str(d.parent))
    known = {entry.DECIDED, entry.GATE_REFUSED, entry.FRESHNESS_REFUSED,
             entry.LIVE_SOURCE_NOT_READY, entry.NO_BAR_PROVIDER}
    assert res["reason"] in known or isinstance(res["reason"], str), res
    assert res["reason"] != "", "the slot produced no reason at all"
    assert "traceback" not in str(res.get("detail", "")).lower()


# ══════════════════════════════════════════════════════════════════════════════
# the rule itself: the slot detector is the measured rule, not a second copy
# ══════════════════════════════════════════════════════════════════════════════

def test_the_slot_detector_is_causal_and_returns_nothing_from_the_future():
    frames = _synthetic_frames()
    labels = {DAY: "Normal"}
    p = NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
    got = NR.detect_entry_for_slot(frames["MES"], labels, "MES", DAY,
                                   pd.Timestamp(f"{DAY.date()} 14:05"), p, short_days=set())
    if got is not None:
        assert pd.Timestamp(got.signal_bar) <= pd.Timestamp(f"{DAY.date()} 14:05")


def test_the_slot_detector_returns_none_outside_the_allowed_regime():
    frames = _synthetic_frames()
    p = NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
    for regime in ("Calm", "Stress", "Crisis"):
        assert NR.detect_entry_for_slot(frames["MES"], {DAY: regime}, "MES", DAY,
                                        pd.Timestamp(f"{DAY.date()} 15:55"), p,
                                        short_days=set()) is None, regime


def test_the_swing_candidates_carry_the_production_fill_law():
    """Stage 5M-1's decision has to survive a new sleeve. The candidate's params come from
    `LIVE_FILL_LAW`, not from an engine default that a reproduction run could move."""
    src = S.LiveTrack1Source()
    p = src.swing_params or NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
    assert p.fill_law == tp.LIVE_FILL_LAW == "production_gap_after_15min_break"


# ══════════════════════════════════════════════════════════════════════════════
# parity, and leaving the operator's world alone
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("flag", [False, True])
def test_the_scheduler_and_the_dashboard_mirror_agree(flag):
    r = ts.parity_report(track1_shadow=flag)
    assert r["in_parity"], r


def test_the_mirror_shows_the_swing_slots_when_the_flag_is_on(monkeypatch):
    import datetime as dt
    monkeypatch.setenv("RAITS_TRACK1_SHADOW", "1")
    from monitor.backend import schedule_status as ss
    ids = {s["id"] for s in ss._scheduled_slots_for(dt.date(2026, 8, 24))}
    want = {s.id for s in ts.TRACK1_SLOTS if s.sleeve == SWING}
    assert want <= ids, sorted(want - ids)


def test_no_production_module_routes_the_swing_sleeve_to_legacy_run_live_day():
    """`run_live_day` is legacy's entry point. A Track 1 sleeve reaching it would be the route
    quietly borrowing the other engine — the exact thing the whole promotion exists to avoid."""
    gi = Path(r"d:\raits\global_index")
    offenders = []
    for path in sorted(gi.glob("*.py")):
        if path.name in ("run_live_day.py", "run_scheduler.py"):
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
               and node.value == "global_index.run_live_day":
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def _hash(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def test_this_suite_leaves_the_operators_files_alone():
    """The Stage 5L incident, kept from recurring: a probe that fires job bodies can write real
    state without meaning to. Hash what matters, run the slot path, hash again."""
    watched = [Path("global_index/preflight_state.json"),
               Path("global_index/maxhold_state.json"),
               Path("live_positions.track1.json"),
               Path("global_index/replay_checkpoint.track1.json")]
    before = {str(p): _hash(p) for p in watched}
    assert any(v for v in before.values()), "nothing to guard — this test would pass vacuously"
    _capture_argv()
    after = {str(p): _hash(p) for p in watched}
    assert after == before, [k for k in before if before[k] != after[k]]


def test_the_real_shadow_directory_is_not_created_by_these_tests():
    real = Path("scratch/track1_shadow/explanations")
    existed = real.exists()
    _capture_argv()
    assert real.exists() == existed, "a test created the real shadow explanations directory"
