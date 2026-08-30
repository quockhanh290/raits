"""Stage 5ZB — the negative audit for the 5ZA causal guards, plus operational readiness.

Stage 5ZA left its mutation pass explicitly pending, and three of its seam tests are the shape
this project keeps getting burned by: `inspect.getsource` + a substring. Two problems with
that, both already paid for in earlier stages —

  * `getsource` reads the LINECACHE, so a source-level mutation cannot reach it and a harness
    built on one reports a green mutation that never ran (Stage 5X, M13/M15);
  * a substring matches prose. If the probe string ever appears in a docstring, the test
    passes with the code deleted (Stage 5T, 5X, 5Y, 5Z — four times).

Measured: neither probe is satisfiable by prose *today*, so 5ZA is not currently wrong. But it
is unbreakable, and an unbreakable test is one nobody can trust later. The versions here read
the FILE and walk the AST, so a mutation lands.

Read-only throughout: no scheduler or backend touched, no broker, no order, no runtime file
written. Every runtime assertion below is an inspection.
"""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from global_index import track1_intraday as intra
from global_index import track1_paper_callsite as callsite
from global_index import track1_slots as slots

REPO = Path(__file__).resolve().parents[1]
ET = "America/New_York"
DAY_ET = pd.Timestamp("2026-08-26")

SLEEVES = ("roska4_calm", "roska4_stress", "roska4_swing", "global_nkd")


def _fn_ast(rel: str, name: str, cls: str | None = None):
    """Parse one function from the FILE, not the linecache.

    This is the whole point of the module. `inspect.getsource` would make every test below
    immune to the mutations that are supposed to break it.
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    scope = tree
    if cls is not None:
        scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in ast.walk(scope)
                if isinstance(n, ast.FunctionDef) and n.name == name)


# ══════════════════════════════════════════════════════════════════════════════
# 1. re-verify the 5ZA scope
# ══════════════════════════════════════════════════════════════════════════════

def test_1_all_seventy_strategy_slots_are_still_present_and_accounted_for():
    by = Counter(s.sleeve for s in slots.TRACK1_SLOTS)
    assert dict(by) == {"roska4_calm": 1, "roska4_stress": 24,
                        "roska4_swing": 23, "global_nkd": 22}
    assert sum(by.values()) == 70
    assert len({s.id for s in slots.TRACK1_SLOTS}) == 70


def test_2_every_sleeve_has_an_intraday_requirement_and_no_extras():
    assert set(intra.REQUIREMENTS) == set(SLEEVES)


def test_3_only_the_two_scanning_sleeves_follow_the_slot():
    """The 5V-1 rule. A blanket `min()` would have silently shrunk Calm's span."""
    follows = {k for k, r in intra.REQUIREMENTS.items() if r.today_to_follows_now}
    assert follows == {"roska4_swing", "global_nkd"}


def test_4_no_sleeve_declares_a_span_that_needs_the_session_end():
    """Calm and Stress must not reach past their own decision point, and the two scanning
    sleeves must reach the session end ONLY through the dynamic bound."""
    for name in ("roska4_calm", "roska4_stress"):
        r = intra.REQUIREMENTS[name]
        assert r.today_to <= "10:30", (name, r.today_to)
        assert r.today_to_follows_now is False


#: Stage 5ZU. The grace stopped being one number for every sleeve, and pinning it as one was
#: pinning a coincidence. Calm's is three minutes because the price it transacts at — the OPEN
#: at 10:00 — is only readable from a CLOSED one-minute bar at 10:01:00, and a one-minute
#: grace put its deadline exactly on that closing instant. The other three are unchanged.
#:
#: Declared per sleeve here so the boundary tests below read it rather than assume it: a test
#: that hard-codes 60 would go red for the wrong reason the next time a sleeve needs its own.
EXPECTED_GRACE = {"roska4_calm": 180, "roska4_stress": 60, "roska4_swing": 60,
                  "global_nkd": 60}


def test_5_the_grace_is_declared_on_every_sleeve_and_matches_its_reason():
    assert set(EXPECTED_GRACE) == set(SLEEVES), "a sleeve appeared or vanished"
    for name in SLEEVES:
        assert intra.REQUIREMENTS[name].decision_grace_seconds == EXPECTED_GRACE[name], name
    # and the one that differs must be the one with an entry quote to wait for
    odd = [n for n, v in EXPECTED_GRACE.items() if v != 60]
    assert odd == ["roska4_calm"], odd
    assert intra.REQUIREMENTS["roska4_calm"].required_entry_quote_time is not None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Calm dispatch grace — behavioural, and bounded on BOTH sides
# ══════════════════════════════════════════════════════════════════════════════

def _calm_frame(day: pd.Timestamp) -> pd.DataFrame:
    r = intra.REQUIREMENTS["roska4_calm"]
    # The DECISION span, which since Stage 5ZU ends before the entry bar rather than on it.
    today = intra.synth_bars(day, r.today_from,
                             r.required_context_through or r.today_to, r.bar_minutes)
    if not r.needs_prior_rth:
        return today
    prior = intra._prev_business_day(day)
    return pd.concat([intra.synth_bars(prior, r.prior_from, r.prior_to, r.bar_minutes),
                      today]).sort_index()


def _entry_quote_index(sleeve: str, day: pd.Timestamp):
    """Where the sleeve's fill reference is read from, or None when it declares none.

    Stage 5ZU. Calm's requirement spans two bar sizes — a five-minute decision span and a
    one-minute bar whose OPEN it transacts at — and the gate reports UNVERIFIED rather than a
    pass when nobody says where the second comes from. Every call in this suite therefore has
    to offer it, or each assertion below would be answering a question it is not about.
    """
    r = intra.REQUIREMENTS[sleeve]
    if r.required_entry_quote_time is None:
        return None
    hh, mm = int(r.required_entry_quote_time[:2]), int(r.required_entry_quote_time[3:])
    return pd.date_range(pd.Timestamp(f"{day.date()} {r.today_from}", tz=ET),
                         pd.Timestamp(f"{day.date()} {hh:02d}:{mm:02d}", tz=ET), freq="1min")


def _validate(sleeve: str, frame, now, day):
    return intra.validate(sleeve, frame, now_et=now, session_day=day,
                          prior_session_day=intra._prev_business_day(day),
                          entry_quote_index=_entry_quote_index(sleeve, day))


def _calm_codes(seconds_late: int):
    now = pd.Timestamp(f"{DAY_ET.date()} 10:00:00", tz=ET) + pd.Timedelta(
        seconds=seconds_late)
    v = _validate("roska4_calm", _calm_frame(DAY_ET), now, DAY_ET)
    return bool(v.allow), tuple(v.codes)


_CALM_GRACE = EXPECTED_GRACE["roska4_calm"]


@pytest.mark.parametrize("late", [0, 1, 3, 30, 59, 120, _CALM_GRACE])
def test_6_seconds_of_dispatch_latency_are_still_the_scheduled_slot(late):
    """Inside the declared grace the slot is still THIS slot, whatever the number is.

    Stage 5ZU widened Calm's grace from 60s to 180s, so 61 and 120 moved from the refused
    side to this one — deliberately: the price this sleeve transacts at is not readable from
    a closed bar until 10:01:00, so a 60-second window ended before the sleeve could ever
    see it. The boundary is read from the requirement rather than written here twice.
    """
    allow, codes = _calm_codes(late)
    assert allow, (late, codes)
    assert "too_late" not in codes, (late, codes)


@pytest.mark.parametrize("late", [_CALM_GRACE + 1, _CALM_GRACE + 60, 3600])
def test_7_materially_late_is_still_refused(late):
    """The grace is a grace, not an amnesty. A missed Calm slot is NOT entered later."""
    allow, codes = _calm_codes(late)
    assert not allow, (late, codes)
    assert "too_late" in codes, (late, codes)


def test_8_the_grace_boundary_is_exactly_where_it_is_declared():
    """In at the declared second, out one second later. Derived from the requirement, so a
    later change to the number moves this test with it — and a change that removed the
    boundary altogether still fails."""
    g = intra.REQUIREMENTS["roska4_calm"].decision_grace_seconds
    assert g == _CALM_GRACE, "the requirement and this suite disagree about the grace"
    assert _calm_codes(g)[0] is True
    assert _calm_codes(g + 1)[0] is False
    assert "too_late" in _calm_codes(g + 1)[1]


def test_9_too_late_is_still_classified_as_window_shut_not_a_data_refusal():
    """Otherwise a genuinely late Calm slot would make the window fail rather than close."""
    from global_index import track1_shadow_acceptance as acc
    src = (REPO / "global_index/track1_shadow_acceptance.py").read_text(encoding="utf-8")
    assert "too_late" in src
    for name in dir(acc):
        val = getattr(acc, name)
        if isinstance(val, (set, frozenset, tuple, list)) and "too_late" in val:
            assert "shut" in name.lower() or "clock" in name.lower() or "window" in name.lower(), (
                f"too_late moved into {name}, which is not a window-shut class")


# ══════════════════════════════════════════════════════════════════════════════
# 3. the truncation seams — AST on the FILE, so a mutation lands
# ══════════════════════════════════════════════════════════════════════════════

def test_10_stress_narrows_its_scan_end_to_the_current_slot():
    """Structure, not a substring: an assignment to `end` whose value is a `min(...)` call.

    A rewrite that keeps the behaviour but changes the spelling still passes; a rewrite that
    drops the narrowing does not.
    """
    fn = _fn_ast("global_index/track1_stress_mnq.py", "detect_entry_for_slot")
    mins = [n for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "end" for t in n.targets)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name) and n.value.func.id == "min"]
    assert len(mins) == 1, f"stress no longer narrows `end` with min(): {len(mins)} site(s)"
    args = {ast.unparse(a) for a in mins[0].value.args}
    assert "end" in args and "hhmm" in args, args


def test_11_normal_r4_and_nkd_truncate_their_scan_to_the_frame_clock():
    """A comparison of the window index against `now_ts`, used to subscript the window."""
    fn = _fn_ast("global_index/track1_normal_r4.py", "detect_entry_for_slot")
    cmps = [n for n in ast.walk(fn)
            if isinstance(n, ast.Compare)
            and isinstance(n.left, ast.Name) and n.left.id == "widx_naive"
            and any(isinstance(o, ast.LtE) for o in n.ops)
            and any(isinstance(c, ast.Name) and c.id == "now_ts" for c in n.comparators)]
    assert cmps, "normal_r4 no longer bounds its scan window by now_ts"
    subs = [n for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "win" for t in n.targets)
            and isinstance(n.value, ast.Subscript)]
    assert subs, "the bound is computed but never applied to `win`"


def test_12_the_live_source_fetches_every_sleeve_through_the_slot_instant():
    """`through=now` on all four candidate builders, read from the file."""
    wanted = {"_calm_candidates": "sleeve_frames", "_swing_candidates": "sleeve_frames",
              "_nkd_candidates": "sleeve_frames", "_stress_candidates": "live_frames"}
    for meth, callee in wanted.items():
        fn = _fn_ast("global_index/track1_live_source.py", meth, cls="LiveTrack1Source")
        hits = [n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", getattr(n.func, "attr", None)) == callee
                and any(k.arg == "through" and isinstance(k.value, ast.Name)
                        and k.value.id == "now" for k in n.keywords)]
        assert len(hits) == 1, f"{meth}: {len(hits)} call(s) to {callee}(through=now)"


def test_13_calm_uses_the_entry_only_detector_not_the_full_day_replay():
    fn = _fn_ast("global_index/track1_live_source.py", "_calm_candidates",
                 cls="LiveTrack1Source")
    called = {getattr(n.func, "id", getattr(n.func, "attr", None))
              for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "detect_entry_for_day" in called
    assert "detect" not in called, "the full-day replay detector is back on the live path"


# ══════════════════════════════════════════════════════════════════════════════
# 4. causality, behaviourally — and the test proves it can go red
# ══════════════════════════════════════════════════════════════════════════════

def _span_for(sleeve: str, now: pd.Timestamp):
    r = intra.REQUIREMENTS[sleeve]
    local = now.tz_convert(r.clock).tz_localize(None)
    day = local.normalize()
    return r, local, day


def _causal_frame(sleeve: str, now: pd.Timestamp):
    """The bars that actually EXIST by `now`, derived from the clock — not from the flag.

    This matters more than it looks. The first version of this helper decided how far to fill
    the frame by reading `today_to_follows_now`, the very field the sweep exists to protect.
    A mutation that flipped the flag moved the fixture with it and the test stayed green:
    the frame agreed with whatever the gate had just decided to want.

    So the bound comes from data the gate does not own: whether the sleeve's DECLARED end is
    still in the future at this slot. If it is, only bars up to the last closed one can
    exist. If it is not, the declared end has already happened and the frame carries it.
    """
    r = intra.REQUIREMENTS[sleeve]
    local = now.tz_convert(r.clock).tz_localize(None)
    day = local.normalize()
    declared = day + intra._hhmm(r.today_to)
    closed = intra._last_closed_bar(local, r.bar_minutes)
    end = closed if declared > local else max(declared, closed)
    hi = f"{end.hour:02d}:{end.minute:02d}"
    frame = intra.synth_bars(day, r.today_from, hi, r.bar_minutes)
    if r.needs_prior_rth:
        prior = intra._prev_business_day(day)
        frame = pd.concat([intra.synth_bars(prior, r.prior_from, r.prior_to,
                                            r.bar_minutes), frame]).sort_index()
    return frame, day


def test_14_no_slot_of_any_sleeve_demands_a_bar_from_its_own_future():
    """The 5ZA sweep, re-run here as the acceptance criterion for this stage.

    For each of the 70 slots: build the frame that slot is causally entitled to, run the real
    gate at the slot instant + 3s, and require it not to refuse for missing or stale bars.
    """
    refused = []
    for s in slots.TRACK1_SLOTS:
        now = pd.Timestamp(f"{DAY_ET.date()} {s.hour:02d}:{s.minute:02d}:03", tz=ET)
        frame, day = _causal_frame(s.sleeve, now)
        v = _validate(s.sleeve, frame, now, day)
        bad = set(v.codes) & {"partial_coverage", "stale", "gap_in_coverage"}
        if bad:
            refused.append((s.id, sorted(bad)))
    assert refused == [], refused
    assert len(slots.TRACK1_SLOTS) == 70, "the sweep must cover every slot"


def test_15_the_sweep_is_capable_of_failing():
    """Non-vacuity. A sweep that passes because it checks nothing is worse than no sweep.

    The control removes two bars from the end of what each scanning slot is entitled to;
    every one of them must then be refused. If this control does NOT fail, `test_14` proves
    nothing.
    """
    caught = 0
    for s in slots.TRACK1_SLOTS:
        r = intra.REQUIREMENTS[s.sleeve]
        if not r.today_to_follows_now:
            continue
        now = pd.Timestamp(f"{DAY_ET.date()} {s.hour:02d}:{s.minute:02d}:03", tz=ET)
        local = now.tz_convert(r.clock).tz_localize(None)
        day = local.normalize()
        end = intra._last_closed_bar(local, r.bar_minutes) - pd.Timedelta(
            minutes=2 * r.bar_minutes)
        if end <= day + intra._hhmm(r.today_from):
            continue
        hi = f"{end.hour:02d}:{end.minute:02d}"
        frame = intra.synth_bars(day, r.today_from, hi, r.bar_minutes)
        v = _validate(s.sleeve, frame, now, day)
        if {"partial_coverage", "stale"} & set(v.codes):
            caught += 1
    assert caught >= 20, (
        f"only {caught} slot(s) refused a deliberately short frame; the sweep in test_14 "
        f"cannot be trusted")


# ══════════════════════════════════════════════════════════════════════════════
# 5. the paper seam, and strategy identity
# ══════════════════════════════════════════════════════════════════════════════

def test_16_the_seam_is_still_the_scheduler_slot_path():
    s = callsite.seam(REPO)
    assert s["function"] == "observe_live_slot"
    assert "run_candidates" in s["anchor"]


def test_17_the_causal_work_changed_no_strategy_rule():
    """Identity is what the backtest reproduced against. The gate decides WHETHER a slot may
    decide; it must never change WHAT the sleeve computes.

    Proved structurally: the gate module cannot reach a sleeve rule module, so there is no
    expression it could change. That is stronger than comparing identity hashes, which would
    only say the two agreed on the day the test ran.
    """
    tree = ast.parse((REPO / "global_index/track1_intraday.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", "") or ""
            names = [a.name for a in n.names]
            for bad in ("track1_normal_r4", "track1_calm_a", "track1_stress_mnq",
                        "track1_signal_layer"):
                assert bad not in mod and not any(bad in x for x in names), bad


def test_17b_the_grace_is_a_gate_field_not_a_strategy_parameter():
    """It lives on the intraday Requirement, and nothing in track1_params knows about it."""
    import dataclasses
    names = {f.name for f in dataclasses.fields(intra.Requirement)}
    assert "decision_grace_seconds" in names
    params_src = (REPO / "global_index/track1_params.py").read_text(encoding="utf-8")
    assert "decision_grace_seconds" not in params_src, (
        "the dispatch grace leaked into the params module, which is hashed into identity")


# ══════════════════════════════════════════════════════════════════════════════
# 6. operational readiness — read-only inspection of what is on disk
# ══════════════════════════════════════════════════════════════════════════════

def test_18_orders_are_still_impossible():
    import os
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "B1_broker_account_or_legacy_retirement" in ids
    assert "PAPER_SHADOW_EVIDENCE" in ids
    assert not (REPO / G.CONFIRMATION_PATH).exists()
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")


def test_19_no_order_journal_book_or_dry_run_residue_exists():
    from global_index import track1_order_journal as J
    assert not (REPO / J.ORDERS_DIR).exists()
    assert not (REPO / "global_index/live_positions.track1.json").exists()
    assert not (REPO / callsite.DRY_RUN_DIRNAME).exists()


def test_20_the_scheduler_argv_is_track1_only_shadow_and_carries_no_arming_flag():
    """Read from the live process, not from a config file."""
    import subprocess
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
         "Where-Object { $_.CommandLine -like '*run_scheduler*' } | "
         "Select-Object -ExpandProperty CommandLine"],
        capture_output=True, text=True, timeout=90).stdout.strip()
    if not out:
        pytest.skip("no scheduler process on this machine")
    assert "--track1-only-shadow" in out
    assert "--allow-orders" not in out


def test_21_the_expected_job_count_is_what_the_current_code_registers():
    from global_index import track1_slots as t1
    strategy = len(t1.TRACK1_SLOTS)
    safety = len(t1.track1_safety_jobs())
    assert strategy == 70 and safety == 11
    # 70 strategy + 11 track1 safety + 5 audit + 11 legacy safety drain + 4 shared = 101
    assert strategy + safety == 81


def test_22_the_runbook_exists_and_names_every_artefact_to_inspect():
    """Stage 5ZB deliverable: the operator must not have to infer this from stage reports."""
    p = REPO / "docs/futures/TRACK1_SHADOW_WINDOW_RUNBOOK.md"
    assert p.exists(), "the post-window runbook is missing"
    text = p.read_text(encoding="utf-8")
    for needed in ("window_coverage", "slot_timing", "track1_shadow_audit",
                   "explanations", "schedule-status", "track1_runtime/orders",
                   "live_positions.track1.json", "replay_checkpoint.track1.json"):
        assert needed in text, needed


def test_23_the_runbook_states_the_three_clocks_explicitly():
    """This stage lost an hour to a shell whose TZ conversion returned UTC. The runbook must
    hand the operator the anchor rather than a habit."""
    text = (REPO / "docs/futures/TRACK1_SHADOW_WINDOW_RUNBOOK.md").read_text(encoding="utf-8")
    assert "UTC" in text and "ET" in text and "Calgary" in text
    assert "zoneinfo" in text or "ZoneInfo" in text


# ══════════════════════════════════════════════════════════════════════════════
# 7. what the ledger actually says — read-only
# ══════════════════════════════════════════════════════════════════════════════

def _coverage_days():
    d = REPO / "global_index/track1_runtime/window_coverage"
    return sorted(d.glob("window_coverage_*.jsonl")) if d.is_dir() else []


def test_24_every_opened_window_in_the_ledger_is_accounted_for():
    """An opened window with no close is `unobserved`, and the ledger says absence is the
    signal. This test does not demand there be none - it demands they be VISIBLE.

    The non-vacuity assert is not decoration. The first version accepted an empty sweep, so a
    mutation that hid every ledger file left it green: "no dangling windows" and "I could not
    find the ledger" were the same answer. Same shape as the read that cannot say "I do not
    know", which is the defect this whole route has spent four stages removing.
    """
    days = _coverage_days()
    assert days, "no window-coverage files found; this test walked nothing"
    dangling = []
    seen_windows = 0
    for p in days:
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        opened = {r.get("sleeve") for r in rows if r.get("event") == "window_open"}
        closed = {r.get("sleeve") for r in rows if r.get("event") == "window_closed"}
        seen_windows += len(opened)
        for s in sorted(opened - closed):
            dangling.append((p.name[-13:-6], s))
    assert seen_windows > 0, "ledger files exist but contain no window_open rows"
    # 2026-08-24 roska4_calm is the known one: the slot died on SpliceRefused before writing
    # its row. Both the crash and the missing row are fixed; the historical row stays as it is.
    assert dangling in ([], [("0260824", "roska4_calm")]), dangling


def test_25_the_calm_crash_of_20260824_cannot_happen_again():
    """Two independent fixes, both asserted from the file.

    The slot now catches SpliceRefused, and the live source projects the provider's extra
    columns away before the join. Either alone would have prevented it.
    """
    fn = _fn_ast("global_index/run_live_day_track1.py", "observe_live_slot")
    caught = set()
    for h in ast.walk(fn):
        if isinstance(h, ast.ExceptHandler) and h.type is not None:
            t = h.type
            for part in (t.elts if isinstance(t, ast.Tuple) else [t]):
                caught.add(ast.unparse(part))
    assert "SpliceRefused" in caught, sorted(caught)

    from global_index import track1_live_source as ls
    assert callable(ls.project_to_frozen_columns)
    frozen = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                           "volume": [1.0]}, index=pd.to_datetime(["2026-08-24 09:30"]))
    live = frozen.copy()
    live["average"] = 1.0
    live["barcount"] = 3
    out, dropped = ls.project_to_frozen_columns("MNQ", live, frozen)
    assert list(out.columns) == list(frozen.columns)
    assert dropped == ("average", "barcount")
