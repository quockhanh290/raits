"""Stage 5ZZZ-BW. One sleeve-day in eighteen carried the wrong word, and it was the catch-all.

Swept every sleeve against every session on disk -- six sessions, three sleeves, eighteen
pairs. Seventeen were right:

    13  complete   / ledger complete
     3  incomplete / ledger incomplete   (27/08 Stress 18/24, 25/08 NKD 0/22, 25/08 Stress 17/24)
     1  waiting    / ledger unobserved   (today's Swing, 0/23 -- its window had not opened)

The eighteenth was Swing on 2026-08-28: nine of twenty-three slots observed, no closing
record, printed UNKNOWN in amber. `unknown` is this module's catch-all for "there is no name
for this", and the panel had a name for it -- the ledger's own.

`unobserved` means no `window_closed` record exists. The ledger fail-closes on purpose: "a
window that opened and then vanished is not in progress after the fact, it is a window nobody
can vouch for." That is a DIFFERENT fact from `incomplete`, where the window did close and
counted fewer slots than expected. One says the coverage is short; the other says nobody can
attest to it at all, and an operator chases those two in different directions.

The only thing separating the seventeenth case from the eighteenth is the clock, which is why
the ordering below is the whole fix: the hours before a window opens still belong to
`waiting`, so a sleeve is never accused of losing a closing record it was not yet due to write.
"""
from __future__ import annotations

import pytest

from monitor.backend import track1_market_view as MV

SPEC = {"window_start": "14:05", "window_end": "15:55"}


def _slots(observed: int, total: int = 23) -> list:
    return ([{"status": MV.SLOT_NO_SIGNAL} for _ in range(observed)]
            + [{"status": MV.SLOT_MISSED} for _ in range(total - observed)])


def _cov(outcome: str, observed: int, total: int = 23) -> dict:
    return {"outcome": outcome, "observed_slots": observed, "expected_slots": total,
            "reason": "no window_closed record - absence is the signal"}


def test_a_closed_window_with_no_closing_record_keeps_the_ledgers_word():
    """The measured case: Swing on 2026-08-28, nine of twenty-three, printed UNKNOWN."""
    got = MV._sleeve_status(_slots(9), _cov("unobserved", 9), SPEC, "23:59")
    assert got == MV.ST_UNOBSERVED, got
    assert got != MV.ST_UNKNOWN


def test_before_the_window_opens_the_same_ledger_verdict_is_still_waiting():
    """The seventeenth case, and the reason the branch ORDER is the fix. A sleeve whose window
    has not come must not be accused of losing a closing record it was never due to write."""
    got = MV._sleeve_status(_slots(0), _cov("unobserved", 0), SPEC, "12:55")
    assert got == MV.ST_WAITING, got


def test_a_window_that_closed_short_is_incomplete_not_unobserved():
    """The distinction the new branch exists to preserve. The ledger closed this window and
    counted eighteen of twenty-four; that is a short session, not an unvouched one."""
    got = MV._sleeve_status(_slots(18, 24), _cov("incomplete", 18, 24), SPEC, "23:59")
    assert got == MV.ST_INCOMPLETE, got


def test_a_window_that_closed_full_is_complete():
    """The common case must not move."""
    got = MV._sleeve_status(_slots(23), _cov("complete", 23), SPEC, "23:59")
    assert got == MV.ST_COMPLETE, got


def test_unknown_is_still_reachable_as_the_real_catch_all():
    """Naming one case must not empty the catch-all. A sleeve with slots decided, no future
    slots left and NO ledger verdict at all is genuinely unnamed, and saying so is right."""
    got = MV._sleeve_status(_slots(23), _cov("", 23), SPEC, "23:59")
    assert got == MV.ST_UNKNOWN, got


def test_a_sleeve_still_inside_its_window_reads_live():
    """The transition the operator watches: waiting, then live, then complete."""
    got = MV._sleeve_status(_slots(9), _cov("incomplete", 9), SPEC, "14:40")
    assert got == MV.ST_LIVE, got


def test_the_three_words_an_operator_watches_come_out_in_order():
    """One test for the sequence, because it is the thing being asked for. Same ledger, three
    clocks: before the window, inside it, after it closed full."""
    seq = [MV._sleeve_status(_slots(0), _cov("unobserved", 0), SPEC, "12:55"),
           MV._sleeve_status(_slots(9), _cov("incomplete", 9), SPEC, "14:40"),
           MV._sleeve_status(_slots(23), _cov("complete", 23), SPEC, "23:59")]
    assert seq == [MV.ST_WAITING, MV.ST_LIVE, MV.ST_COMPLETE], seq


# -- the word the page prints, and its colour ---------------------------------------------
def test_the_chip_names_the_window_not_the_slots():
    """`unobserved` printed beside "9/23 slots" reads as a contradiction -- nine of them
    plainly were observed. What went unobserved is the window's CLOSE."""
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1]
          / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    block = js[js.index("function mvStatusChip"):]
    block = block[:block.index("function mvChip")]
    assert "'unobserved'" in block, block
    m = re.search(r"s\.status === 'unobserved'\)\s*\{\s*return \{ word: '([^']+)', tone: '(\w+)'",
                  block)
    assert m, block
    word, tone = m.group(1), m.group(2)
    assert word == "WINDOW NOT CLOSED", word
    # Amber, not red: a gap in the evidence is not a refusal, and the two colours send an
    # operator to different places.
    assert tone == "warn", tone


def test_the_chip_carries_the_ledgers_own_reason():
    """The sentence explaining it is already on the record. Writing a second one here would be
    a second account of the same fact, free to drift from the first."""
    from pathlib import Path

    import re

    js = (Path(__file__).resolve().parents[1]
          / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    block = js[js.index("function mvStatusChip"):js.index("function mvChip")]
    # Bound to the GUARD, not to the file. The first version asked only whether the words
    # `coverage` and `reason` appeared somewhere in the function, and a mutation that replaced
    # the condition with `if (false)` left both words sitting in an unreachable body -- the
    # test stayed green with the branch switched off.
    m = re.search(r"if \(s\.status === 'unobserved'\) \{(.*?)\n    \}", block, re.S)
    assert m, "the unobserved branch is gone or its condition changed"
    body = m.group(1)
    assert "coverage" in body and "reason" in body, body
    # And the chip builder must actually be handed it, or the tooltip is dead code.
    assert "mvChip(st.word, st.tone, st.tip)" in js
