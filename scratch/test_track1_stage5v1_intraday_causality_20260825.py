"""Stage 5V-1 / 5R-2 — the NKD intraday gate must not require bars from the future.

READ-ONLY of production data. No broker, no order, no confirmation file, no runtime write.

What was measured live
----------------------
On 2026-08-25 nineteen consecutive `global_nkd` slots wrote
`gate_refused / partial_coverage,stale` while holding 107 contiguous bars of the session.
Both codes came from `track1_intraday.validate` — `run_live_day_track1` builds `detail` as
`",".join(verdict.codes)` from that call and nothing else — and both had the same root cause:
a grid-quantised frame compared against a continuous instant.

    partial_coverage   `today_span` demanded bars to `today_to` = 15:55 for EVERY slot, so a
                       14:10 slot required 105 minutes that had not happened.
    stale              the staleness check compared `last + bar_minutes` against raw `now`.
                       A slot fires ~3s after its minute, so the newest complete 5-minute
                       bucket is exactly one bar back and the test failed BY THOSE SECONDS:
                       "last bar 15:45 is more than one 5-minute bar behind 15:50:03".

The fix is one idea used twice: `_last_closed_bar(now, n)` — the newest grid point whose bar
must certainly have finished. The span's high bound follows it (for scanning sleeves only) and
the staleness horizon is it. Written once so the two cannot disagree about which bar is owed.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(r"d:\raits")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_intraday as intra   # noqa: E402

DAY = pd.Timestamp("2026-08-25")
JST = "Asia/Tokyo"
ET = "America/New_York"


def nkd_frame(hi: str, lo: str = "14:00"):
    return intra.synth_bars(DAY, lo, hi, 5, tz=JST)


def at_jst(hhmm: str, secs: int = 3):
    """A slot instant: its own minute plus the seconds a subprocess takes to get there."""
    return pd.Timestamp(f"2026-08-25 {hhmm}", tz=JST) + pd.Timedelta(seconds=secs)


# ══════════════════════════════════════════════════════════════════════════════
# the six things the stage had to prove
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("hhmm", ["14:15", "14:35", "15:00", "15:30", "15:50"])
def test_1_a_frame_ending_at_the_slot_passes_for_that_slot(hhmm):
    """1 + 5. A frame holding 14:00..now satisfies the gate, and no slot before 15:55 needs a
    bar that has not happened."""
    v = intra.validate("global_nkd", nkd_frame(hhmm), now_et=at_jst(hhmm))
    assert v.allow is True, (hhmm, v.codes, [c.detail for c in v.checks if c.refuses])


@pytest.mark.parametrize("later", ["15:00", "15:30", "15:50"])
def test_2_the_same_frame_does_not_pass_for_a_later_slot(later):
    v = intra.validate("global_nkd", nkd_frame("14:35"), now_et=at_jst(later))
    assert v.allow is False
    assert intra.STALE in v.codes, v.codes


def test_3_a_hole_inside_the_span_still_refuses():
    b = nkd_frame("14:35").drop(index=[pd.Timestamp("2026-08-25 14:15", tz=JST)])
    v = intra.validate("global_nkd", b, now_et=at_jst("14:35"))
    assert v.allow is False
    assert intra.GAP_IN_COVERAGE in v.codes, v.codes


def test_3b_a_frame_starting_late_still_refuses_partial_coverage():
    """The low bound is NOT dynamic — the scan reads from 14:00 and that is still demanded."""
    v = intra.validate("global_nkd", nkd_frame("14:35", lo="14:10"), now_et=at_jst("14:35"))
    assert v.allow is False
    assert intra.PARTIAL_COVERAGE in v.codes, v.codes


@pytest.mark.parametrize("bars_behind", [1, 2, 6])
def test_4_a_frame_more_than_one_bar_behind_the_slot_is_stale(bars_behind):
    now = at_jst("15:00")
    end = (pd.Timestamp("2026-08-25 15:00", tz=JST)
           - pd.Timedelta(minutes=5 * bars_behind))
    v = intra.validate("global_nkd", nkd_frame(end.strftime("%H:%M")), now_et=now)
    if bars_behind == 1:
        # exactly one bar back IS the newest bar that must have closed — not stale
        assert v.allow is True, v.codes
    else:
        assert intra.STALE in v.codes, (bars_behind, v.codes)


def test_the_three_second_slot_latency_no_longer_reads_as_stale():
    """The live defect, reproduced exactly. A slot firing 3s after its minute holds a frame
    whose newest complete bucket is one bar back; that is not staleness, it is arithmetic."""
    frame = nkd_frame("15:45")
    v = intra.validate("global_nkd", frame, now_et=at_jst("15:50", secs=3))
    assert v.allow is True, v.codes
    assert [c.code for c in v.checks if c.name == "staleness"] == [intra.OK]


def test_5_no_slot_before_the_close_requires_a_future_bar():
    """Walk every five-minute slot in the band with a frame that reaches exactly that slot."""
    t = pd.Timestamp("2026-08-25 14:10", tz=JST)
    # 15:50 is the last slot that can DECIDE. The 15:55 one fires about three seconds after
    # `decide_to` and is refused `too_late` — pre-existing, deliberate, and benign: the
    # acceptance gate classifies it `observed_window_shut`, which is an OBSERVED class rather
    # than a failure. Asserted below rather than walked over.
    end = pd.Timestamp("2026-08-25 15:50", tz=JST)
    checked = 0
    while t <= end:
        hhmm = t.strftime("%H:%M")
        v = intra.validate("global_nkd", nkd_frame(hhmm), now_et=t + pd.Timedelta(seconds=3))
        assert v.allow is True, (hhmm, v.codes)
        checked += 1
        t += pd.Timedelta(minutes=5)
    assert checked == 21, checked


def test_the_final_slot_of_the_band_has_dispatch_grace_then_window_shut():
    """It fires ~3s after `decide_to`, so it can never decide — and that must count as
    OBSERVED, or a window could never be complete."""
    from global_index import track1_shadow_acceptance as acc
    v = intra.validate("global_nkd", nkd_frame("15:50"), now_et=at_jst("15:55"))
    assert v.allow is True and v.codes == ()
    late = intra.validate("global_nkd", nkd_frame("15:50"),
                          now_et=at_jst("15:56", secs=1))
    assert late.allow is False and late.codes == (intra.TOO_LATE,)
    row = {"decided": False, "reason": "gate_refused", "detail": ",".join(late.codes)}
    assert acc.classify_slot_row(row) == acc.SLOT_WINDOW_SHUT
    assert acc.SLOT_WINDOW_SHUT in acc.OBSERVED_CLASSES


def test_the_live_refusal_codes_were_a_HARD_refusal_which_is_why_it_mattered():
    """`partial_coverage,stale` classifies as observed_hard_refusal — the class that makes a
    sleeve `slot_could_not_evaluate` and the window FAIL."""
    from global_index import track1_shadow_acceptance as acc
    row = {"decided": False, "reason": "gate_refused", "detail": "partial_coverage,stale"}
    assert acc.classify_slot_row(row) == acc.SLOT_HARD_REFUSAL


# ══════════════════════════════════════════════════════════════════════════════
# the other three sleeves must not move
# ══════════════════════════════════════════════════════════════════════════════

def _calm_frames(today_hi: str):
    prior = intra.synth_bars(DAY - pd.Timedelta(days=1), "09:30", "16:00", 5)
    return pd.concat([prior, intra.synth_bars(DAY, "09:30", today_hi, 5)])


def _calm_quote(last="10:00"):
    """The MINUTE index the 10:00 OPEN is read from — the second half of Calm's contract.

    Stage 5ZU split the one thing this sleeve declared into two: the span the DECISION reads
    (through 09:55) and the bar whose OPEN it transacts at (10:00, read from a closed
    one-minute bar). Every call here now says which minutes exist, because a gate that was
    not told cannot answer, and answering anyway is what the old contract did.
    """
    return pd.date_range(f"{DAY} 09:30", f"{DAY} {last}", freq="1min", tz=ET)


def test_calm_still_needs_its_declared_bar_and_the_prior_rth():
    at = pd.Timestamp("2026-08-25 10:00", tz=ET)
    ok = intra.validate("roska4_calm", _calm_frames("09:55"), now_et=at,
                        entry_quote_index=_calm_quote("10:00"))
    assert ok.allow is True, ok.codes
    assert "6 bars 09:30-09:55 contiguous" in [
        c.detail for c in ok.checks if c.name == "today_span"][0]

    # the span the DECISION reads must still be complete
    short = intra.validate("roska4_calm", _calm_frames("09:45"), now_et=at,
                           entry_quote_index=_calm_quote("10:00"))
    assert short.allow is False
    assert intra.PARTIAL_COVERAGE in short.codes or intra.STALE in short.codes

    # and the entry quote must exist, as its own distinct refusal
    no_quote = intra.validate("roska4_calm", _calm_frames("09:55"), now_et=at,
                              entry_quote_index=_calm_quote("09:59"))
    assert no_quote.allow is False
    assert intra.ENTRY_QUOTE_ABSENT in no_quote.codes
    assert intra.DECISION_BAR_ABSENT not in no_quote.codes

    # not offering the index at all is UNVERIFIED, never a pass
    unasked = intra.validate("roska4_calm", _calm_frames("09:55"), now_et=at)
    assert unasked.allow is False
    assert intra.ENTRY_QUOTE_UNVERIFIED in unasked.codes

    no_prior = intra.validate("roska4_calm", intra.synth_bars(DAY, "09:30", "09:55", 5),
                              now_et=at, entry_quote_index=_calm_quote("10:00"))
    assert no_prior.allow is False and intra.MISSING_SESSION in no_prior.codes


def test_stress_still_needs_the_whole_setup_span():
    at = pd.Timestamp("2026-08-25 10:35", tz=ET)
    ok = intra.validate("roska4_stress", intra.synth_bars(DAY, "09:30", "10:30", 5), now_et=at)
    assert ok.allow is True, ok.codes
    short = intra.validate("roska4_stress", intra.synth_bars(DAY, "09:30", "10:20", 5),
                           now_et=at)
    assert short.allow is False
    assert intra.PARTIAL_COVERAGE in short.codes, short.codes


def test_swing_scans_from_1400_to_now_and_not_beyond():
    """Swing has the same shape as NKD and had the same defect. Its 14:00 low bound is
    untouched; only the future half of the span is."""
    v = intra.validate("roska4_swing", intra.synth_bars(DAY, "14:00", "14:30", 5),
                       now_et=pd.Timestamp("2026-08-25 14:30", tz=ET) + pd.Timedelta(seconds=3))
    assert v.allow is True, v.codes
    late_start = intra.validate("roska4_swing", intra.synth_bars(DAY, "14:15", "14:30", 5),
                                now_et=pd.Timestamp("2026-08-25 14:30", tz=ET))
    assert late_start.allow is False and intra.PARTIAL_COVERAGE in late_start.codes


def test_only_the_two_scanning_sleeves_follow_the_slot():
    follows = {k for k, r in intra.REQUIREMENTS.items() if r.today_to_follows_now}
    assert follows == {"roska4_swing", "global_nkd"}, follows
    # and the two that do not are exactly the ones whose today_to is a bar or a past level.
    #
    # Stage 5ZU: for Calm that bar is now named `required_entry_quote_time` — the OPEN the
    # entry transacts at — and it is no longer the bar the DECISION waits to close. The claim
    # is unchanged in substance and now says which of the two it means.
    calm = intra.REQUIREMENTS["roska4_calm"]
    assert calm.today_to == calm.required_entry_quote_time
    assert calm.required_context_through < calm.required_entry_quote_time
    assert calm.decision_bar is None, "the closed-bar requirement is back"
    assert (intra.REQUIREMENTS["roska4_stress"].today_to
            < intra.REQUIREMENTS["roska4_stress"].decide_from)


# ══════════════════════════════════════════════════════════════════════════════
# the shared arithmetic
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("now,want", [
    ("14:12:00", "14:05"), ("14:10:03", "14:05"), ("14:15:00", "14:10"),
    ("14:14:59", "14:05"), ("15:50:03", "15:45"),
])
def test_last_closed_bar_is_one_whole_bar_back_from_the_floor(now, want):
    got = intra._last_closed_bar(pd.Timestamp(f"2026-08-25 {now}"), 5)
    assert got == pd.Timestamp(f"2026-08-25 {want}"), (now, got)


def test_the_span_and_the_staleness_rule_share_one_function():
    """Two rules about "which bar does the frame owe" that could disagree would be two rules.
    Parsed, not grepped."""
    tree = ast.parse(Path(intra.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "validate")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_last_closed_bar"]
    assert len(calls) == 2, f"expected the span and staleness to share it, found {len(calls)}"


def test_the_tokyo_clock_is_still_the_one_used():
    """The 13-hour class of error. `now` must be read on the requirement's own clock."""
    frame = nkd_frame("15:00")
    # the same instant expressed two ways must give the same verdict
    a = intra.validate("global_nkd", frame, now_et=at_jst("15:00"))
    same = pd.Timestamp("2026-08-25 15:00:03", tz=JST).tz_convert(ET)
    b = intra.validate("global_nkd", frame, now_et=same)
    assert a.allow == b.allow is True
    assert a.codes == b.codes


# ══════════════════════════════════════════════════════════════════════════════
# nothing else moved
# ══════════════════════════════════════════════════════════════════════════════

def test_the_live_ledger_rows_are_explained_and_untouched():
    """The 2026-08-25 NKD rows were written by the OLD code and refused. Nothing was
    backfilled, edited or re-written.

    Scoped to `global_nkd`, and that scoping is the point. Stage 5W pinned the whole file at
    22 rows because the NKD *window* had closed — but the file is the whole DAY's ledger, and
    Stress began writing into it at 11:11 ET, so the exact count broke the moment another
    sleeve ran. The window being final does not make the file final.

    Same family as pinning a line count on a log that is still being appended to. The
    distribution of the CLOSED window is the durable fact; the size of the file it lives in
    is not.
    """
    import collections
    import json
    p = REPO / "global_index/track1_runtime/window_coverage/window_coverage_20260825.jsonl"
    if not p.exists():
        pytest.skip("no live ledger in this checkout")
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    nkd = [r for r in rows if r.get("sleeve") == "global_nkd"]
    assert [r for r in nkd if r.get("event") == "window_closed"], (
        "the NKD window is still open; this test pins a closed window")

    obs = [r for r in nkd if r.get("event") == "slot_observed"]
    assert len(obs) == 22, len(obs)
    assert all(r.get("decided") is False for r in obs)
    assert all(r.get("reason") == "gate_refused" for r in obs)

    dist = collections.Counter(str(r.get("detail")) for r in obs)
    assert dist == {"partial_coverage,stale": 20, "stale": 1, "too_late": 1}, dist

    # and the two classes are what the acceptance gate makes of them: the 21 hard refusals
    # are why this window cannot pass, and the single `too_late` is the benign window-shut
    # code that predates this stage.
    hard = sum(v for k, v in dist.items() if k != "too_late")
    assert hard == 21


def test_the_ledger_file_is_shared_by_every_sleeve_of_the_day():
    """The fact that broke the test above, pinned so it cannot surprise anyone again.

    One file per DAY, not per window. A test that pins its length is pinning something that
    keeps changing until the last sleeve of the day has finished.
    """
    import json
    p = REPO / "global_index/track1_runtime/window_coverage/window_coverage_20260825.jsonl"
    if not p.exists():
        pytest.skip("no live ledger in this checkout")
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    sleeves = {r.get("sleeve") for r in rows}
    assert "global_nkd" in sleeves
    assert all(str(r.get("date")) == "2026-08-25" for r in rows)


def test_orders_are_still_impossible():
    import os
    from global_index import track1_gates as gates
    blocking = {b.id for b in gates.blocking()}
    assert "B1_broker_account_or_legacy_retirement" in blocking
    assert "PAPER_SHADOW_EVIDENCE" in blocking
    assert gates.may_enable_orders()[0] is False
    assert not Path(gates.CONFIRMATION_PATH).exists()
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "")


def test_no_scheduler_or_ops_path_requests_orders():
    for f in ("global_index/run_scheduler.py", "monitor/ops.py"):
        tree = ast.parse((REPO / f).read_text(encoding="utf-8"))
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
                    and n.value == "--allow-orders"], f
