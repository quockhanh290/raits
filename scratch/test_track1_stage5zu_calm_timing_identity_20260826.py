"""Stage 5ZU — Calm A could never pass its own gate, and the gate was asking the wrong thing.

Measured live 2026-08-26: the one Calm slot refused `partial_coverage, decision_bar_absent`
on a frame that held everything the rule actually reads. The contradiction, in numbers:

    decide_from / decide_to   10:00 / 10:00      + 60s grace  ->  deadline 10:01:00
    decision_bar              10:00, and it had to be a CLOSED five-minute bar
    a closed 10:00 5m bar     first exists at    10:05:00

Four minutes apart, every day, for the only sleeve whose decision bar is also the first
instant it may decide.

The backtest contract says the 10:00 bar contributes exactly ONE thing: the OPEN the entry
transacts at. Everything the RULE reads — the prior RTH session and today's 09:30 open — is
fixed by 09:30. So the gate was demanding a closed bar for a decision that does not read it.

Two names now do what one was doing:

    required_context_through    09:55 — the last bar the DECISION reads
    required_entry_quote_time   10:00 — the bar whose OPEN is the fill reference,
                                checked against the MINUTE index it is read from

The entry price is unchanged. The observation instant moves by about a minute, because a
one-minute bar stamped 10:00 closes at 10:01 and that is the earliest a closed bar can carry
that open.
"""
from __future__ import annotations

import ast
import csv
from pathlib import Path

import pandas as pd
import pytest

from global_index import track1_calm_a as ca
from global_index import track1_intraday as ti

REPO = Path(r"d:\raits")
ARTIFACT = REPO / "scratch/calm_pcloc_not_deep_gap_trade_list.csv"
DAY = "2026-08-26"
PRIOR = "2026-08-25"
ET = "America/New_York"


def five(last: str, *, drop: str | None = None):
    a = pd.date_range(f"{PRIOR} 09:30", f"{PRIOR} 16:00", freq="5min", tz=ET)
    b = pd.date_range(f"{DAY} 09:30", f"{DAY} {last}", freq="5min", tz=ET)
    idx = a.append(b)
    if drop:
        idx = idx.drop(pd.Timestamp(f"{DAY} {drop}", tz=ET))
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
                        index=idx)


def minutes(last: str):
    return pd.date_range(f"{DAY} 09:30", f"{DAY} {last}", freq="1min", tz=ET)


def check(bars, now: str, quote=None):
    return ti.validate("roska4_calm", bars, now_et=pd.Timestamp(f"{DAY} {now}", tz=ET),
                       session_day=pd.Timestamp(DAY).date(),
                       prior_session_day=pd.Timestamp(PRIOR).date(),
                       entry_quote_index=quote)


# ══════════════════════════════════════════════════════════════════════════════
# A. the backtest contract, on the artifact itself
# ══════════════════════════════════════════════════════════════════════════════

def artifact_rows():
    return list(csv.DictReader(ARTIFACT.open(encoding="utf-8")))


def test_1_the_artifact_has_the_rows_this_stage_reasoned_over():
    rows = artifact_rows()
    assert len(rows) == 421, len(rows)
    assert {r["direction"] for r in rows} == {"LONG"}
    assert {r["inst"] for r in rows} == {"MES", "MNQ"}


@pytest.mark.parametrize("col,want", [("signal_time", "09:30:00"),
                                      ("entry_time", "10:00:00"),
                                      ("exit_time", "15:55:00")])
def test_2_every_row_carries_the_same_three_clock_times(col, want):
    rows = artifact_rows()
    assert rows, "the artifact must not be empty or this proves nothing"
    bad = [r["day"] for r in rows if pd.Timestamp(r[col]).strftime("%H:%M:%S") != want]
    assert bad == [], (col, want, bad[:5])


def test_3_the_signal_never_follows_the_entry():
    rows = artifact_rows()
    assert all(pd.Timestamp(r["signal_time"]) <= pd.Timestamp(r["entry_time"]) for r in rows)
    assert all(r["signal_after_entry"] in ("0", "0.0") for r in rows)
    assert all(r["outside_entry_bar"] in ("0", "0.0") for r in rows)
    assert all(r["outside_exit_bar"] in ("0", "0.0") for r in rows)


def test_4_the_signal_is_thirty_minutes_before_the_entry_on_every_row():
    """The number that makes the fix obvious: the decision is fixed half an hour before the
    bar the gate was demanding."""
    rows = artifact_rows()
    gaps = {(pd.Timestamp(r["entry_time"]) - pd.Timestamp(r["signal_time"])) for r in rows}
    assert gaps == {pd.Timedelta(minutes=30)}, gaps


def test_5_the_params_agree_with_the_artifact():
    p = ca.CalmAParams()
    assert p.rth_start == "09:30" and p.entry_time == "10:00" and p.exit_time == "15:55"


# ══════════════════════════════════════════════════════════════════════════════
# B. the contradiction, and that it is gone
# ══════════════════════════════════════════════════════════════════════════════

def test_6_calm_is_the_only_sleeve_whose_decision_bar_was_its_first_decidable_instant():
    """Why the other three never hit this. Derived from the table, not asserted about it."""
    clash = [k for k, r in ti.REQUIREMENTS.items()
             if r.decision_bar is not None and r.decision_bar == r.decide_from]
    assert clash == [], f"a sleeve still demands a closed bar at the instant it opens: {clash}"


def test_7_stress_measures_a_level_that_is_already_closed_when_it_may_decide():
    r = ti.REQUIREMENTS["roska4_stress"]
    assert r.today_to < r.decide_from, (r.today_to, r.decide_from)


@pytest.mark.parametrize("sleeve", ["roska4_swing", "global_nkd"])
def test_8_the_scanning_sleeves_follow_the_clock_instead(sleeve):
    r = ti.REQUIREMENTS[sleeve]
    assert r.today_to_follows_now is True
    assert r.decision_bar is None


def test_9_todays_live_refusal_no_longer_happens_on_todays_frame():
    """The regression that reproduces the live event and requires it to be gone.

    Before: allow=False, codes = partial_coverage, decision_bar_absent — on a frame holding
    the complete 09:30-09:55 span, which is everything the rule reads.
    """
    v = check(five("09:55"), "10:01:10", minutes("10:00"))
    assert v.allow, [(c.name, c.code, c.detail) for c in v.checks if c.code != "ok"]
    assert "partial_coverage" not in v.codes
    assert "decision_bar_absent" not in v.codes


def test_10_the_decision_no_longer_needs_a_closed_ten_o_clock_five_minute_bar():
    r = ti.REQUIREMENTS["roska4_calm"]
    assert r.decision_bar is None, "the closed-bar requirement is back"
    assert r.required_context_through == "09:55"
    assert r.required_entry_quote_time == "10:00"
    assert r.required_context_through < r.required_entry_quote_time


def test_11_the_context_span_can_only_ever_be_narrower_than_the_declared_day():
    for k, r in ti.REQUIREMENTS.items():
        if r.required_context_through:
            assert r.required_context_through <= r.today_to, k


# ══════════════════════════════════════════════════════════════════════════════
# C. the four outcomes, exercised
# ══════════════════════════════════════════════════════════════════════════════

def test_12_no_quote_index_is_unverified_never_a_pass():
    v = check(five("09:55"), "10:00:19", None)
    assert not v.allow
    assert ti.ENTRY_QUOTE_UNVERIFIED in v.codes


def test_13_a_quote_that_has_not_closed_yet_refuses_as_entry_quote_absent():
    v = check(five("09:55"), "10:00:19", minutes("09:59"))
    assert not v.allow
    assert ti.ENTRY_QUOTE_ABSENT in v.codes
    assert ti.DECISION_BAR_ABSENT not in v.codes


def test_14_a_closed_ten_o_clock_minute_bar_is_enough():
    v = check(five("09:55"), "10:01:10", minutes("10:00"))
    assert v.allow, list(v.codes)


def test_15_late_is_still_late_and_never_becomes_an_entry():
    """No-late-entry survives the fix. The grace moved; the refusal did not."""
    v = check(five("09:55"), "10:03:30", minutes("10:00"))
    assert not v.allow
    assert ti.TOO_LATE in v.codes


def test_16_the_grace_is_three_minutes_and_that_is_an_observation_change():
    r = ti.REQUIREMENTS["roska4_calm"]
    assert r.decision_grace_seconds == 180
    # the entry PRICE definition is untouched — that is the strategy identity
    assert r.required_entry_quote_time == ca.CalmAParams().entry_time == "10:00"


def test_17_a_hole_in_the_context_span_still_refuses():
    v = check(five("09:55", drop="09:45"), "10:01:10", minutes("10:00"))
    assert not v.allow
    assert ti.GAP_IN_COVERAGE in v.codes


def test_18_a_frame_that_stops_short_of_the_context_still_refuses():
    v = check(five("09:45"), "10:01:10", minutes("10:00"))
    assert not v.allow
    assert ti.PARTIAL_COVERAGE in v.codes or ti.STALE in v.codes


def test_19_too_early_still_refuses():
    v = check(five("09:55"), "09:58:00", minutes("10:00"))
    assert not v.allow
    assert ti.TOO_EARLY in v.codes


# ══════════════════════════════════════════════════════════════════════════════
# D. what must NOT have changed
# ══════════════════════════════════════════════════════════════════════════════

def test_20_the_entry_price_is_still_the_open_at_ten_and_reads_nothing_else():
    """AST over the detector: the entry comes from `_bar_open_at`, and no high/low/close of
    the entry bar is read anywhere in the causal path."""
    # Stage 5ZX widened the SCOPE and kept the number. The causal path is now two functions —
    # the rule's pre-entry half and the detector built on it — so counting inside one of them
    # reports one bar read and calls it a violation. The property was never "this function
    # calls it twice"; it was "the causal path takes exactly the 09:30 and 10:00 opens, and
    # nothing else". Counted across both, that is still exactly two, and this now also catches
    # a third read appearing in EITHER half.
    src = (REPO / "global_index/track1_calm_a.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    CAUSAL = ("detect_entry_for_day", "detect_setup_before_entry")
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name in CAUSAL]
    assert len(fns) == len(CAUSAL), f"the causal path lost a half: {[f.name for f in fns]}"
    calls = [n for f in fns for n in ast.walk(f) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_bar_open_at"]
    assert len(calls) == 2, "the causal path no longer takes exactly the 09:30 and 10:00 opens"
    # And each half reads exactly one: the pre-entry half must not reach the entry bar, which
    # is the whole reason it exists. A total of two split 2/0 would pass the line above.
    per = {f.name: sum(1 for n in ast.walk(f) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name) and n.func.id == "_bar_open_at")
           for f in fns}
    assert per == {"detect_entry_for_day": 1, "detect_setup_before_entry": 1}, per

    # The forbidden thing is reading TODAY's entry bar's high/low/close. The PRIOR session's
    # OHLC is causal and required — it closed yesterday — and the first version of this test
    # conflated the two, flagging `sessions.loc[prev]["low"]` as lookahead. Narrowed to what
    # it means: the only thing this function may take out of today's MINUTE frame is an open,
    # and it may only take it through `_bar_open_at`.
    # Over BOTH halves, for the reason above: a direct read of today's frame is lookahead
    # wherever it is written, and checking only the outer function would leave the half that
    # actually holds the rule unexamined.
    for fn in fns:
        frame_arg = fn.args.args[0].arg
        direct = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                  and n.value.id == frame_arg]
        assert direct == [], (
            f"{fn.name} subscripts {frame_arg} directly; every read of today's frame must "
            f"go through _bar_open_at, which takes an OPEN and nothing else")
        attr_reads = [n for n in ast.walk(fn)
                      if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                      and n.value.id == frame_arg and n.attr in ("loc", "at", "iloc", "iat")]
        assert attr_reads == [], f"{fn.name} indexes {frame_arg} outside _bar_open_at"


def test_21_bar_open_at_takes_the_open_and_only_the_open():
    src = (REPO / "global_index/track1_calm_a.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_bar_open_at")
    # It reads `sel_naive.loc[want, "open"]` — a Subscript whose slice is a TUPLE, which the
    # first version of this test did not handle, so it collected nothing and compared an
    # empty set. Every string constant the function names is gathered instead, which is the
    # claim: an OPEN and no other column.
    cols = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value in ("open", "high", "low", "close", "volume")}
    assert cols == {"open"}, cols


def test_22_the_other_three_sleeves_are_untouched_by_this_change():
    for k in ("roska4_stress", "roska4_swing", "global_nkd"):
        r = ti.REQUIREMENTS[k]
        assert r.required_context_through is None, k
        assert r.required_entry_quote_time is None, k
        assert r.decision_grace_seconds == 60, k


@pytest.mark.parametrize("sleeve,now,ok", [
    ("roska4_stress", "11:00:03", True),
    ("roska4_stress", "12:35:00", False),
])
def test_23_stress_still_behaves_exactly_as_before(sleeve, now, ok):
    a = pd.date_range(f"{DAY} 09:30", f"{DAY} 10:55", freq="5min", tz=ET)
    bars = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
                        index=a)
    v = ti.validate(sleeve, bars, now_et=pd.Timestamp(f"{DAY} {now}", tz=ET),
                    session_day=pd.Timestamp(DAY).date())
    assert v.allow is ok, list(v.codes)


def test_24_a_refused_slot_is_not_a_no_signal():
    """A missed or refused Calm slot must never be filed as 'the rule looked and found
    nothing'. The two are different facts and only one of them is about the market."""
    from global_index import track1_signals as sg

    assert sg.SLOT_REFUSED != sg.NO_SIGNAL
    assert sg.SLOT_MISSED != sg.NO_SIGNAL
    assert sg.SLOT_REFUSED in sg.STATUSES


def test_24b_a_partial_ten_oclock_bar_cannot_reach_the_decision():
    """The hard constraint, checked rather than asserted.

    Measured live 2026-08-26 at 10:00:19: MNQ's joined frame already carried a bar stamped
    10:00 — nineteen seconds of one — while MES's stopped at 09:59. A partial bar's OPEN is
    final from its first tick and is exactly what the entry transacts at; its high, low and
    close are not, and nothing may read them.

    The context span stops at 09:55, so a 10:00 bar present in the frame is outside everything
    the decision reads. This proves it by verdict equality: adding one changes nothing.
    """
    without = five("09:55")
    extra = pd.DataFrame({"open": 1.0, "high": 99.0, "low": -99.0, "close": 42.0,
                          "volume": 3},
                         index=pd.DatetimeIndex([pd.Timestamp(f"{DAY} 10:00", tz=ET)]))
    with_partial = pd.concat([without, extra])

    a = check(without, "10:01:10", minutes("10:00"))
    b = check(with_partial, "10:01:10", minutes("10:00"))
    assert a.allow == b.allow is True
    assert a.codes == b.codes == ()
    span_a = [c.detail for c in a.checks if c.name == "today_span"][0]
    span_b = [c.detail for c in b.checks if c.name == "today_span"][0]
    assert span_a == span_b, "the partial bar changed what the decision span read"
    assert "09:55" in span_b and "10:00" not in span_b, span_b


def test_24c_the_context_span_never_extends_to_the_entry_quote():
    """A one-line guard against the whole class: whatever else changes, the span the decision
    reads must end strictly before the bar the entry is priced at."""
    r = ti.REQUIREMENTS["roska4_calm"]
    assert r.required_context_through < r.required_entry_quote_time
    v = check(five("09:55"), "10:01:10", minutes("10:00"))
    span = [c.detail for c in v.checks if c.name == "today_span"][0]
    assert r.required_entry_quote_time not in span, span


def test_25_the_splice_guard_was_not_touched():
    from global_index import track1_gates as g

    released, detail = g.live_frame_wiring()
    assert released is True, detail


def test_26_orders_are_still_impossible():
    from global_index import track1_gates as g

    assert g.may_enable_orders()[0] is False
    # Stage 5ZZZ-E. The confirmation file leaves this list, for the reason Stage 5ZZS restated
    # it in four suites and 5ZZW and 5ZZZ-A in several more: the operator signed it deliberately
    # on 2026-08-27, and asserting its absence asserts that nobody decided anything. What still
    # holds is that a decision on disk must be a SIGNED one - an unsigned file appearing here
    # would be something a run had dropped.
    _conf = REPO / g.CONFIRMATION_PATH
    if _conf.exists():
        import json as _json
        assert (_json.loads(_conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip()


def test_27_no_new_refusal_code_is_undeclared():
    """Every code the module names must be in REFUSAL_CODES, or a refusal exists that no
    caller can enumerate."""
    named = {v for k, v in vars(ti).items()
             if k.isupper() and isinstance(v, str) and k not in ("OK", "ET")}
    assert named - {ti.OK} <= set(ti.REFUSAL_CODES) | {ti.ET}, named - set(ti.REFUSAL_CODES)
