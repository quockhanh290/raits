"""scratch/test_track1_stage3b_blockers_20260822.py — the Stage 3B gate.

    python -m pytest scratch/test_track1_stage3b_blockers_20260822.py -q
    TRACK1_REGEN=1 python -m pytest scratch/test_track1_stage3b_blockers_20260822.py -q

Offline. No broker, no scheduler started, no dashboard write, no order.

The regeneration test is opt-in for one reason, and it is not speed (it takes ~35 s): the
Normal-R4 generator REPLACES five production symbols for the duration of its run, so it is
driven in a SUBPROCESS. That is also the mitigation the SLEEVE_normal_r4 gate names, so the
test doubles as a demonstration of it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import route_checkpoint as rc  # noqa: E402
from global_index import run_live_day_track1 as entry  # noqa: E402
from global_index import track1_bootstrap as boot  # noqa: E402
from global_index import track1_gates as g
from global_index import track1_normal_r4 as NR  # noqa: E402
from global_index import track1_intraday as intra  # noqa: E402
from global_index import track1_live_sleeves as ls  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_signal_layer as T  # noqa: E402
from global_index import track1_slots as slots  # noqa: E402

DAY = pd.Timestamp("2026-03-02")            # a Monday
PRIOR = pd.Timestamp("2026-02-27")           # the Friday before it


# ══════════════════════════════════════════════════════════════════════════════
# 1. B1 — the go-live gate
# ══════════════════════════════════════════════════════════════════════════════
def _write_conf(tmp_path, payload) -> str:
    p = tmp_path / "conf.json"
    p.write_text(json.dumps(payload) if not isinstance(payload, str) else payload,
                 encoding="utf-8")
    return str(p)


def test_b1_the_sentinel_is_not_created_by_this_build():
    assert not Path(g.CONFIRMATION_PATH).exists(), (
        f"{g.CONFIRMATION_PATH} exists. This build must never create it — a confirmation "
        f"that appears without a person putting it there is not a confirmation.")


def test_b1_allow_orders_refuses_without_confirmation(monkeypatch):
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    gate = entry.OrderGate(True)
    assert gate.allow_orders is False
    assert gate.state == entry.OrderGate.REFUSED
    joined = " ".join(gate.reasons)
    assert "B1_broker_account_or_legacy_retirement" in joined
    assert entry.main(["--allow-orders", "--window", "vault2026"]) == 2


def test_b1_is_now_the_only_thing_between_the_route_and_an_armed_gate(tmp_path, monkeypatch):
    """Stage 4 changed what this test can say, and the change is worth stating loudly.

    When it was written, releasing B1 left three other gates shut. Stage 4 closed all three by
    building what was missing, so B1 is the last one — and a valid confirmation plus the
    environment approval now genuinely ARMS the order gate. That is the designed end state,
    not a regression, but it means the confirmation file is no longer one safeguard among
    several. It is the safeguard.
    """
    path = _write_conf(tmp_path, {
        "schema_version": 1, "confirmed_by": "test", "confirmed_at": "2026-03-02",
        "legacy_retired_confirmed": True})
    conf, errs = g.load_confirmations(path)
    assert errs == [] and conf.get("legacy_retired_confirmed") is True

    before = {b.id for b in g.blocking()}
    still = {b.id for b in g.blocking(conf)}
    assert "B1_broker_account_or_legacy_retirement" in before, "B1 was not blocking to begin with"
    # Exactly B1 moves. Asserted against the registry rather than a hand-written list, so this
    # keeps testing INDEPENDENCE as blockers close instead of going red the day one does.
    assert before - still == {"B1_broker_account_or_legacy_retirement"}, before - still
    # This line has now been rewritten twice, in both directions: Stage 4B added a measured
    # gate so releasing B1 no longer emptied the table, and Stage 4C released that gate by
    # building the path, so it does again. Chasing the state is the wrong test, so BOTH
    # directions are asserted below and neither can be satisfied by accident.
    # Stage 5S: no longer "the table empties". A MEASURED gate cannot be signed, so releasing
    # every confirmation leaves exactly the measurements that are currently shut. Asserting
    # THAT is the property; asserting emptiness was chasing the state, which this test's own
    # comment above says is the wrong test — and it had already been rewritten twice for it.
    _measured_shut = {b.id for b in g.BLOCKERS.values()
                      if b.released_by_measurement and not b.measure()[0]}
    assert still == _measured_shut, f"a CONFIRMATION gate survived its signature: {still}"
    assert all(g.BLOCKERS[i].released_by == () for i in still), (
        "something in `still` could have been signed away and was not")

    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    assert entry.OrderGate(True, confirmation_path=path).allow_orders is False,         "a confirmation file alone armed the gate — the environment factor is not wired"

    # Stage 5S. This test is about the two AUTHORISATION factors — a signed confirmation and
    # the out-of-band environment approval — so the EVIDENCE gate is satisfied here rather
    # than left to the real audit directory. Leaving it to the real one would make a test
    # about wiring pass or fail on how the shadow route happened to run that week.
    for name in list(g.MEASUREMENTS):
        monkeypatch.setitem(g.MEASUREMENTS, name,
                            lambda root="": (True, "satisfied for this test"))

    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert entry.OrderGate(True, confirmation_path=path).allow_orders is True,         "both factors were satisfied and the gate still refused — something is blocking that "         "the registry does not report"

    # And the other direction: a measured gate that fails shuts the route again no matter what
    # is signed or exported. This is what stops the two factors above from being the whole
    # story the day somebody adds a fetch that skips the join.
    monkeypatch.setitem(g.MEASUREMENTS, "live_frame_wiring",
                        lambda root="": (False, "held shut for this test"))
    assert entry.OrderGate(True, confirmation_path=path).allow_orders is False,         "a failing measurement did not re-shut the gate"


def test_b1_the_separate_account_route_releases_it_too(tmp_path):
    path = _write_conf(tmp_path, {
        "schema_version": 1, "confirmed_by": "test", "confirmed_at": "2026-03-02",
        "separate_account_confirmed": True})
    conf, errs = g.load_confirmations(path)
    assert errs == []
    assert "B1_broker_account_or_legacy_retirement" not in {b.id for b in g.blocking(conf)}


@pytest.mark.parametrize("bad,why", [
    ({"schema_version": 2, "confirmed_by": "t", "confirmed_at": "d",
      "legacy_retired_confirmed": True}, "wrong schema"),
    ({"schema_version": 1, "confirmed_at": "d", "legacy_retired_confirmed": True},
     "no confirmed_by"),
    ({"schema_version": 1, "confirmed_by": "  ", "confirmed_at": "d",
      "legacy_retired_confirmed": True}, "blank confirmed_by"),
    ({"schema_version": 1, "confirmed_by": "t", "confirmed_at": "d",
      "legacy_retired_confirmed": "yes"}, "flag is not a boolean"),
    ({"schema_version": 1, "confirmed_by": "t", "confirmed_at": "d",
      "legacy_retired_confirm": True}, "misspelled flag"),
    ({"schema_version": 1, "confirmed_by": "t", "confirmed_at": "d",
      "legacy_retired_confirmed": True, "extra_flag": True}, "unknown key"),
    ("{not json", "unparseable"),
    ("[1,2,3]", "not an object"),
])
def test_b1_an_invalid_confirmation_fails_closed(tmp_path, monkeypatch, bad, why):
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    path = _write_conf(tmp_path, bad)
    conf, errs = g.load_confirmations(path)
    assert errs, f"{why}: accepted a file it should have refused"
    assert conf.flags == {}, f"{why}: granted flags from a file that failed validation"
    gate = entry.OrderGate(True, confirmation_path=path)
    assert gate.allow_orders is False
    assert any("confirmation file" in r for r in gate.reasons), why


def test_b1_a_misspelled_flag_is_refused_rather_than_silently_dropped(tmp_path):
    """The direction that matters. Ignoring the typo would leave the operator believing a
    gate is open that is shut."""
    path = _write_conf(tmp_path, {
        "schema_version": 1, "confirmed_by": "t", "confirmed_at": "d",
        "legacy_retired_confirm": True})
    _conf, errs = g.load_confirmations(path)
    assert any("unknown key" in e for e in errs)


def test_b1_the_gate_can_actually_open_so_the_refusal_is_the_blockers_talking(monkeypatch):
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert entry.OrderGate(True, blockers={}).allow_orders is True
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    assert entry.OrderGate(True, blockers={}).allow_orders is False, \
        "one flag on a command line was enough — the second factor is not wired"


def test_b1_the_runbook_exists_and_names_both_paths():
    p = Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md")
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    for token in ("legacy_retired_confirmed", "separate_account_confirmed", "STOP_TRADING",
                  "Rollback", "_ENTRY_WINDOWS"):
        assert token in txt, token


# ══════════════════════════════════════════════════════════════════════════════
# 2. B3 — intraday bar coverage
# ══════════════════════════════════════════════════════════════════════════════
def _calm_frame(day=DAY, prior=PRIOR, **kw):
    a = intra.synth_bars(prior, "09:30", "16:00", **kw)
    b = intra.synth_bars(day, "09:30", "10:00", **kw)
    return pd.concat([a, b])


def _stress_frame(day=DAY, to="12:30", **kw):
    return intra.synth_bars(day, "09:30", to, **kw)


#: Stage 5ZU. Calm's requirement is about two bar sizes, and the gate can only answer the
#: second half if it is told where the entry quote is read from. These calls now say so.
#: Not offering it is reported UNVERIFIED rather than passed, which is why every Calm call in
#: this file had to be updated rather than left to "still pass".
def _calm_quote(day=None, last="10:00"):
    import pandas as _pd
    d = day if day is not None else DAY
    return _pd.date_range(d + _pd.Timedelta(hours=9, minutes=30),
                          d + _pd.Timedelta(hours=int(last[:2]), minutes=int(last[3:])),
                          freq="1min")


def test_b3_calm_a_passes_only_when_everything_it_reads_is_there():
    v = intra.validate("roska4_calm", _calm_frame(), now_et=DAY + pd.Timedelta(hours=10),
                       session_day=DAY, prior_session_day=PRIOR,
                       entry_quote_index=_calm_quote())
    assert v.allow, v.as_dict()
    assert v.codes == ()


def test_b3_calm_a_is_unverified_when_nobody_says_where_the_quote_comes_from():
    """The new half, and it must never read as a pass."""
    v = intra.validate("roska4_calm", _calm_frame(), now_et=DAY + pd.Timedelta(hours=10),
                       session_day=DAY, prior_session_day=PRIOR)
    assert not v.allow
    assert intra.ENTRY_QUOTE_UNVERIFIED in v.codes


def test_b3_stress_passes_inside_its_window():
    v = intra.validate("roska4_stress", _stress_frame(),
                       now_et=DAY + pd.Timedelta(hours=11), session_day=DAY,
                       ledger_status={"outcome": "complete", "observed_slots": 24,
                                      "expected_slots": 24})
    assert v.allow, v.as_dict()


@pytest.mark.parametrize("case,code", [
    ("empty", intra.NO_BARS),
    ("none", intra.NOT_A_FRAME),
    ("tz_utc", intra.TZ_MISMATCH),
    ("duplicate", intra.DUPLICATE_TIMESTAMPS),
    ("unsorted", intra.OUT_OF_ORDER),
    ("no_prior", intra.MISSING_SESSION),
    ("partial_today", intra.PARTIAL_COVERAGE),
    ("hole_today", intra.GAP_IN_COVERAGE),
    ("no_entry_quote", intra.ENTRY_QUOTE_ABSENT),
    ("too_early", intra.TOO_EARLY),
    ("too_late", intra.TOO_LATE),
])
def test_b3_calm_a_fails_closed_on_every_way_the_frame_can_be_wrong(case, code):
    now = DAY + pd.Timedelta(hours=10)
    df, prior = _calm_frame(), PRIOR
    # Stage 5ZU: every Calm call must say where the entry quote comes from, or the verdict is
    # UNVERIFIED and each case below would "fail" for a reason it is not about.
    quote = _calm_quote()
    if case == "empty":
        df = df.iloc[0:0]
    elif case == "none":
        df = None
    elif case == "tz_utc":
        df = _calm_frame(tz="UTC")
    elif case == "duplicate":
        df = pd.concat([df, df.iloc[[-1]]]).sort_index()
    elif case == "unsorted":
        df = df.iloc[list(range(len(df) - 2)) + [len(df) - 1, len(df) - 2]]
    elif case == "no_prior":
        df = intra.synth_bars(DAY, "09:30", "10:00")
    elif case == "partial_today":
        df = pd.concat([intra.synth_bars(PRIOR, "09:30", "16:00"),
                        intra.synth_bars(DAY, "09:45", "10:00")])
    elif case == "hole_today":
        today = intra.synth_bars(DAY, "09:30", "10:00")
        df = pd.concat([intra.synth_bars(PRIOR, "09:30", "16:00"), today.drop(today.index[3])])
    elif case == "no_entry_quote":
        # Stage 5ZU: the frame is COMPLETE for the decision (through 09:55) and the 10:00
        # OPEN is simply not readable yet. That is a different fact from the old
        # `no_decision_bar`, which conflated the two, and the refusal now says which.
        quote = _calm_quote(last="09:59")
    elif case == "too_early":
        now = DAY + pd.Timedelta(hours=9, minutes=45)
    elif case == "too_late":
        now = DAY + pd.Timedelta(hours=10, minutes=20)

    v = intra.validate("roska4_calm", df, now_et=now, session_day=DAY,
                       prior_session_day=prior, entry_quote_index=quote)
    assert v.allow is False, f"{case} was allowed"
    assert code in v.codes, (case, v.codes)


@pytest.mark.parametrize("case,code", [
    ("detector_partial", intra.PARTIAL_COVERAGE),
    ("detector_hole", intra.GAP_IN_COVERAGE),
    ("before_1035", intra.TOO_EARLY),
    ("after_1230", intra.TOO_LATE),
    ("stale", intra.STALE),
    ("ledger_incomplete", intra.WINDOW_UNOBSERVED),
])
def test_b3_stress_fails_closed_on_every_way_the_window_can_be_wrong(case, code):
    now = DAY + pd.Timedelta(hours=11)
    df = _stress_frame()
    ledger = {"outcome": "complete", "observed_slots": 24, "expected_slots": 24}
    if case == "detector_partial":
        df = intra.synth_bars(DAY, "09:45", "12:30")
    elif case == "detector_hole":
        full = _stress_frame()
        df = full.drop(full.index[5])
    elif case == "before_1035":
        now = DAY + pd.Timedelta(hours=10, minutes=30)
    elif case == "after_1230":
        now = DAY + pd.Timedelta(hours=12, minutes=45)
    elif case == "stale":
        df = intra.synth_bars(DAY, "09:30", "10:35")
    elif case == "ledger_incomplete":
        ledger = {"outcome": "incomplete", "observed_slots": 9, "expected_slots": 24}

    v = intra.validate("roska4_stress", df, now_et=now, session_day=DAY,
                       ledger_status=ledger)
    assert v.allow is False, f"{case} was allowed"
    assert code in v.codes, (case, v.codes)


def test_b3_an_unchecked_window_observation_says_so_rather_than_passing():
    v = intra.validate("roska4_stress", _stress_frame(),
                       now_et=DAY + pd.Timedelta(hours=11), session_day=DAY)
    obs = next(c for c in v.checks if c.name == "window_observation")
    assert obs.code == intra.OK
    assert "did not run" in obs.detail, \
        "an unsupplied check reported as a plain pass is the failure this wording prevents"


def test_b3_an_unknown_sleeve_is_refused_not_waved_through():
    # `roska4_swing` was the stand-in for "unknown" until Stage 5M-B gave it a requirement,
    # at which point this test was asserting about a sleeve the gate now knows. The property
    # is about an unknown sleeve, so the fixture has to be one that stays unknown — chosen
    # from outside the requirement table rather than named and hoped for.
    unknown = "sleeve_that_no_requirement_describes"
    assert unknown not in intra.REQUIREMENTS
    v = intra.validate(unknown, _stress_frame(), now_et=DAY + pd.Timedelta(hours=11))
    assert v.allow is False and intra.UNKNOWN_SLEEVE in v.codes


def test_b3_the_windows_agree_with_every_other_table_that_carries_them():
    """Since Stage 5N a sleeve's requirement is written in ITS OWN clock (`req.clock`), so
    the textual equality with the ET tables holds only for ET sleeves. For a session-clock
    sleeve the requirement must instead match `SESSION_WINDOWS` — same clock, same band —
    while the ledger and the ET table still agree with each other about the slot grid."""
    from global_index import window_ledger as wl
    for sleeve, req in intra.REQUIREMENTS.items():
        lo, hi = tp.WINDOWS_ET[sleeve]
        assert (wl.WINDOWS[sleeve]["start_et"], wl.WINDOWS[sleeve]["end_et"]) == (lo, hi)
        if req.clock == "America/New_York":
            assert (req.decide_from, req.decide_to) == (lo, hi), sleeve
            ok, _ = T.window_verdict(sleeve, pd.Timestamp(f"{DAY.date()} {req.decide_from}"))
            assert ok, sleeve
        else:
            assert (req.decide_from, req.decide_to) == tp.SESSION_WINDOWS[sleeve], sleeve
            assert tp.SESSION_WINDOW_CLOCKS[sleeve] == req.clock, sleeve
            ok, _ = T.window_verdict(
                sleeve, pd.Timestamp(f"{DAY.date()} {req.decide_from}", tz=req.clock))
            assert ok, sleeve


# ══════════════════════════════════════════════════════════════════════════════
# 3. LIVE_SLEEVE_SOURCE — one verdict per sleeve
# ══════════════════════════════════════════════════════════════════════════════
def test_sleeves_the_table_and_the_registry_cannot_disagree():
    assert ls.self_check() == []
    assert g.self_check() == []


def test_sleeves_each_one_has_a_named_call_chain_and_a_verdict():
    r = ls.readiness()
    assert set(r["sleeves"]) == set(tp.SLEEVE_INSTRUMENTS)
    # Stage 4 promoted the last two. All four now compute today's answer from today's bars.
    assert r["blocked"] == [], r["blocked"]
    assert sorted(r["live_ready"]) == sorted(tp.SLEEVE_INSTRUMENTS)
    for name, s in ls.SOURCES.items():
        assert s.call_chain, name
        assert s.anchor, name
        assert s.gap and len(s.gap) > 20, name
        assert s.kind == ls.COMPUTED_FROM_BARS, (name, s.kind)
        # Not "no side effects" — Stress scopes one and reverses it in a `finally`, which is a
        # different thing from what this blocker was ever about. What must be gone is any
        # sleeve that REPLACES a production symbol for the duration of its run.
        for eff in s.side_effects:
            assert "REPLACES" not in eff, (name, eff)
            assert not any(m in eff for m in ("futures.", "raits.")), (name, eff)
    # The other kinds stay in the vocabulary: they describe the states a future sleeve arrives
    # in, and deleting them would leave no way to say "not there yet".
    assert ls.FROZEN_INPUT in ls.SOURCE_KINDS and ls.ANCHORED_REGENERATION in ls.SOURCE_KINDS


def test_sleeves_stress_is_mnq_only_g3_q7_and_not_the_1020_candidate():
    chain = " ".join(ls.SOURCES["roska4_stress"].call_chain)
    assert "mnq_only_g3_q7" in chain
    assert "stress_liquidation_1020" not in chain
    # and the module that must NOT be used says so about itself
    other = Path("futures/stress_liquidation_1020.py")
    if other.exists():
        assert "not wired into" in other.read_text(encoding="utf-8")


def test_sleeves_calm_a_no_longer_depends_on_the_frozen_file():
    """The blocker was the CSV. Stage 4 removed the dependency, so the table must not still
    claim it — and the file itself stays on disk as the thing the detector is checked against."""
    s = ls.SOURCES["roska4_calm"]
    assert s.kind == ls.COMPUTED_FROM_BARS and s.live_ready is True
    assert s.frozen_inputs == (), s.frozen_inputs
    assert "track1_calm_a.detect" in " ".join(s.call_chain)
    assert Path("scratch/calm_pcloc_not_deep_gap_trade_list.csv").exists(), \
        "the artifact the detector is measured against is gone — the anchor is unverifiable"


def test_sleeves_normal_r4_replaces_nothing_any_more():
    """The blocker was the monkeypatching. The table must not still describe it as present."""
    s = ls.SOURCES["roska4_swing"]
    assert s.kind == ls.COMPUTED_FROM_BARS and s.live_ready is True
    assert s.side_effects == (), s.side_effects
    chain = " ".join(s.call_chain)
    assert "track1_normal_r4.run_instrument" in chain
    assert "model_sameday_stop" not in chain, "the root-level script is still in the chain"
    assert "COPY" in chain or "copy" in chain, \
        "the fill law must be applied to a copy, and the chain should say so"


@pytest.mark.skipif(os.environ.get("TRACK1_REGEN") != "1",
                    reason="regenerates through the shipped generator (~35s) in a subprocess; "
                           "opt in with TRACK1_REGEN=1")
def test_sleeves_normal_r4_regenerates_the_committed_rows_exactly():
    """Driven in a SUBPROCESS on purpose: the generator replaces five production symbols for
    the duration of its run, so calling it in the test process would leave the rest of the
    suite deciding against a patched engine."""
    code = (
        "import json,sys;sys.path.insert(0,'.');"
        "import scratch.track1_fill_shortgate_regen_20260822 as R;"
        "res=R.run_variant('artifact_gate_on','vault2026','spy_daily_live.csv');"
        "print('ANCHOR'+json.dumps(R.anchor(res,'vault2026')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(Path.cwd()), timeout=1800)
    assert out.returncode == 0, out.stderr[-2000:]
    line = next(l for l in out.stdout.splitlines() if l.startswith("ANCHOR"))
    anc = json.loads(line[len("ANCHOR"):])
    assert anc["all_ok"], anc
    assert anc["committed_total"] > 0, "nothing was compared — the anchor would pass empty"
    assert {r["inst"] for r in anc["rows"]} == {"MES", "MNQ", "MYM", "M2K", "MNKD"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. The Track 1 checkpoint and bootstrap
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def replay():
    import scratch.track1_replay_source_20260822 as src
    w = "vault2026"
    return w, src.candidates(w), src.early_exit_valuer(w)


def test_ckpt_resume_from_a_cut_instant_is_exact(replay):
    w, cands, val = replay
    for cut in ("2026-03-31", "2026-03-31 11:14:00-04:00"):
        r = boot.verify_resume(cands, cut=cut, early_exit_value=val)
        assert r["events_exact"], (cut, r["first_diff"])
        assert r["equity_exact"], cut
        assert r["events_head"] > 0 and r["events_tail"] > 0, \
            f"{cut}: one side is empty, so the split proves nothing"
        assert r["open_full"] == r["open_resumed"]
        assert r["cut_instant"], "no cut_instant was recorded"


def test_ckpt_the_carried_state_holds_everything_stage2c_proved_load_bearing(replay):
    w, cands, val = replay
    state, _head = boot.build(cands, cut="2026-03-31", window=w, early_exit_value=val)
    for key in ("equity", "peak_equity", "day_start_equity", "cur_day", "positions",
                "cut_instant", "booked_counter"):
        assert key in state, key
    assert state["positions"], "the cut carries no open position — the resume path is untested"
    for row in state["positions"]:
        for key in ("trade_id", "sleeve", "instrument", "direction", "qty", "risk_dollars"):
            assert key in row, key


@pytest.mark.parametrize("drop", ["cut_instant", "equity", "peak_equity", "positions"])
def test_ckpt_a_bootstrap_missing_a_carried_value_is_refused(replay, drop):
    w, cands, val = replay
    state, _ = boot.build(cands, cut="2026-03-31", early_exit_value=val)
    broken = dict(state)
    broken.pop(drop) if drop != "cut_instant" else broken.update(cut_instant=None)
    with pytest.raises(T.BootstrapRefused):
        T.restore(boot._fresh_book(), broken, cands)


def _tail_after(cands, val, state):
    b = boot._fresh_book()
    T.restore(b, state, cands)
    tail, _ = T.run_candidates(cands, book=b, early_exit_value=val,
                               resume_from=state["cut_instant"])
    return [T.event_key(x) for x in tail]


def test_ckpt_peak_and_positions_are_load_bearing_at_an_ordinary_cut(replay):
    """These two bind wherever anything is carried at all — raising the peak manufactures a
    drawdown the breaker reads, and dropping the positions frees the caps."""
    w, cands, val = replay
    state, _ = boot.build(cands, cut="2026-03-31", early_exit_value=val)
    base = _tail_after(cands, val, state)
    assert base, "the tail is empty — every mutation below would pass vacuously"

    lifted = json.loads(json.dumps(state))
    lifted["peak_equity"] = float(lifted["peak_equity"]) * 1.2
    assert _tail_after(cands, val, lifted) != base, "peak_equity is not load-bearing"

    forgotten = json.loads(json.dumps(state))
    forgotten["positions"] = []
    assert _tail_after(cands, val, forgotten) != base, "carried positions are not load-bearing"


#: (field, window, cut) — every pairing MEASURED by sweeping `binding_cuts()` rather than
#: assumed. All three windows produce a cut where all three fields bind; vault2026's first
#: binding cut happens to bind all three at once, which is why it carries three rows here.
BINDING = [
    ("cluster", "vault2026", "2026-01-26 14:30:00-05:00"),
    ("risk", "vault2026", "2026-01-26 14:30:00-05:00"),
    ("day_start_equity", "vault2026", "2026-01-26 14:30:00-05:00"),
    ("cluster", "vault2025", "2025-01-21 14:15:00-05:00"),
    ("risk", "vault2025", "2025-02-03 15:25:00-05:00"),
    ("day_start_equity", "vault2025", "2025-02-05 14:20:00+09:00"),
    # `equity` needs a cut where the book has GROWN, so resetting it to the account base
    # manufactures a drawdown large enough to cross a breaker threshold. At an early cut the
    # book is still near its base and the reset changes nothing — which is why "binds at any
    # cut" was the wrong claim, and measuring was the only way to find that out.
    ("equity", "vault2025", "2025-05-22 14:20:00-04:00"),
    ("equity", "vault2026", "2026-06-29 14:55:00-04:00"),
]


@pytest.mark.parametrize("field,window,cut", BINDING)
def test_ckpt_every_carried_field_is_load_bearing_at_a_cut_that_consults_it(
        field, window, cut):
    """Stage 2C could not make these two diverge and said so. The reason was the CUT, not the
    field.

    A carried position's cluster and risk are read by exactly one thing: the cap gate, when a
    SAME-CLUSTER candidate arrives while that position is still open. Stage 2C placed its cuts
    to make the breaker's peak bind — a few sessions before the deepest drawdown — and at
    those instants no same-cluster candidate followed before the carried position exited.
    Measured directly at the 2026-03-31 cut: both carried positions had ZERO same-cluster
    candidates arrive before they exited, so the fields were carried, restored and never
    consulted.

    `binding_cuts()` returns the instants where they ARE consulted, and at one of those both
    mutations diverge. So the honest verdict is not "not load-bearing" — it is "load-bearing,
    and here is the condition a cut has to satisfy to show it".
    """
    import scratch.track1_replay_source_20260822 as src
    cands, val = src.candidates(window), src.early_exit_valuer(window)
    assert pd.Timestamp(cut) in boot.binding_cuts(cands) or cut == "2022-01-10", \
        "the chosen cut is not one where a carried position's cluster is consulted again"

    state, _ = boot.build(cands, cut=cut, early_exit_value=val)
    assert state["positions"], f"{window} {cut}: nothing carried, so nothing to mutate"
    base = _tail_after(cands, val, state)
    assert base, "the tail is empty"

    m = json.loads(json.dumps(state))
    if field == "risk":
        for row in m["positions"]:
            row["risk_dollars"] = float(row["risk_dollars"]) * 20
    elif field == "cluster":
        for row in m["positions"]:
            row["sleeve"] = ("global_nkd" if row["sleeve"] != "global_nkd"
                             else "roska4_swing")
    elif field == "equity":
        m["equity"] = 50_000.0
    else:
        assert m.get("day_start_equity") is not None,             f"{window} {cut}: nothing carried in day_start_equity, so nothing to mutate"
        m["day_start_equity"] = float(m["day_start_equity"]) * 1.15
    assert _tail_after(cands, val, m) != base, (
        f"carried {field} did not bind at {window} {cut}, which was chosen because it should")


def test_ckpt_a_carried_field_that_is_never_consulted_is_reported_not_assumed(replay):
    """The other half of the finding above, pinned so it cannot quietly become folklore."""
    w, cands, val = replay
    state, _ = boot.build(cands, cut="2026-03-31", early_exit_value=val)
    cut = pd.Timestamp(state["cut_instant"])
    for row in state["positions"]:
        exit_ts = pd.Timestamp(row["exit_time"])
        same = [c for c in cands if c.sleeve == row["sleeve"]
                and cut < pd.Timestamp(c.entry_time) <= exit_ts]
        assert same == [], (
            "this cut now DOES consult a carried position's cluster, so the explanation "
            "above has changed and the test that depends on it must be re-read")


def test_ckpt_the_old_stage2b_bootstrap_is_still_refused_with_params_mismatch():
    old = Path("scratch/replay_checkpoint.track1.bootstrap_20260822.json")
    if not old.exists():
        pytest.skip("the Stage 2B bootstrap is not on disk")
    rows = entry.checkpoint_report(regime_csv="spy_daily_live.csv",
                                   data_paths=entry.default_data_paths(), path=str(old))
    swing = [r for r in rows if r["sleeve"] == "roska4_swing"]
    assert swing and all(r["code"] == rc.PARAMS_MISMATCH for r in swing), swing


def test_ckpt_a_new_bootstrap_under_track1_params_is_accepted(tmp_path, replay):
    """Written under the Track 1 identity, and accepted by `route_checkpoint.usable`.

    Small synthetic frames stand in for the 8-year parquet: the fingerprint is computed over
    whatever frame both sides are handed, so the mechanism under test — identity, route
    scoping, acceptance — is exercised without spending minutes reading 3.3 million rows.
    """
    w, cands, val = replay
    state, _ = boot.build(cands, cut="2026-03-31", window=w, early_exit_value=val)

    frames, paths = {}, {}
    for inst in ("MES", "MNQ", "MYM", "M2K", "MNKD"):
        idx = pd.date_range("2026-03-25", periods=40, freq="5min", tz="America/New_York")
        frames[inst] = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0,
                                     "close": 1.0, "volume": 1.0}, index=idx)
        f = tmp_path / f"{inst}.parquet"
        f.write_bytes(inst.encode())
        paths[inst] = str(f)

    entries = boot.checkpoint_entries(state, frames=frames, regime_csv="spy_daily_live.csv",
                                      data_paths=paths, fill_law=NR.NormalR4Params().fill_law)
    assert set(entries) == set(rc.CHECKPOINTED_SLEEVES)

    ck = tmp_path / "replay_checkpoint.track1.json"
    boot.write(state, entries=entries, book_path=str(tmp_path / "book.json"),
               checkpoint_path=str(ck))
    assert ck.exists()

    for sleeve, insts in entries.items():
        for inst in insts:
            got = boot.accepts(str(ck), sleeve=sleeve, inst=inst, frame=frames[inst],
                               regime_csv="spy_daily_live.csv", data_path=paths[inst],
                               fill_law=NR.NormalR4Params().fill_law)
            assert bool(got) is True, (sleeve, inst, getattr(got, "code", None),
                                       getattr(got, "detail", ""))

    # ...and a settings change is refused, with the code that names it.
    import global_index.track1_params as _tp
    real = _tp.sleeve_config

    def moved(sleeve, inst, **kw):
        cfg = real(sleeve, inst, **kw)
        cfg["ema_period"] = 999
        return cfg

    _tp.sleeve_config = moved
    try:
        got = boot.accepts(str(ck), sleeve="roska4_swing", inst="MES", frame=frames["MES"],
                           regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                           fill_law=NR.NormalR4Params().fill_law)
    finally:
        _tp.sleeve_config = real
    assert bool(got) is False and got.code == rc.PARAMS_MISMATCH


def test_ckpt_writing_the_route_never_touches_another_route(tmp_path, replay):
    w, cands, val = replay
    state, _ = boot.build(cands, cut="2026-03-31", early_exit_value=val)
    ck = tmp_path / "ck.json"
    ck.write_text(json.dumps({
        "schema_version": 2,
        "routes": {"someone_else": {"sleeves": {"roska4_swing": {"instruments": {
            "MES": {"route": "someone_else", "last_day": "2026-01-01"}}}}}}}),
        encoding="utf-8")
    frames = {"MES": pd.DataFrame({"open": [1.0]},
                                  index=pd.date_range("2026-03-25", periods=1, freq="5min"))}
    entries = boot.checkpoint_entries(state, frames=frames, regime_csv="spy_daily_live.csv",
                                      data_paths={"MES": str(tmp_path / "x.parquet")},
                                      fill_law=NR.NormalR4Params().fill_law)
    boot.write(state, entries=entries, book_path=str(tmp_path / "b.json"),
               checkpoint_path=str(ck))
    after = json.loads(ck.read_text(encoding="utf-8"))
    assert after["routes"]["someone_else"]["sleeves"]["roska4_swing"]["instruments"]["MES"][
        "last_day"] == "2026-01-01"
    assert tp.ROUTE in after["routes"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. Scheduler / dashboard parity
# ══════════════════════════════════════════════════════════════════════════════
def test_wiring_the_legacy_scheduler_and_its_dashboard_mirror_agree():
    r = slots.parity_report()
    assert r["scheduler_jobs"] > 50, "the scheduler produced almost no jobs — comparison empty"
    assert r["mirror_rows"] > 50
    assert r["in_parity"], {"only_in_scheduler": r["only_in_scheduler"],
                            "only_in_dashboard_mirror": r["only_in_dashboard_mirror"]}


def test_wiring_the_parity_check_can_actually_go_red(monkeypatch):
    monkeypatch.setitem(slots.MIRROR_EXEMPT, "stop_repair_0020", "pretend it is exempt")
    r = slots.parity_report()
    assert not r["in_parity"], "removing a job from the comparison changed nothing"


def test_wiring_the_id_to_label_aliases_are_still_needed_and_still_only_two():
    r = slots.parity_report()
    assert r["aliases_still_needed"] == sorted(slots.ID_TO_LOG_LABEL), (
        "a job named in the alias table no longer exists, or a new one diverged — either way "
        "the two namespaces have moved and the table has to be re-read")
    assert len(slots.ID_TO_LOG_LABEL) == 2


def test_wiring_track1_slots_are_declared_and_not_scheduled():
    """The count is DERIVED from the window table now, not pinned.

    It was `== 25` while Calm and Stress were the only sleeves. Stage 5M-B added 23 swing
    slots and the pin turned red for a change that was intended — which is the failure mode a
    literal always has. What the test is actually about is that each window's slots span it
    exactly and none is registered with the LEGACY scheduler, and both survive a new sleeve.
    """
    ids = slots.track1_slot_ids()
    expected = sum(_slots_in(lo, hi) for lo, hi in tp.WINDOWS_ET.values())
    assert len(ids) == expected, (len(ids), expected)
    assert {"TRACK1_CALM_DECIDE_0932", "TRACK1_CALM_OBSERVE_1002"} <= ids
    assert "TRACK1_CALM_1000" not in ids
    assert {"TRACK1_STRESS_1035", "TRACK1_STRESS_1230"} <= ids
    assert "TRACK1_STRESS_1235" not in ids, "a slot exists past the end of the window"
    assert {"TRACK1_SWING_1405", "TRACK1_SWING_1555"} <= ids
    assert "TRACK1_SWING_1600" not in ids, "a slot exists past the end of the window"
    live = slots.legacy_scheduler_slot_ids()
    assert not (ids & {j.upper() for j in live}), "a Track 1 slot is registered in a scheduler"
    assert slots.as_dict()["scheduled_live"] is False


def _slots_in(lo: str, hi: str) -> int:
    """How many 5-minute slots an inclusive ET window holds."""
    lo_h, lo_m = (int(x) for x in lo.split(":"))
    hi_h, hi_m = (int(x) for x in hi.split(":"))
    return ((hi_h * 60 + hi_m) - (lo_h * 60 + lo_m)) // 5 + 1


def test_wiring_the_stop_repair_sweep_inside_the_stress_window_is_named():
    from global_index import run_scheduler as rs
    assert list(slots.REQUIRED_ENTRY_WINDOW) == [(10, 35), (12, 30)]
    lo, hi = slots.REQUIRED_ENTRY_WINDOW
    clashing = [s for s in rs._REPAIR_SLOTS_FOR_TEST()] if hasattr(
        rs, "_REPAIR_SLOTS_FOR_TEST") else [(h, 20) for h in range(0, 24, 2)]
    inside = [s for s in clashing if lo <= s <= hi]
    assert inside == [(12, 20)], inside
    # and it is NOT yet excluded, which is exactly what the wiring gate is holding
    live = slots.legacy_scheduler_slot_ids()
    assert "stop_repair_1220" in live


def test_wiring_the_paper_output_policy_is_stated_per_channel():
    pol = slots.PAPER_OUTPUT_POLICY
    assert set(pol) == {"runner_events", "trade_log", "live_state", "slot_timing",
                        "window_coverage"}
    assert "SEPARATE" in pol["trade_log"], \
        "sharing trade_log without a reader change folds Track 1 into legacy's gates"


# ══════════════════════════════════════════════════════════════════════════════
# 6. The ledger cannot drift from the code
# ══════════════════════════════════════════════════════════════════════════════
LEDGER_JSON = Path("scratch/track1_blocking_ledger_20260822.json")


#: Fields `as_ledger()` computes by RUNNING a measurement, rather than reading the table.
#: They are a snapshot of a moment and a file cannot stay equal to them.
#:
#: Measured 2026-08-27: the ledger was regenerated at Stage 5ZR and had drifted again within
#: hours — the shadow-evidence count moved from two judgeable days to three, and the regime
#: verification went from "no record" to PASS when the 13:45 pre-flight ran. Neither is a
#: registry change; both are the world moving. A parity test that compares them is a test that
#: goes red on its own schedule, and one that people learn to regenerate past without reading.
#:
#: So the STATIC half is compared exactly — every id, status, evidence sentence, releasing flag
#: and dependency — and the live half is checked for SHAPE instead. A blocker losing its
#: measurement, or gaining one the ledger does not know about, still fails.
VOLATILE_LEDGER_KEYS = ("measured_now", "required_measurement_now", "blocking_now")


def _static(ledger: dict) -> dict:
    out = {k: v for k, v in ledger.items() if k not in VOLATILE_LEDGER_KEYS}
    out["blockers"] = [{k: v for k, v in b.items() if k not in VOLATILE_LEDGER_KEYS}
                       for b in ledger["blockers"]]
    return out


def test_ledger_matches_the_registry_exactly():
    assert LEDGER_JSON.exists(), "the ledger has not been generated"
    on_disk = json.loads(LEDGER_JSON.read_text(encoding="utf-8"))
    live = g.as_ledger()
    assert _static(on_disk) == _static(live), (
        "the ledger on disk and the registry in code disagree on something that is NOT a live "
        "measurement. The ledger is GENERATED from the registry; regenerate it rather than "
        "editing it.")


def test_ledger_carries_a_live_measurement_wherever_the_registry_declares_one():
    """The half the parity check can no longer compare, asserted by shape.

    A blocker that declares a measurement must carry its result, and one that declares none
    must not pretend to. That is what the exact comparison was really protecting, and it
    survives without pinning a number that changes by itself.
    """
    live = g.as_ledger()
    assert live["blockers"], "the ledger is empty"
    for row in live["blockers"]:
        blk = g.BLOCKERS[row["id"]]
        if blk.released_by_measurement:
            assert set(row["measured_now"]) == {"released", "detail"}, row["id"]
            assert isinstance(row["measured_now"]["released"], bool), row["id"]
            assert row["measured_now"]["detail"], f"{row['id']}: a verdict with no reason"
        else:
            assert row["measured_now"] is None, row["id"]
        if blk.also_requires_measurement:
            assert set(row["required_measurement_now"]) == {"satisfied", "detail"}, row["id"]
        else:
            assert row["required_measurement_now"] is None, row["id"]
    assert set(live["blocking_now"]) <= set(g.BLOCKERS), live["blocking_now"]


def test_ledger_has_no_status_outside_the_allowed_set():
    """Read from the registry rather than from a second copy of the list. Stage 4B added a
    third status and this test went red for naming two — which is the right kind of red, but
    it was red about its own hard-coded list rather than about the table."""
    for b in g.BLOCKERS.values():
        assert b.status in g.STATUSES, (b.id, b.status)
    assert "OPEN" not in g.STATUSES


def test_ledger_every_gate_is_releasable_and_every_closed_one_carries_evidence():
    assert g.self_check() == []
    gated = [b for b in g.BLOCKERS.values() if b.status == g.USER_DECISION_GATE]
    closed = [b for b in g.BLOCKERS.values() if b.status == g.CLOSED]
    assert gated and closed, "one side is empty — the distinction is not being exercised"
    for b in gated:
        assert b.released_by and b.decision_needed
    for b in closed:
        assert not b.blocks_orders and len(b.evidence) > 80


def test_ledger_the_markdown_names_every_blocker():
    md = Path("scratch/track1_blocking_ledger_20260822.md")
    assert md.exists()
    txt = md.read_text(encoding="utf-8")
    for b in g.BLOCKERS.values():
        assert b.id in txt, b.id


def test_ledger_releasing_every_gate_would_open_the_route(monkeypatch):
    """The whole set must be satisfiable. A ledger where some gate can never be released is a
    ledger that says 'never' while looking like 'not yet'."""
    flags = {f: True for b in g.BLOCKERS.values() for f in b.released_by}
    conf = g.Confirmations(flags, "test", "2026-03-02", "(synthetic)")

    # Satisfiable: sign every confirmation AND satisfy every measurement, and the route opens.
    # Generalised over MEASUREMENTS in Stage 5S rather than naming one, so adding a measured
    # gate cannot silently make the whole set unsatisfiable while this still passes.
    assert g.MEASUREMENTS, "no measurements at all — this test would prove nothing"
    for name in list(g.MEASUREMENTS):
        monkeypatch.setitem(g.MEASUREMENTS, name,
                            lambda root="": (True, "satisfied for this test"))
    ok, reasons = g.may_enable_orders(conf)
    assert ok, reasons

    # And not satisfiable by signatures ALONE. Hold EACH measurement shut in turn and the same
    # set of flags must fail on exactly that gate — otherwise a gate built to be unsignable has
    # become signable, or one has stopped holding at all.
    #
    # Stage 5ZQ introduced a SECOND kind of measurement and this loop did not know about it.
    # `released_by_measurement` is an OR: the measurement passing OPENS the gate. The new
    # `also_requires_measurement` is an AND: the measurement passing is REQUIRED even once the
    # gate has been signed. A measurement of the second kind releases nothing by itself, so
    # the old `expected` came back empty and this test fired — correctly, on its own terms.
    #
    # Both kinds are now covered, and the claim is the same for both: hold this measurement
    # shut and exactly the gates that depend on it must be the ones still refusing. For an
    # AND-measurement that is the stronger statement, because the gate is refusing WITH every
    # signature already granted.
    for name in list(g.MEASUREMENTS):
        opens = [b.id for b in g.BLOCKERS.values()
                 if b.released_by_measurement == name and b.blocks_orders]
        required_by = [b.id for b in g.BLOCKERS.values()
                       if b.also_requires_measurement == name and b.blocks_orders]
        expected = sorted(opens + required_by)
        assert expected, (f"{name} neither releases nor is required by any order-blocking "
                          f"gate — it is a measurement nothing consults")
        monkeypatch.setitem(g.MEASUREMENTS, name,
                            lambda root="": (False, "held shut for this test"))
        ok, reasons = g.may_enable_orders(conf)
        assert not ok, name
        assert sorted(r.split(":")[0] for r in reasons) == expected, (name, reasons)
        monkeypatch.setitem(g.MEASUREMENTS, name,
                            lambda root="": (True, "satisfied for this test"))

    # A waiver flag must not be able to stand in for a signature. Granting ONLY the waivers,
    # with every measurement held shut, must open nothing — otherwise the escape hatch built
    # for "the broker could not be reached" has become a way in.
    waivers = {b.waiver_flag: True for b in g.BLOCKERS.values() if b.waiver_flag}
    if waivers:
        for name in list(g.MEASUREMENTS):
            monkeypatch.setitem(g.MEASUREMENTS, name,
                                lambda root="": (False, "held shut for this test"))
        ok, _ = g.may_enable_orders(g.Confirmations(waivers, "test", "2026-03-02", "(synth)"))
        assert not ok, "waivers alone opened the route"
