"""global_index/track1_intraday.py — does today's bar frame actually support the decision?

Stage 3B, closing B3. Source-agnostic and offline: it takes a bar frame and an instant, and
answers whether a sleeve may decide. It never fetches anything, so it is real gate logic
rather than a promise about a source that does not exist yet — and when a live adapter is
written, the gate does not have to be written again with it.

What B3 actually was
--------------------
Legacy's freshness gate is the 13:45 ET pre-flight flag, and it works because every legacy
entry window opens after 13:45. Track 1's Calm A (10:00 ET) and Stress (10:35-12:30 ET) open
before it. `track1_freshness` already encodes the D-1 contract for the HISTORICAL inputs and
reports the intraday source as UNVERIFIED, deliberately, because it cannot see it. This file
is the part that can.

The two requirements, stated exactly
------------------------------------
**Calm A** enters at the OPEN of the 10:00 ET bar and exits at the open of the 15:55 bar. Its
gate (D-1 Calm causal, prior-close location, gap depth) is computed from the PRIOR session's
RTH, and the disaster stop is 1.5 x ATR15 which is a daily series. So the decision needs:

    prior session   09:30-16:00 ET complete and contiguous
    today           09:30 through 10:00 ET contiguous, and the 10:00 bar PRESENT
    the clock       at or after 10:00 ET — the entry price is that bar's open, and a
                    decision taken before the bar exists is a decision on a price nobody quoted

**Stress-MNQ** breaks the low of 09:30-10:30 ET, known once the 10:30-10:35 bar has closed,
and may enter from 10:35 to 12:30. So the decision needs:

    today           09:30 through 10:30 ET complete and contiguous — that IS the detector's
                    input, and a hole in it moves the low it is looking for
    the clock       at or after 10:35, and at or before 12:30
    the bar         the decision bar present
    observation     the window ledger must not report the window incomplete

Why "duplicate" and "out of order" are refusals rather than repairs
--------------------------------------------------------------------
Both are silent corrupters. `fetch_bars` sorts, but a duplicated timestamp survives sorting
and the last one wins on a reindex — which is exactly how 1050 of 1590 NKD live bars once
overwrote frozen history with a 13-hour clock error. A frame that disagrees with itself is
not one this route repairs; it is one it refuses.

Timezone is checked, not converted
-----------------------------------
A caller that hands over a tz-naive frame is asserting it is already on the ET wall clock. A
caller that hands over a tz-aware frame in another zone has made a mistake this file will not
paper over by converting: converting is how a frame ends up correct by accident and wrong the
next time the offset changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

ET = "America/New_York"

# Verdict codes. One per distinct condition — "it refused" is not a diagnosis.
OK = "ok"
NO_BARS = "no_bars"
NOT_A_FRAME = "not_a_frame"
TZ_MISMATCH = "tz_mismatch"
DUPLICATE_TIMESTAMPS = "duplicate_timestamps"
OUT_OF_ORDER = "out_of_order"
MISSING_SESSION = "missing_session"
PARTIAL_COVERAGE = "partial_coverage"
GAP_IN_COVERAGE = "gap_in_coverage"
STALE = "stale"
TOO_EARLY = "too_early"
TOO_LATE = "too_late"
DECISION_BAR_ABSENT = "decision_bar_absent"
#: Stage 5ZU. The bar whose OPEN is the fill reference is not in the frame yet, and the frame
#: is the only place the shadow route can read it. Distinct from `decision_bar_absent`, which
#: said the DECISION could not be taken — a claim that was never true for Calm.
ENTRY_QUOTE_ABSENT = "entry_quote_absent"
#: The caller did not supply the index the entry quote would be read from, so that half was
#: not checked. Never reported as a pass: a check that did not run is not a check that passed.
ENTRY_QUOTE_UNVERIFIED = "entry_quote_unverified"
WINDOW_UNOBSERVED = "window_unobserved"
UNKNOWN_SLEEVE = "unknown_sleeve"

REFUSAL_CODES = (NO_BARS, NOT_A_FRAME, TZ_MISMATCH, DUPLICATE_TIMESTAMPS, OUT_OF_ORDER,
                 MISSING_SESSION, PARTIAL_COVERAGE, GAP_IN_COVERAGE, STALE, TOO_EARLY,
                 TOO_LATE, DECISION_BAR_ABSENT, ENTRY_QUOTE_ABSENT, ENTRY_QUOTE_UNVERIFIED,
                 WINDOW_UNOBSERVED, UNKNOWN_SLEEVE)


@dataclass(frozen=True)
class Requirement:
    """What one sleeve needs from the intraday frame, in wall-clock ET."""
    sleeve: str
    bar_minutes: int
    #: today's contiguous span the decision reads, inclusive of both ends
    today_from: str
    today_to: str
    #: the bar whose OPEN is the entry, or None when the sleeve has no single entry bar
    decision_bar: str | None
    #: earliest and latest instant a decision may be taken
    decide_from: str
    decide_to: str
    #: whether the PRIOR session's RTH must also be complete
    needs_prior_rth: bool
    #: How late the scheduler child may start while still being treated as THIS slot.
    #:
    #: This is not permission to enter late. It is the small dispatch latency between the
    #: cron minute and the Python process evaluating the gate. Measured live slots start a
    #: few seconds after their nominal minute; without a grace, Calm's one-shot 10:00 slot
    #: passes at exactly 10:00:00 and refuses at 10:00:01, before the route has even had a
    #: chance to observe the bar it was scheduled for. Past this grace the slot is late and
    #: the fail-closed direction is still `too_late`.
    decision_grace_seconds: int = 60
    prior_from: str = "09:30"
    prior_to: str = "16:00"
    #: The WALL CLOCK every hh:mm above is written in, and the clock the frame's index
    #: carries. Stage 5N: until then every sleeve was a US-RTH sleeve and ET was implicit;
    #: the NKD frame is carried on Asia/Tokyo, and validating a Tokyo-stamped frame against
    #: ET wall times is a 13-hour error of exactly the shape that once overwrote 1,050
    #: frozen NKD bars. `validate` converts `now_et` to THIS clock, so every comparison in
    #: one call happens on one clock.
    clock: str = "America/New_York"
    #: Stage 5V-1. Is `today_to` the END OF A SCAN, or a bar the decision actually reads?
    #:
    #: For a one-shot sleeve it is a bar: Calm's span ends at 10:00 and 10:00 is the entry.
    #: For Stress it is a level the setup is measured on, and it sits BEFORE the decide band
    #: (10:30 against 10:35), so it is always in the past when a slot runs.
    #:
    #: For the two SCANNING sleeves it is neither. Swing and NKD take the first admitted
    #: signal anywhere in a band that ends at 15:55, so `today_to` is where the scan STOPS —
    #: and requiring the frame to reach it made every slot demand bars from the future.
    #: Measured live on 2026-08-25: nineteen consecutive NKD slots refused
    #: `partial_coverage` with "last bar in the span is 15:46, expected 15:55" while holding
    #: 107 contiguous bars of the session and a staleness check that read `ok`.
    #:
    #: True means the span's high bound follows the slot instead: the last bar that must
    #: certainly have closed. It never widens anything — the span is still contiguous from
    #: `today_from`, a hole still refuses, and staleness still requires the frame to reach
    #: the slot.
    today_to_follows_now: bool = False
    #: Stage 5ZU. The last instant the DECISION reads, when that is not `today_to`.
    #:
    #: Calm's rule is a statement about the prior RTH plus today's 09:30 open. Every input is
    #: fixed by 09:30, and the 10:00 bar contributes exactly one thing: the OPEN that the
    #: entry transacts at. Collapsing those two into `today_to`/`decision_bar` made the gate
    #: demand a CLOSED 10:00 bar before it would allow a decision that does not read it —
    #: and a closed 10:00 five-minute bar first exists at 10:05, four minutes after this
    #: sleeve's own deadline. Measured live 2026-08-26: `partial_coverage`,
    #: `decision_bar_absent`, on a frame that held everything the rule actually needs.
    required_context_through: str | None = None
    #: The bar whose OPEN is the fill reference. Checked separately, against the index the
    #: caller says that quote would be read from — never against the decision frame, because
    #: the two are on different bar sizes and that conflation is the defect above.
    required_entry_quote_time: str | None = None


REQUIREMENTS: dict = {
    # Stage 5ZU. `decision_bar` is gone and the two things it was doing are now named apart.
    #
    # `today_to` stays 10:00 — that is still where the sleeve's day ENDS as a concept — but
    # the span the decision needs runs to 09:55, the last five-minute bar that must have
    # closed before the entry instant. The 10:00 OPEN is declared as what it is: the fill
    # reference, checked against the minute index it is actually read from.
    #
    # The grace is 180s rather than 60s, and that is an OBSERVATION change, not a strategy
    # one: the entry price is still the OPEN at 10:00. A one-minute bar stamped 10:00 closes
    # at 10:01:00, so a slot dispatched at 10:00:00 cannot see that open until a minute after
    # it starts. Sixty seconds put the deadline exactly on the closing instant; three minutes
    # let the slot observe a CLOSED bar and still refuses anything past 10:03.
    "roska4_calm": Requirement(
        sleeve="roska4_calm", bar_minutes=5,
        today_from="09:30", today_to="10:00", decision_bar=None,
        decide_from="10:00", decide_to="10:00", needs_prior_rth=True,
        decision_grace_seconds=180,
        required_context_through="09:55",
        required_entry_quote_time="10:00"),
    "roska4_stress": Requirement(
        sleeve="roska4_stress", bar_minutes=5,
        today_from="09:30", today_to="10:30", decision_bar=None,
        decide_from="10:35", decide_to="12:30", needs_prior_rth=False),
    # Stage 5M-B. The sleeve scans 5-minute bars from the 14:00 resume bar and takes the FIRST
    # admitted signal anywhere in 14:05-15:55, so there is no single decision bar.
    #
    # `today_from` is 14:00, not 09:30, and that is the honest span rather than a wider one:
    # `_scan_window` reads only bars inside the window, and its volume average looks back
    # eleven bars from each one. Claiming the whole session would make the gate demand bars
    # the rule never opens, and a gate that refuses for a reason the sleeve does not have is
    # a gate people learn to widen.
    #
    # `needs_prior_rth` is False. The sleeve's cross-day state is a POSITION carried in the
    # route checkpoint, not a feature computed from yesterday's session — unlike Calm, whose
    # entire signal is a statement about the prior RTH.
    "roska4_swing": Requirement(
        sleeve="roska4_swing", bar_minutes=5,
        today_from="14:00", today_to="15:55", decision_bar=None,
        decide_from="14:05", decide_to="15:55", needs_prior_rth=False,
        today_to_follows_now=True),
    # Stage 5N. Written in the TOKYO clock, because that is the clock the MNKD frame carries
    # and the clock the rule scans in (`between_time("14:00","15:55")` on the frame).
    #
    # The decide band is the SESSION window, not the ET slot grid. The two coincide in
    # summer (14:10-15:55 JST = 01:10-02:55 ET) and drift an hour apart in winter, because
    # the scheduler is fixed in ET and Japan has no DST — legacy's own behaviour, inherited
    # deliberately. In winter the gate will refuse the late slots TOO_LATE, which is the
    # session truth: the window they would decide in has closed.
    "global_nkd": Requirement(
        sleeve="global_nkd", bar_minutes=5,
        today_from="14:00", today_to="15:55", decision_bar=None,
        decide_from="14:10", decide_to="15:55", needs_prior_rth=False,
        clock="Asia/Tokyo", today_to_follows_now=True),
}


@dataclass(frozen=True)
class Check:
    name: str
    code: str
    detail: str = ""

    @property
    def refuses(self) -> bool:
        return self.code in REFUSAL_CODES


@dataclass(frozen=True)
class Verdict:
    sleeve: str
    allow: bool
    checks: tuple
    codes: tuple = ()

    def as_dict(self) -> dict:
        return {"sleeve": self.sleeve, "allow": self.allow, "codes": list(self.codes),
                "checks": [{"name": c.name, "code": c.code, "detail": c.detail}
                           for c in self.checks]}


def _hhmm(t: str) -> pd.Timedelta:
    h, m = str(t).split(":")
    return pd.Timedelta(hours=int(h), minutes=int(m))


def _index_checks(df, clock: str = ET) -> list:
    """Shape of the index itself, before anything is asked of its contents.

    `clock` is the requirement's declared wall clock (Stage 5N) — the MNKD frame legitimately
    carries Asia/Tokyo, and a gate that demanded ET of it would refuse the sleeve's own
    session. The refusal stays for a frame on the WRONG clock: the gate still does not
    convert, because a converted frame is right by accident.
    """
    accepted = {clock} | ({"US/Eastern"} if clock == ET else set())
    out = []
    if df is None or not hasattr(df, "index"):
        return [Check("frame", NOT_A_FRAME, "no bar frame was supplied")]
    if len(df.index) == 0:
        return [Check("frame", NO_BARS, "the bar frame is empty")]
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None and str(idx.tz) not in accepted:
        out.append(Check("timezone", TZ_MISMATCH,
                         f"index carries {idx.tz}; this sleeve's gate expects the "
                         f"{clock} wall clock, and it does not convert — a converted frame "
                         f"is right by accident"))
    if idx.has_duplicates:
        dup = idx[idx.duplicated()][:3]
        out.append(Check("duplicates", DUPLICATE_TIMESTAMPS,
                         f"{int(idx.duplicated().sum())} duplicated timestamp(s), first "
                         f"{[str(x) for x in dup]} — sorting does not remove these and a "
                         f"reindex silently keeps the last"))
    if not idx.is_monotonic_increasing:
        bad = next((i for i in range(1, len(idx)) if idx[i] < idx[i - 1]), None)
        out.append(Check("ordering", OUT_OF_ORDER,
                         f"first backwards step at position {bad}: "
                         f"{idx[bad - 1]} then {idx[bad]}"))
    return out


def _naive(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_localize(None) if idx.tz is not None else idx


def _last_closed_bar(now: pd.Timestamp, bar_minutes: int) -> pd.Timestamp:
    """The newest grid point whose bar must CERTAINLY have finished by `now`.

    Stage 5V-1. Flooring `now` to the grid is not enough: a slot fires seconds after its own
    minute, and the bar the fetch was told to stop at is the one still open — Stage 5R-0 drops
    it precisely because it is not finished. So the answer is one whole bar back from the
    floor: at 14:12 on a five-minute grid it is 14:05, and at 14:10:03 it is also 14:05.

    This is the same arithmetic the staleness check allows (`last + bar_minutes >= horizon`),
    written once so the span and the staleness rule cannot disagree about which bar the frame
    owes.
    """
    n = pd.Timedelta(minutes=int(bar_minutes))
    return pd.Timestamp(now).floor(n) - n


def _as_hhmm(delta: pd.Timedelta) -> str:
    """A within-day offset back into the `HH:MM` vocabulary the requirement is written in."""
    total = int(delta.total_seconds()) // 60
    return f"{total // 60:02d}:{total % 60:02d}"


def _span_check(name: str, idx: pd.DatetimeIndex, day: pd.Timestamp,
                lo: str, hi: str, step_minutes: int) -> list:
    """Every bar from lo to hi inclusive, on `day`, with no hole."""
    want_lo, want_hi = day + _hhmm(lo), day + _hhmm(hi)
    have = idx[(idx >= want_lo) & (idx <= want_hi)]
    if len(have) == 0:
        return [Check(name, MISSING_SESSION,
                      f"no bars at all between {lo} and {hi} on {day.date()}")]
    out = []
    if have[0] > want_lo:
        out.append(Check(name, PARTIAL_COVERAGE,
                         f"first bar in the span is {have[0]}, expected {want_lo}"))
    if have[-1] < want_hi:
        out.append(Check(name, PARTIAL_COVERAGE,
                         f"last bar in the span is {have[-1]}, expected {want_hi}"))
    step = pd.Timedelta(minutes=int(step_minutes))
    gaps = [(have[i - 1], have[i]) for i in range(1, len(have))
            if (have[i] - have[i - 1]) > step]
    if gaps:
        out.append(Check(name, GAP_IN_COVERAGE,
                         f"{len(gaps)} hole(s); first between {gaps[0][0]} and {gaps[0][1]} "
                         f"({(gaps[0][1] - gaps[0][0]).total_seconds() / 60:.0f} min > "
                         f"{step_minutes} min)"))
    if not out:
        out.append(Check(name, OK, f"{len(have)} bars {lo}-{hi} contiguous"))
    return out


#: Stage 5ZX. Requirements keyed by (sleeve, PHASE), for the sleeves whose evidence is split
#: across two slots. Looked up by `requirement_for` and used ONLY when a phase is named — the
#: table above is untouched, so every unsplit sleeve and every unphased call gate exactly as
#: they did before.
#:
#: Calm is the only entry today, and only because its two phases read different bar sizes at
#: different instants. Writing one requirement that admitted both would mean a gate that asks
#: for the loosest of each pair, which is a gate that passes at 09:32 something only true at
#: 10:01.
PHASE_REQUIREMENTS: dict = {
    # DECIDE. The rule is complete once today's 09:30 MINUTE bar has closed: everything else it
    # reads closed yesterday. So this validates the ONE-minute frame, spans exactly that one
    # bar, and — the defining property — declares NO entry quote. A DECIDE phase that required
    # an entry quote would be the 10:00 slot again under a new name.
    #
    # `decide_to` is 09:59 with no grace, and the missing minute is deliberate. At 10:00:00 the
    # entry happens; an "intent" first written at or after that instant is not an intent, it is
    # a description of something already in flight. The gate is where that stays true even if a
    # scheduler runs late.
    ("roska4_calm", "DECIDE"): Requirement(
        sleeve="roska4_calm", bar_minutes=1,
        today_from="09:30", today_to="09:30", decision_bar=None,
        decide_from="09:31", decide_to="09:59", needs_prior_rth=True,
        decision_grace_seconds=0,
        required_context_through="09:30",
        required_entry_quote_time=None),
    # OBSERVE. Reads one thing the decide half could not: the 10:00 open, from a CLOSED minute
    # bar. So the entry quote is required here and the frame is again the minute one. It decides
    # nothing — by the time it runs, the decision is half an hour old and recorded.
    ("roska4_calm", "OBSERVE"): Requirement(
        sleeve="roska4_calm", bar_minutes=1,
        today_from="09:30", today_to="10:00", decision_bar=None,
        decide_from="10:01", decide_to="10:30", needs_prior_rth=True,
        decision_grace_seconds=0,
        required_context_through="10:00",
        required_entry_quote_time="10:00"),
}


def requirement_for(sleeve: str, phase: str = "") -> "Requirement | None":
    """The requirement governing this slot, phase included.

    An UNKNOWN phase returns `None` rather than falling back to the sleeve's own requirement.
    Falling back is the tempting choice and the wrong one: a typo in a scheduler argument would
    then gate a decide-half slot with the entry-half rule, pass it at the wrong instant, and
    look in every record exactly like a slot that ran correctly.
    """
    if not phase:
        return REQUIREMENTS.get(sleeve)
    return PHASE_REQUIREMENTS.get((sleeve, phase))


def validate(sleeve: str, bars, *, now_et, session_day=None,
             prior_session_day=None, ledger_status: Mapping[str, Any] | None = None,
             requirement: Requirement | None = None,
             entry_quote_index=None) -> Verdict:
    """May `sleeve` take a decision at `now_et` on this frame? Fails closed.

    `bars` is any object with a DatetimeIndex on the ET wall clock — a live fetch, a slice of
    parquet, or a frame built by a test. That is the point of the signature: the rule is not
    entangled with where the bars came from.

    `ledger_status` is what `window_ledger.status` returned for this sleeve and date, when
    the caller has it. Absent, it is not checked — and the check that IS run says so, rather
    than reporting a pass it did not perform.
    """
    req = requirement or REQUIREMENTS.get(sleeve)
    if req is None:
        return Verdict(sleeve, False,
                       (Check("sleeve", UNKNOWN_SLEEVE,
                              f"{sleeve!r} declares no intraday requirement; known: "
                              f"{sorted(REQUIREMENTS)}"),), (UNKNOWN_SLEEVE,))

    checks = list(_index_checks(bars, req.clock))
    if any(c.code in (NOT_A_FRAME, NO_BARS) for c in checks):
        return Verdict(sleeve, False, tuple(checks),
                       tuple(c.code for c in checks if c.refuses))

    idx = _naive(pd.DatetimeIndex(bars.index))
    now = pd.Timestamp(now_et)
    if now.tzinfo is not None:
        # The requirement's OWN clock, not ET unconditionally. Every hh:mm in the
        # requirement and every stamp in the frame are on that clock, so the instant the
        # caller passes must be read on it too — or the staleness check compares a Tokyo
        # last-bar against an ET horizon and becomes vacuously green.
        now = now.tz_convert(req.clock).tz_localize(None)
    day = pd.Timestamp(session_day).normalize() if session_day is not None else now.normalize()

    # ── the clock ────────────────────────────────────────────────────────────
    earliest = day + _hhmm(req.decide_from)
    latest = day + _hhmm(req.decide_to) + pd.Timedelta(seconds=req.decision_grace_seconds)
    if now < earliest:
        checks.append(Check("clock", TOO_EARLY,
                            f"{now} is before {earliest}; the decision bar has not opened, so "
                            f"there is no price to decide on"))
    elif now > latest:
        checks.append(Check("clock", TOO_LATE,
                            f"{now} is after {latest}; "
                            + ("this sleeve is a one-shot and a late entry is a different "
                               "trade at a moved price" if req.decide_from == req.decide_to
                               else "the entry window has closed")))
    else:
        checks.append(Check("clock", OK, f"{now} is inside {earliest}..{latest}"))

    # ── today's span the decision reads ──────────────────────────────────────
    #
    # Stage 5V-1. For a SCANNING sleeve the high bound follows the slot rather than the end of
    # the band, because the end of the band is in the future for every slot but the last. The
    # bound is `last_closed_bar(now)` — the newest grid point whose bar must certainly have
    # finished — and it is deliberately the SAME arithmetic the staleness check below allows,
    # so the two can never disagree about which bar the frame owes.
    #
    # It cannot widen anything: `min` with `today_to` keeps the declared end as a ceiling, the
    # span is still required contiguous from `today_from`, a hole still refuses, and staleness
    # still requires the frame to reach the slot. What it stops requiring is bars that do not
    # exist yet.
    # Stage 5ZU. When the sleeve declares how far the DECISION reads, that is the span — not
    # the end of its conceptual day. It can only ever be narrower: `required_context_through`
    # names a bar at or before `today_to`, and a hole inside the span still refuses.
    today_hi = req.required_context_through or req.today_to
    if req.today_to_follows_now:
        closed = _last_closed_bar(now, req.bar_minutes)
        declared_hi = day + _hhmm(req.today_to)
        if closed < declared_hi:
            today_hi = _as_hhmm(closed - day)
    checks.extend(_span_check("today_span", idx, day, req.today_from, today_hi,
                              req.bar_minutes))

    # ── the decision bar itself ──────────────────────────────────────────────
    if req.decision_bar is not None:
        want = day + _hhmm(req.decision_bar)
        if want not in set(idx):
            checks.append(Check("decision_bar", DECISION_BAR_ABSENT,
                                f"no bar at {want}; its OPEN is the entry price"))
        else:
            checks.append(Check("decision_bar", OK, f"bar at {want} present"))

    # ── the entry quote: the OPEN the fill transacts at ──────────────────────
    #
    # Checked against `entry_quote_index`, which the caller says is where that quote is read
    # from — the MINUTE index, not the five-minute decision frame. They are different bar
    # sizes and treating them as one is exactly what made Calm impossible: a 10:00 open is
    # readable from a closed one-minute bar at 10:01 and from a closed five-minute bar only
    # at 10:05, and the sleeve's deadline sits between the two.
    #
    # Absent index means the caller did not offer one, and that is reported as UNVERIFIED
    # rather than passed. A check that did not run is not a check that passed.
    if req.required_entry_quote_time is not None:
        want_q = day + _hhmm(req.required_entry_quote_time)
        if entry_quote_index is None:
            checks.append(Check("entry_quote", ENTRY_QUOTE_UNVERIFIED,
                                f"no index was offered to read the {want_q} OPEN from, so "
                                f"whether the fill reference exists was not established"))
        # Put the quote index on the same clock the rest of this function works in — the
        # requirement's clock, made naive — using the SAME helper the decision frame goes
        # through. A tz-aware stamp never equals a naive one, so comparing them directly
        # would report every quote absent, always, and look exactly like a real refusal.
        elif want_q not in set(_naive(pd.DatetimeIndex(entry_quote_index)
                                      .tz_convert(req.clock)
                                      if pd.DatetimeIndex(entry_quote_index).tz is not None
                                      else pd.DatetimeIndex(entry_quote_index))):
            checks.append(Check("entry_quote", ENTRY_QUOTE_ABSENT,
                                f"no bar at {want_q} in the quote index; its OPEN is the "
                                f"entry price and the decision cannot be priced without it"))
        else:
            checks.append(Check("entry_quote", OK, f"the {want_q} OPEN is readable"))

    # ── staleness: the frame must reach the decision instant ─────────────────
    #
    # Stage 5V-1. The horizon is the last bar that must CERTAINLY have closed, not the raw
    # instant. Comparing a grid-quantised frame against a continuous `now` made this fire by
    # SECONDS: a slot fires about three seconds after its own minute, the newest complete
    # five-minute bucket is therefore exactly one bar back, and `last + 5min < now` was true
    # by that three seconds. Measured live on 2026-08-25 at 15:50:03 JST — "last bar 15:45 is
    # more than one 5-minute bar behind 15:50:03" — on a frame that was not stale at all.
    #
    # It does not weaken the check. A frame two bars behind still refuses, and the arithmetic
    # is the SAME `_last_closed_bar` the span above uses, so the two cannot disagree about
    # which bar the frame owes.
    last = idx[-1]
    horizon = min(_last_closed_bar(now, req.bar_minutes), latest)
    if last < horizon:
        checks.append(Check("staleness", STALE,
                            f"last bar {last} is behind {horizon}, the newest "
                            f"{req.bar_minutes}-minute bar that must have closed by {now}"))
    else:
        checks.append(Check("staleness", OK, f"last bar {last}"))

    # ── the prior session, where the gate reads it ───────────────────────────
    if req.needs_prior_rth:
        prior = (pd.Timestamp(prior_session_day).normalize()
                 if prior_session_day is not None else _prev_business_day(day))
        checks.extend(_span_check("prior_rth", idx, prior, req.prior_from, req.prior_to,
                                  req.bar_minutes))

    # ── did anyone actually watch the window ─────────────────────────────────
    if ledger_status is None:
        checks.append(Check("window_observation", OK,
                            "not supplied by the caller, so not checked — this is a "
                            "statement that the check did not run, not that it passed"))
    elif ledger_status.get("outcome") == "complete":
        checks.append(Check("window_observation", OK, "window ledger reports complete"))
    else:
        checks.append(Check("window_observation", WINDOW_UNOBSERVED,
                            f"window ledger reports {ledger_status.get('outcome')!r} "
                            f"({ledger_status.get('observed_slots')} of "
                            f"{ledger_status.get('expected_slots')} slots); absence of a "
                            f"complete observation is itself the signal"))

    codes = tuple(c.code for c in checks if c.refuses)
    return Verdict(sleeve, not codes, tuple(checks), codes)


def _prev_business_day(day: pd.Timestamp) -> pd.Timestamp:
    x = pd.Timestamp(day).normalize() - pd.Timedelta(days=1)
    while x.weekday() >= 5:
        x -= pd.Timedelta(days=1)
    return x


def synth_bars(day, lo: str, hi: str, step_minutes: int = 5, *, tz: str | None = None,
               price: float = 100.0) -> "pd.DataFrame":
    """A contiguous OHLCV frame for one span. For tests and for exercising the gate offline.

    Kept here rather than in the test file so the gate and the thing that satisfies it cannot
    drift: a fixture that builds bars the validator happens to accept, written beside the
    validator, would only ever agree with itself.
    """
    d = pd.Timestamp(day).normalize()
    idx = pd.date_range(d + _hhmm(lo), d + _hhmm(hi), freq=f"{int(step_minutes)}min")
    if tz is not None:
        idx = idx.tz_localize(tz)
    return pd.DataFrame({"open": price, "high": price + 1.0, "low": price - 1.0,
                         "close": price, "volume": 1000.0}, index=idx)
