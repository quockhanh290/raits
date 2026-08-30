"""Stage 5ZA — causal slot audit after the paper-path stages.

The failure shape this file guards:

    a slot runs every five minutes, but the gate or detector asks for the end of the
    window/session anyway.

Stage 5V-1 fixed that for the two scanning sleeves. This suite sweeps all 70 strategy slots
and a few adjacent seams so the next copy is caught before a live window has to find it.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from collections import Counter, defaultdict

import pandas as pd

from global_index import track1_intraday as intra
from global_index import track1_live_source as live
from global_index import track1_normal_r4 as normal
from global_index import track1_paper_callsite as callsite
from global_index import track1_slots as slots
from global_index import track1_stress_mnq as stress


ET = "America/New_York"
DAY_ET = pd.Timestamp("2026-08-26")


def _slot_now(slot, *, seconds: int = 3) -> pd.Timestamp:
    return pd.Timestamp(
        f"{DAY_ET.date()} {slot.hour:02d}:{slot.minute:02d}:{seconds:02d}",
        tz=ET,
    )


def _local_day(now: pd.Timestamp, clock: str) -> pd.Timestamp:
    return now.tz_convert(clock).tz_localize(None).normalize()


def _hhmm(ts: pd.Timestamp) -> str:
    return f"{ts.hour:02d}:{ts.minute:02d}"


def _frame_owed_by_slot(sleeve: str, now: pd.Timestamp) -> pd.DataFrame:
    """A minimal frame that contains exactly what the slot is entitled to require."""
    req = intra.REQUIREMENTS[sleeve]
    local_now = now.tz_convert(req.clock).tz_localize(None)
    day = _local_day(now, req.clock)
    # Stage 5ZU: the span the DECISION is entitled to require, which for Calm now ends before
    # the bar its entry is priced at rather than on it.
    hi = req.required_context_through or req.today_to
    closed = intra._last_closed_bar(local_now, req.bar_minutes)
    if req.today_to_follows_now:
        declared = day + intra._hhmm(req.today_to)
        hi = _hhmm(min(declared, closed))
    else:
        # The fixed-span sleeves still need the frame to reach the slot for the staleness
        # check. Stress is the important case: the detector's setup span ends at 10:30, but
        # a 12:00 slot must still prove it is not deciding from a 10:30-only frame.
        declared = day + intra._hhmm(req.today_to)
        hi = _hhmm(max(declared, closed))

    today = intra.synth_bars(day, req.today_from, hi, req.bar_minutes)
    if not req.needs_prior_rth:
        return today

    prior = intra._prev_business_day(day)
    prior_frame = intra.synth_bars(prior, req.prior_from, req.prior_to, req.bar_minutes)
    return pd.concat([prior_frame, today]).sort_index()


def test_inventory_is_the_full_four_sleeve_strategy_route():
    counts = Counter(s.sleeve for s in slots.TRACK1_SLOTS)
    assert counts == {
        "roska4_calm": 1,
        "roska4_stress": 24,
        "roska4_swing": 23,
        "global_nkd": 22,
    }
    assert len(slots.TRACK1_SLOTS) == 70


def _quote_index(sleeve: str, now: pd.Timestamp):
    """Where the sleeve's fill reference is read from, or None when it declares none.

    Stage 5ZU. A sleeve may price its entry on a different bar size from the one it decides
    on, and the gate reports UNVERIFIED — never a pass — when nobody says where that price
    comes from. Every validate call in this suite offers it, so each assertion keeps testing
    what its name says.
    """
    req = intra.REQUIREMENTS[sleeve]
    if req.required_entry_quote_time is None:
        return None
    day = _local_day(now, req.clock)
    return pd.date_range(day + intra._hhmm(req.today_from),
                         day + intra._hhmm(req.required_entry_quote_time), freq="1min")


def test_every_strategy_slot_accepts_the_bars_it_can_causally_require():
    """No slot may demand bars past its own instant.

    This is the executable version of the operational question: a 10:35 slot should be able
    to run at 10:35:03, and a 14:05 slot should not wait until 15:55.
    """
    failures = {}
    for slot in slots.TRACK1_SLOTS:
        now = _slot_now(slot)
        frame = _frame_owed_by_slot(slot.sleeve, now)
        req = intra.REQUIREMENTS[slot.sleeve]
        v = intra.validate(
            slot.sleeve,
            frame,
            now_et=now,
            session_day=_local_day(now, req.clock),
            prior_session_day=intra._prev_business_day(_local_day(now, req.clock)),
            entry_quote_index=_quote_index(slot.sleeve, now),
        )
        bad = set(v.codes) & {intra.PARTIAL_COVERAGE, intra.STALE}
        if bad or not v.allow:
            failures[slot.id] = v.as_dict()
    assert failures == {}


def test_calm_one_shot_has_dispatch_grace_but_not_a_late_entry():
    slot = next(s for s in slots.TRACK1_SLOTS if s.id == "TRACK1_CALM_1000")
    frame = _frame_owed_by_slot(slot.sleeve, _slot_now(slot, seconds=3))

    inside = intra.validate(
        "roska4_calm",
        frame,
        now_et=_slot_now(slot, seconds=3),
        session_day=DAY_ET,
        prior_session_day=intra._prev_business_day(DAY_ET),
        entry_quote_index=_quote_index("roska4_calm", _slot_now(slot, seconds=3)),
    )
    assert inside.allow, inside.as_dict()

    # One second past the DECLARED grace, read from the requirement rather than written here.
    # Stage 5ZU widened Calm's grace to 180s so the sleeve can see the closed one-minute bar
    # its entry is priced from; the hard-coded 10:01:01 was inside the new window and would
    # have made this test assert the opposite of its own name.
    grace = intra.REQUIREMENTS["roska4_calm"].decision_grace_seconds
    late_now = _slot_now(slot, seconds=0) + pd.Timedelta(seconds=grace + 1)
    late = intra.validate(
        "roska4_calm",
        frame,
        now_et=late_now,
        session_day=DAY_ET,
        prior_session_day=intra._prev_business_day(DAY_ET),
        entry_quote_index=_quote_index("roska4_calm", late_now),
    )
    assert not late.allow
    assert late.codes == (intra.TOO_LATE,)


def test_only_scanning_sleeves_move_their_span_high_bound_with_the_slot():
    follows = {k for k, r in intra.REQUIREMENTS.items() if r.today_to_follows_now}
    assert follows == {"roska4_swing", "global_nkd"}


def _calls_with_keyword(fn, callee: str, keyword: str, name: str) -> int:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = getattr(node.func, "id", None)
        if called != callee:
            continue
        for kw in node.keywords:
            if kw.arg == keyword and isinstance(kw.value, ast.Name) and kw.value.id == name:
                count += 1
    return count


def test_live_source_fetches_each_sleeve_through_the_slot_instant():
    assert _calls_with_keyword(live.LiveTrack1Source._calm_candidates, "sleeve_frames",
                               "through", "now") == 1
    assert _calls_with_keyword(live.LiveTrack1Source._swing_candidates, "sleeve_frames",
                               "through", "now") == 1
    assert _calls_with_keyword(live.LiveTrack1Source._nkd_candidates, "sleeve_frames",
                               "through", "now") == 1
    assert _calls_with_keyword(live.LiveTrack1Source._stress_candidates, "live_frames",
                               "through", "now") == 1


def test_detectors_truncate_to_the_slot_instant_not_the_window_end():
    stress_src = inspect.getsource(stress.detect_entry_for_slot)
    normal_src = inspect.getsource(normal.detect_entry_for_slot)
    assert "end = min(end, hhmm)" in stress_src
    assert "widx_naive <= now_ts" in normal_src
    assert "win = win[widx_naive <= now_ts]" in normal_src


def test_calm_live_detector_is_entry_only_not_full_day_replay():
    src = inspect.getsource(live.LiveTrack1Source._calm_candidates)
    assert "detect_entry_for_day" in src
    assert ".detect(" not in src
    setup_src = inspect.getsource(__import__("global_index.track1_calm_a",
                                             fromlist=["detect_entry_for_day"])
                                  .detect_entry_for_day)
    assert "exit_time=None" in setup_src


def test_paper_callsite_seam_is_the_scheduler_slot_path():
    seam = callsite.seam()
    assert seam["function"] == "observe_live_slot"
    assert "run_candidates" in seam["anchor"]
    assert "not what the scheduler runs" in seam["not_run_shadow"]


def test_slot_ids_are_unique_per_sleeve_and_five_minute_window_cadence_holds():
    by_sleeve = defaultdict(list)
    for s in slots.TRACK1_SLOTS:
        by_sleeve[s.sleeve].append(s)
    assert len({s.id for s in slots.TRACK1_SLOTS}) == len(slots.TRACK1_SLOTS)
    for sleeve, ss in by_sleeve.items():
        if sleeve == "roska4_calm":
            continue
        minutes = [s.hour * 60 + s.minute for s in ss]
        assert [b - a for a, b in zip(minutes, minutes[1:])] == [5] * (len(minutes) - 1)
