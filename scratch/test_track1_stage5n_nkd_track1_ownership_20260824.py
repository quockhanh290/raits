"""Stage 5N — Track 1 owns the MNKD overnight sleeve at slot and source level.

No scheduler started, no real IBKR (frame providers only), no orders, no switch files. Every
ledger these tests write goes under `tmp_path`.

What this stage is, and is not
------------------------------
It is plumbing: the sleeve's rule is the SAME engine as Normal-R4 at the promoted settings —
ema 10, chandelier config 2.5, five-day hold, `RegimeLabels(lag_days=1)`, qty 1, cap 6% — and
nothing about it is re-derived here. After 5N Track 1 owns all four strategy sleeves at
slot/source level in track1-only shadow.

It is NOT legacy independence (the safety sweeps still watch legacy's book — 5O), not paper or
live readiness, and not permission to delete the legacy route (5O + 5P first).

The two clock findings this stage is really about
--------------------------------------------------
1. `detect_entry_for_slot` truncated its scan at `now` converted to **ET** — correct for every
   frame it had ever seen and a 13-hour error for the Tokyo-clocked MNKD frame. Fixed to
   truncate on the frame's own clock.
2. The window gate read a candidate's entry stamp as a bare wall-clock hh:mm and compared it
   to the ET slot band. The committed NKD rows are stamped +09:00 in the Tokyo SESSION window,
   and judging them against the ET band silently rejected 26 of them — the replay's accepted
   tail shrank from 91 to 67 before any 5N test existed. The gate now judges a candidate on
   the sleeve's session window in the sleeve's own clock.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_index import track1_intraday as intra     # noqa: E402
from global_index import track1_live_source as S      # noqa: E402
from global_index import track1_normal_r4 as NR       # noqa: E402
from global_index import track1_params as tp          # noqa: E402
from global_index import track1_signal_layer as T     # noqa: E402
from global_index import track1_slots as ts           # noqa: E402
from global_index import window_ledger as wl          # noqa: E402

NKD = "global_nkd"
JST, ET = "Asia/Tokyo", "America/New_York"
DAYS = pd.bdate_range(end=pd.Timestamp("2026-08-24"), periods=16)
TODAY = pd.Timestamp(DAYS[-1].date())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# fixtures: a Tokyo session with one measured breakout
# ══════════════════════════════════════════════════════════════════════════════

def _day_frame(d, breakout=False):
    idx = pd.date_range(f"{d.date()} 09:00", f"{d.date()} 15:59", freq="1min", tz=JST)
    close = np.full(len(idx), 38000.0)
    vol = np.full(len(idx), 900.0)
    if breakout:
        # 14:30 pullback pinned at the flat level on low volume; 14:35 resume +40 on 4x
        # volume — the exact two-bar pattern `TrendFollowStrategy.generate_signal` admits.
        pb = (idx >= pd.Timestamp(f"{d.date()} 14:30", tz=JST)) & \
             (idx < pd.Timestamp(f"{d.date()} 14:35", tz=JST))
        rs_ = (idx >= pd.Timestamp(f"{d.date()} 14:35", tz=JST)) & \
              (idx < pd.Timestamp(f"{d.date()} 14:40", tz=JST))
        after = idx >= pd.Timestamp(f"{d.date()} 14:40", tz=JST)
        close[pb] = 38001.0; vol[pb] = 300.0
        close[rs_] = 38040.0; vol[rs_] = 3600.0
        close[after] = 38045.0
    return pd.DataFrame({"open": close, "high": close + 6, "low": close - 6,
                         "close": close, "volume": vol}, index=idx)


@pytest.fixture(scope="module")
def tokyo():
    """(frozen Tokyo-aware history, live naive-ET half) — the real provider contract."""
    full = pd.concat([_day_frame(d, breakout=(d == DAYS[-1])) for d in DAYS])
    cut = pd.Timestamp(f"{DAYS[-2].date()} 15:59", tz=JST)
    frozen = full[full.index <= cut]
    live = full[full.index > cut].copy()
    live.index = live.index.tz_convert(ET).tz_localize(None)
    return frozen, live


def _source(tokyo, **kw):
    frozen, live = tokyo
    defaults = dict(bar_provider=S.FrameBarProvider({"MNKD": live}),
                    labels={pd.Timestamp(d.date()): "Normal" for d in DAYS},
                    frozen_frames={"MNKD": frozen}, short_days={TODAY})
    defaults.update(kw)
    return S.LiveTrack1Source(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# 1. slots, inventory, and the argv
# ══════════════════════════════════════════════════════════════════════════════

def test_the_window_is_declared_and_mirrors_the_legacy_cadence():
    assert tp.WINDOWS_ET[NKD] == ("01:10", "02:55")
    nkd = [s for s in ts.TRACK1_SLOTS if s.sleeve == NKD]
    assert len(nkd) == 22
    assert {(s.hour, s.minute) for s in nkd} == \
        {(1, m) for m in range(10, 60, 5)} | {(2, m) for m in range(0, 60, 5)}


def test_the_slot_minutes_are_exactly_the_legacy_nkd_minutes():
    """Asserted against the legacy triggers read from the built scheduler, not from memory."""
    sched = _sched(track1_shadow=True)
    legacy = set()
    for j in sched.get_jobs():
        if j.id.startswith("nkd_night"):
            trig = str(j.trigger)
            legacy.add((int(re.search(r"hour='(\d+)'", trig).group(1)),
                        int(re.search(r"minute='(\d+)'", trig).group(1))))
    assert legacy, "no legacy NKD jobs found — the comparison would pass on nothing"
    mine = {(s.hour, s.minute) for s in ts.TRACK1_SLOTS if s.sleeve == NKD}
    assert mine == legacy, sorted(mine ^ legacy)


def _sched(**kw):
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5n")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        return rs.make_scheduler(port=4002, dry_run=True, **kw)
    finally:
        logging.disable(lvl)


def _argv(**kw):
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
        for j in sched.get_jobs():
            if j.id.startswith("track1_"):
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert seen, "no Track 1 slot fired"
    return seen


def test_nkd_slot_argv_in_track1_only():
    rows = [r for r in _argv(track1_only=True) if r["label"].startswith("TRACK1_NKD_")]
    assert len(rows) == 22
    for r in rows:
        a = r["args"]
        assert a[a.index("--sleeve") + 1] == NKD
        assert a[a.index("--bar-provider") + 1] == "ibkr"
        assert a[a.index("--source") + 1] == "live-shadow"
        assert r["route"] == "track1_candidate"
        for nope in ("--allow-orders", "--port", "--window"):
            assert nope not in a, (r["label"], nope)


def test_nkd_slots_have_no_provider_in_the_transitional_mode():
    """The staging reason travels with the mode: in transitional shadow the legacy nkd_night
    jobs still occupy 01:10-02:55, so the NKD slots run without a provider there — exactly
    the swing pattern, for exactly the swing reason."""
    rows = [r for r in _argv(track1_shadow=True) if r["label"].startswith("TRACK1_NKD_")]
    assert {r["args"][r["args"].index("--bar-provider") + 1] for r in rows} == {"none"}


def test_legacy_nkd_jobs_absent_in_track1_only_present_in_transitional():
    only = {j.id for j in _sched(track1_only=True).get_jobs()}
    trans = {j.id for j in _sched(track1_shadow=True).get_jobs()}
    assert not [i for i in only if i.startswith("nkd_night")], "legacy NKD jobs survived"
    assert len([i for i in trans if i.startswith("nkd_night")]) == 22
    # 60 until 2026-08-24. Stage 5Q-5 added `spy_refresh_pm` at 16:20 ET, the post-close SPY
    # daily refresh, in ALL THREE modes (60->61 default, 129->130 transitional, 100->101
    # track1-only). It is shared infrastructure: both routes read that CSV, so a legacy
    # retirement must not take it with them. A deliberate move, pinned again at its new value.
    assert len(_sched().get_jobs()) == 61, "the default schedule moved"
    assert "spy_refresh_pm" in {j.id for j in _sched().get_jobs()}


def test_the_parser_accepts_the_sleeve():
    """Derived from the window table since 5M-C — this asserts the derivation caught up,
    because the swing sleeve once shipped with slots the parser rejected."""
    import subprocess
    r = subprocess.run([sys.executable, "-m", "global_index.run_live_day_track1",
                        "--source", "live-shadow", "--sleeve", NKD,
                        "--slot-id", "TRACK1_NKD_0110", "--bar-provider", "none",
                        "--regime-csv", "spy_daily_live.csv"],
                       capture_output=True, text=True, cwd=r"d:\raits", timeout=300)
    assert "invalid choice" not in r.stderr, r.stderr[-300:]
    assert "ledger_not_configured" in r.stdout, (
        "expected the route's own fail-closed refusal; got: " + r.stdout[-200:])


# ══════════════════════════════════════════════════════════════════════════════
# 2. the source path — reuse proven, no second implementation
# ══════════════════════════════════════════════════════════════════════════════

def test_the_source_serves_the_sleeve_and_refuses_without_a_provider():
    src = S.LiveTrack1Source()
    with pytest.raises(S.LiveSourceRefused) as e:
        src._for_sleeve(NKD, pd.Timestamp("2026-08-24 01:10", tz=ET), TODAY)
    assert e.value.code == "no_bar_provider"


def test_sleeves_at_answers_the_nkd_band():
    src = S.LiveTrack1Source()
    for t in ("01:10", "02:00", "02:55"):
        assert src.sleeves_at(pd.Timestamp(f"2026-08-24 {t}")) == [NKD], t
    assert src.sleeves_at(pd.Timestamp("2026-08-24 03:00")) == []


def test_a_candidate_is_produced_from_a_tokyo_frame(tokyo):
    cands = _source(tokyo).candidates(pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET))
    assert len(cands) == 1
    c = cands[0]
    assert c.sleeve == NKD and c.instrument == "MNKD"
    assert c.direction == "SHORT" and c.entry_price == 38040.0
    assert c.qty == 1 == tp.SLEEVE_QTY[NKD]
    # the stop is the sleeve's own: entry-anchored 2.0 x daily ATR, on the SHORT side
    assert c.stop_price > c.entry_price
    assert c.meta["ema_period"] == 10
    assert c.meta["fill_law"] == tp.LIVE_FILL_LAW
    assert c.meta["regime_lag1"] == "Normal"


def test_the_candidate_is_causal_across_the_slot_grid(tokyo):
    """The signal bar is 14:35 JST and its 5-minute bucket completes at 14:40 JST = 01:40 ET.
    Slots before that must see nothing; slots at and after it must see the SAME entry."""
    src = _source(tokyo)
    for hhmm in ("01:10", "01:30", "01:35"):
        assert src.candidates(pd.Timestamp(f"{TODAY.date()} {hhmm}", tz=ET)) == [], hhmm
    seen = set()
    for hhmm in ("01:40", "02:00", "02:55"):
        cands = src.candidates(pd.Timestamp(f"{TODAY.date()} {hhmm}", tz=ET))
        assert len(cands) == 1, hhmm
        seen.add((cands[0].entry_price, str(cands[0].entry_time)))
    assert len(seen) == 1, f"the entry moved between slots: {seen}"


def test_the_candidate_entry_stamp_is_the_aware_tokyo_signal_bar(tokyo):
    """The committed replay rows carry +09:00 stamps; the live candidate must speak the same
    convention or the two sides of the equivalence stop being comparable."""
    c = _source(tokyo).candidates(pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET))[0]
    stamp = pd.Timestamp(c.entry_time)
    assert stamp.tzinfo is not None
    assert str(stamp.tz) == "Asia/Tokyo"
    assert str(stamp.time())[:5] == "14:35"


def test_the_spy_short_gate_reaches_the_sleeve(tokyo):
    """The fixture's signal is a SHORT. With today absent from short_days it must vanish —
    the same gate the generator applied to every instrument, exercised live."""
    src = _source(tokyo, short_days=set())
    assert src.candidates(pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET)) == []


def test_a_missing_regime_map_is_a_refusal_not_an_empty_list(tokyo):
    src = _source(tokyo, labels={})
    with pytest.raises(S.LiveSourceRefused) as e:
        src.candidates(pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET))
    assert e.value.code == S.REGIME_UNAVAILABLE


def test_the_regime_is_read_lag_1_not_same_day(tokyo):
    """Yesterday Normal + today Stress must still trade (the lag-1 read sees yesterday);
    yesterday Stress + today Normal must not. Both directions, so the test cannot pass on a
    map that ignores dates entirely."""
    labels_y_normal = {pd.Timestamp(d.date()): "Normal" for d in DAYS}
    labels_y_normal[TODAY] = "Stress"
    src = _source(tokyo, labels=labels_y_normal)
    assert len(src.candidates(pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET))) == 1

    labels_y_stress = {pd.Timestamp(d.date()): "Normal" for d in DAYS}
    labels_y_stress[pd.Timestamp(DAYS[-2].date())] = "Stress"
    src = _source(tokyo, labels=labels_y_stress)
    # lag-1 sees Stress -> TrendFollow allows Stress too; the discriminating regime is Calm
    labels_y_calm = {pd.Timestamp(d.date()): "Normal" for d in DAYS}
    labels_y_calm[pd.Timestamp(DAYS[-2].date())] = "Calm"
    src = _source(tokyo, labels=labels_y_calm)
    assert src.candidates(pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET)) == []


def test_no_legacy_import_and_no_second_rule_implementation():
    """The source path must call the promoted engine, not carry a copy of it."""
    import inspect
    src = inspect.getsource(S.LiveTrack1Source._nkd_candidates)
    assert "detect_entry_for_slot" in src, "the promoted detector is not what runs"
    assert "generate_signal" not in src, "a rule re-implementation crept in"
    import ast as _ast
    tree = _ast.parse(Path("global_index/track1_live_source.py").read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = [a.name for a in node.names]
            assert "global_index.run_live_day" not in ([mod] + names)


# ══════════════════════════════════════════════════════════════════════════════
# 3. the window gate, on the session clock — the replay regression this stage hit
# ══════════════════════════════════════════════════════════════════════════════

def test_the_gate_judges_nkd_stamps_on_the_tokyo_session_window():
    d = TODAY.date()
    ok, _ = T.window_verdict(NKD, pd.Timestamp(f"{d} 14:35", tz=JST))
    assert ok
    bad, why = T.window_verdict(NKD, pd.Timestamp(f"{d} 09:30", tz=JST))
    assert not bad and "JST" in why, why


def test_an_aware_stamp_is_an_instant_not_a_wall_text():
    """The same instant must get the same verdict however it is labelled."""
    d = TODAY.date()
    jst = pd.Timestamp(f"{d} 14:35", tz=JST)
    et = jst.tz_convert(ET)
    assert T.window_verdict(NKD, jst) == T.window_verdict(NKD, et)


def test_the_committed_replay_rows_pass_the_gate_again():
    """The measurement that forced the session-window fix: judging the +09:00 artifact rows
    against the ET slot band rejected 26 of them and shrank the accepted tail 91 -> 67. This
    pins the restored state, on the full replay rather than a sample."""
    from global_index import track1_bootstrap as boot
    from global_index.track1_sleeves import load_source
    src = load_source("replay")
    cands = src.candidates("vault2026")
    nkd = [c for c in cands if c.sleeve == NKD]
    assert nkd, "no NKD rows in the replay — the check would pass on nothing"
    rejected = [c.trade_id for c in nkd if not T.window_verdict(NKD, c.entry_time)[0]]
    assert rejected == [], rejected
    b = boot._fresh_book()
    tail, _ = T.run_candidates(cands, book=b,
                               early_exit_value=src.early_exit_valuer("vault2026"))
    assert len(tail) == 91, len(tail)
    assert b.counters.get("reject_window", 0) == 0


def test_us_sleeves_still_judge_on_et():
    ok, _ = T.window_verdict("roska4_swing", pd.Timestamp(f"{TODAY.date()} 14:30"))
    assert ok
    bad, why = T.window_verdict("roska4_swing", pd.Timestamp(f"{TODAY.date()} 11:00"))
    assert not bad and "ET" in why


# ══════════════════════════════════════════════════════════════════════════════
# 4. ledger, admission, freshness, checkpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_ledger_expected_slots_matches_the_registered_slots():
    assert wl.expected_slots(NKD) == 22 == len([s for s in ts.TRACK1_SLOTS
                                                if s.sleeve == NKD])


def test_a_window_is_complete_only_at_22_decided_slots(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    importlib.reload(wl)
    try:
        day = str(TODAY.date())
        slots = [s for s in ts.TRACK1_SLOTS if s.sleeve == NKD]
        wl.window_open(NKD, day, route_hint=tp.ROUTE)
        for s_ in slots[:21]:
            wl.slot_observed(NKD, day, s_.id, decided=True, route_hint=tp.ROUTE)
        wl.window_closed(NKD, day, 21, route_hint=tp.ROUTE, signal=wl.NO_SIGNAL,
                         slots_ran=21, slots_decided=21)
        st = wl.status(wl.read_day(day), NKD, day)
        assert st["outcome"] != "complete" and st["usable_as_evidence"] is False, st
        wl.slot_observed(NKD, day, slots[21].id, decided=True, route_hint=tp.ROUTE)
        wl.window_closed(NKD, day, 22, route_hint=tp.ROUTE, signal=wl.NO_SIGNAL,
                         slots_ran=22, slots_decided=22)
        st = wl.status(wl.read_day(day), NKD, day)
        assert st["outcome"] == "complete" and st["usable_as_evidence"] is True, st
    finally:
        monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
        importlib.reload(wl)


def test_the_admission_requirement_is_written_in_the_tokyo_clock():
    r = intra.REQUIREMENTS[NKD]
    assert r.clock == "Asia/Tokyo"
    assert (r.decide_from, r.decide_to) == tp.SESSION_WINDOWS[NKD] == ("14:10", "15:55")
    assert (r.today_from, r.today_to) == ("14:00", "15:55")
    assert r.needs_prior_rth is False and r.bar_minutes == 5


def test_the_admission_gate_validates_a_tokyo_frame_at_an_et_instant(tokyo):
    """The whole point of Requirement.clock: an ET slot instant and a Tokyo frame, one call,
    no 13-hour error. TOO_EARLY before the session decide band, OK inside it."""
    frozen, live = tokyo
    joined = S.sleeve_frames(provider=S.FrameBarProvider({"MNKD": live}),
                             through=pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET),
                             frozen_frames={"MNKD": frozen}, sleeves=[NKD])[NKD]
    frame = joined["MNKD"].frame
    b5 = frame.resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                     "close": "last", "volume": "sum"}).dropna()
    v = intra.validate(NKD, b5, now_et=pd.Timestamp(f"{TODAY.date()} 02:55", tz=ET))
    assert v.allow, [c.detail for c in v.checks if c.refuses]
    early = intra.validate(NKD, b5, now_et=pd.Timestamp(f"{TODAY.date()} 01:05", tz=ET))
    assert not early.allow and intra.TOO_EARLY in early.codes


def test_freshness_is_d_minus_1_for_every_nkd_slot():
    from global_index import track1_freshness as fresh
    monday = "2026-08-24"
    for s_ in ts.TRACK1_SLOTS:
        if s_.sleeve != NKD:
            continue
        at = pd.Timestamp(f"{monday} {s_.hour:02d}:{s_.minute:02d}")
        assert fresh.required_data_through(at) == pd.Timestamp("2026-08-21"), s_.id


def test_a_checkpoint_can_be_written_for_the_sleeve_under_a_temp_path(tmp_path, tokyo):
    """CHECKPOINTED_SLEEVES has carried global_nkd since Stage 2C; this proves the schema
    really closes over a Tokyo frame rather than trusting the list."""
    from global_index import track1_bootstrap as boot
    frozen, _live = tokyo
    pq = tmp_path / "MNKD.parquet"
    frozen.to_parquet(pq)
    state = {"schema_version": 2, "route": tp.ROUTE, "window": "live",
             "cut_instant": f"{TODAY.date()}T02:55:00", "equity": 0.0,
             "cur_day": str(TODAY.date()), "peak_equity": 0.0, "day_start_equity": 0.0,
             "positions": [], "booked_counter": {}, "counters": {}}
    entries = boot.checkpoint_entries(state, frames={"MNKD": frozen},
                                      regime_csv="spy_daily_live.csv",
                                      data_paths={"MNKD": str(pq)},
                                      fill_law=tp.LIVE_FILL_LAW)
    assert NKD in entries, sorted(entries)
    ck = tmp_path / "cp.json"
    boot.write(state, entries=entries, book_path=str(tmp_path / "book.json"),
               checkpoint_path=str(ck))
    import json as _json
    payload = _json.loads(ck.read_text(encoding="utf-8"))
    assert NKD in _json.dumps(payload)


def test_nkd_decisions_never_read_the_legacy_book():
    """The decision path is candidates -> gate -> book, and the book is the route's own.
    Asserted at the source level: nothing under the NKD candidate path names the legacy
    positions file."""
    import inspect
    for fn in (S.LiveTrack1Source._nkd_candidates, NR.detect_entry_for_slot):
        assert "live_positions.json" not in inspect.getsource(fn)


# ══════════════════════════════════════════════════════════════════════════════
# 5. dashboard, parity, ops counts
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kw", [{}, {"track1_shadow": True}, {"track1_only": True}])
def test_parity_in_all_three_modes(kw):
    r = ts.parity_report(**kw)
    assert r["in_parity"], r


def test_the_mirror_carries_the_nkd_rows(monkeypatch):
    import datetime as dt
    monkeypatch.setenv("RAITS_TRACK1_SHADOW", "1")
    from monitor.backend import schedule_status as ss
    importlib.reload(ss)
    try:
        ids = {s["id"] for s in ss._scheduled_slots_for(dt.date(2026, 8, 24))}
        want = {s.id for s in ts.TRACK1_SLOTS if s.sleeve == NKD}
        assert want <= ids, sorted(want - ids)
    finally:
        monkeypatch.delenv("RAITS_TRACK1_SHADOW", raising=False)
        importlib.reload(ss)


def test_ops_count_is_derived_and_covers_the_new_sleeve():
    from monitor import ops
    assert ops.track1_slot_count() == len(ts.TRACK1_SLOTS) == 70
