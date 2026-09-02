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
#
# Two tests stood here that scraped `mvStatusChip` for the branch by regex. Stage 5ZZZ-BX moved
# the branch into `mvProgressChip`, and both went red without a single behaviour changing --
# they were pinned to WHERE the code lived. What they were protecting (the word, the colour,
# and the tooltip coming from the ledger rather than a second copy) is asserted below against
# the functions as the page actually runs them, which survives the code moving again.

# -- Stage 5ZZZ-BX: where the session IS, kept apart from what it FOUND -------------------
def _chip_fns():
    """The two renderers, lifted out of the page and executed as written.

    Read from the file rather than reimplemented here: a Python copy of the branch table would
    agree with itself no matter what the page does, which is the failure mode this file has
    already hit once today.
    """
    import re
    import subprocess
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1]
          / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")

    def grab(name):
        i = js.index("function %s(s) {" % name)
        depth, j = 0, js.index("{", i)
        for k in range(j, len(js)):
            if js[k] == "{":
                depth += 1
            elif js[k] == "}":
                depth -= 1
                if depth == 0:
                    return js[i:k + 1]
        raise AssertionError("unbalanced braces reading %s" % name)

    prog, stat = grab("mvProgressChip"), grab("mvStatusChip")
    assert "WAITING" in prog and "COMPLETE" in prog, prog[:200]
    return prog, stat


def _run_js(prog, stat, sleeve):
    import json
    import subprocess

    script = (prog + "\n" + stat + "\n"
              + "const s = " + json.dumps(sleeve) + ";\n"
              + "console.log(JSON.stringify({p: mvProgressChip(s), o: mvStatusChip(s)}));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def chips():
    fns = _chip_fns()
    return lambda sleeve: _run_js(fns[0], fns[1], sleeve)


def test_a_finished_sleeve_says_it_finished(chips):
    """The defect, measured on the page at 21:39 ET with all three sleeves done: every tab read
    NO SIGNAL and nothing said any of them had ended. `waiting` and `live` were visible only
    because no outcome exists at those moments."""
    got = chips({"status": "complete", "slots": [{"status": "no_signal"}]})
    assert got["p"]["word"] == "COMPLETE", got
    assert got["o"]["word"] == "NO SIGNAL", got


def test_a_sleeve_with_nothing_decided_publishes_no_outcome(chips):
    """Before the window there is no answer to borrow. A second chip repeating the progress
    word would be two chips saying one thing."""
    got = chips({"status": "waiting", "slots": []})
    assert got["p"]["word"] == "WAITING", got
    assert got["o"] is None, got


def test_a_live_sleeve_shows_both_and_the_reading_is_marked_interim(chips):
    """"No signal" on a live sleeve is an interim reading; on a complete one it is the
    session's answer. The progress chip is what separates them."""
    got = chips({"status": "live", "slots": [{"status": "no_signal"}, {"status": "future"}]})
    assert got["p"]["word"] == "LIVE" and got["p"]["tone"] == "live", got
    assert "interim" in got["p"]["tip"], got["p"]


def test_a_signal_still_wins_the_outcome_chip(chips):
    """The loudest fact must not be demoted by the split."""
    got = chips({"status": "complete", "slots": [{"status": "signal"}]})
    assert got["p"]["word"] == "COMPLETE", got
    assert got["o"]["word"] == "SIGNAL" and got["o"]["tone"] == "good", got


def test_an_unvouched_window_still_reports_what_its_slots_found(chips):
    """Measured on 2026-08-28: WINDOW NOT CLOSED beside NO SIGNAL and 9/23. The nine slots that
    ran found nothing, and that is a fact; the caveat rides on the chip next to it."""
    got = chips({"status": "unobserved", "slots": [{"status": "no_signal"}],
                 "coverage": {"reason": "no window_closed record"}})
    assert got["p"]["word"] == "WINDOW NOT CLOSED" and got["p"]["tone"] == "warn", got
    assert got["o"]["word"] == "NO SIGNAL", got


def test_an_unvouched_window_with_nothing_decided_claims_no_outcome(chips):
    """A window nobody closed AND nothing evaluated has no finding to report. Printing "no
    signal" there would turn an absence of evidence into a result."""
    got = chips({"status": "unobserved", "slots": [{"status": "missed"}], "coverage": {}})
    assert got["o"] is None, got


def test_a_refused_window_does_not_say_it_twice(chips):
    """The progress chip already carries REFUSED."""
    got = chips({"status": "refused", "slots": [{"status": "refused"}]})
    assert got["p"]["word"] == "REFUSED" and got["p"]["tone"] == "bad", got
    assert got["o"] is None, got


def test_a_data_refusal_still_outranks_everything(chips):
    """A provider that refused data is louder than either axis: nothing below it can be
    trusted, so it must not be reduced to a second chip."""
    got = chips({"status": "complete", "slots": [{"status": "no_signal"}],
                 "data_status": {"ok": False, "provider_reason": "held back"}})
    assert got["o"]["word"] == "DATA REFUSED" and got["o"]["tone"] == "bad", got


def test_the_unvouched_tooltip_is_the_ledgers_own_sentence(chips):
    """The explanation is already on the record. A second one written in the page would be a
    second account of the same fact, free to drift from the first."""
    got = chips({"status": "unobserved", "slots": [{"status": "no_signal"}],
                 "coverage": {"reason": "no window_closed record - absence is the signal"}})
    assert got["p"]["tip"] == "no window_closed record - absence is the signal", got["p"]


def test_a_record_with_no_reason_still_explains_itself(chips):
    """Older sessions may carry no reason string. Falling back to silence would leave an amber
    chip with nothing behind it."""
    got = chips({"status": "unobserved", "slots": [{"status": "no_signal"}], "coverage": {}})
    assert "window_closed" in got["p"]["tip"], got["p"]


def test_the_tooltip_is_actually_handed_to_the_chip_builder():
    """A tip the renderer never passes on is dead code. This is the call site, not the value."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1]
          / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    assert "mvChip(pr.word, pr.tone, pr.tip)" in js, "the progress chip drops its tooltip"
    assert "mvChip(st.word, st.tone, st.tip)" in js, "the outcome chip drops its tooltip"


def test_the_verdict_pill_survives_a_sleeve_with_no_outcome():
    """The second caller. `mvStatusChip` now returns nothing while a sleeve has decided nothing,
    and the verdict pill reads `.tone` off it -- without a fallback it would throw on every
    waiting sleeve, which is the state the page opens in every morning."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1]
          / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    block = js[js.index("function mvVerdict(s) {"):]
    block = block[:block.index("\n  function ", 10)]
    assert "mvStatusChip(s) || mvProgressChip(s)" in block, block


def test_a_data_refusal_is_placed_ahead_of_the_progress_chip():
    """The regression the split caused, and the reason it is worth pinning twice.

    Stage 5ZZZ-BX put progress first unconditionally, so a sleeve whose feed never answered
    read COMPLETE first and DATA REFUSED second -- and a sleeve whose feed never answered is
    not meaningfully complete. The commit making that split CLAIMED a data refusal still
    outranked both; the code did not do it. A DOM test written three stages earlier caught it:
    "if the feed did not answer, what the slots did is a smaller fact than why".

    Asserted on the ordering at the render site, because the ordering IS the fix -- both chips
    were present either way.
    """
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1]
          / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    i_first = js.index("if (st && st.outranks) out.push(")
    i_prog = js.index("out.push(mvChip(pr.word, pr.tone, pr.tip));")
    i_last = js.index("if (st && !st.outranks) out.push(")
    assert i_first < i_prog < i_last, (i_first, i_prog, i_last)


def test_only_the_data_refusal_claims_to_outrank(chips):
    """If every outcome outranked, the split would be undone and progress would be last."""
    refused = chips({"status": "complete", "slots": [{"status": "no_signal"}],
                     "data_status": {"ok": False, "provider_reason": "held back"}})
    assert refused["o"]["outranks"] is True, refused["o"]
    for sleeve in ({"status": "complete", "slots": [{"status": "no_signal"}]},
                   {"status": "complete", "slots": [{"status": "signal"}]},
                   {"status": "unobserved", "slots": [{"status": "no_signal"}],
                    "coverage": {}}):
        got = chips(sleeve)
        assert not (got["o"] or {}).get("outranks"), (sleeve, got["o"])
