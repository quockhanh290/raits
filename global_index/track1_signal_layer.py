"""global_index/track1_signal_layer.py — the Track 1 route's decision brain. NEW FILE.

Stage 3. Offline: nothing here connects to a broker, reads a clock, or sends an order. It
takes candidates and an open book, and returns decisions.

Relationship to the legacy signal layer
---------------------------------------
`global_index/signal_layer.py` is **not modified, not imported and not subclassed**. The two
answer different questions and unifying them would be the "patch legacy until it becomes
Track 1" move that this build is explicitly not making:

* legacy turns two ENGINE outputs into entry/exit events for three clusters, then hands them
  to `live_decision.decide_day`, which sizes every candidate as
  `contracts_by_inst[inst]` and admits it against its own cluster budget alone;
* this file is the ADMISSION layer for four sleeves whose rules interact — a family cap
  across two of them, a same-symbol invariant across all four, a force-close of one sleeve
  by another, and a quantity that belongs to the candidate rather than to the instrument.

None of those four can be expressed in `decide_day` without changing what legacy does.

Ported, with an equivalence gate — not re-derived
-------------------------------------------------
The rule set below is a port of the loop in
`scratch/track1_stage2c_book_bootstrap_20260822.py::replay`, which is itself gated against
`scratch/combined_repaired_replay_20260822.py::replay_repaired`. A second copy of a decision
rule is the failure this project has paid for more than once, so the copy is not trusted:
`scratch/test_track1_stage3_route_20260822.py` drives BOTH implementations over the same
window and requires the ordered settlement events to be identical, and then mutates one rule
at a time and requires each mutation to diverge.

Two rules that are here and not in the scratch loop
---------------------------------------------------
1. **The same-sleeve, same-instrument guard.** The scratch loop suppresses a Normal candidate
   when Calm or Stress holds the symbol, and a Calm candidate when Normal or Stress does, but
   nothing stops a second Normal position on an instrument Normal already holds. On the
   replay tables that cannot happen — the engine emits one trade per instrument at a time —
   so the rule is inert there, and the equivalence test asserts it never fires. In live it is
   the difference between an invariant and a hope.
2. **The detection-window gate.** In replay the window lives in the trade table's entry_time.
   Live, a Calm A candidate arriving at 10:20 or a Stress candidate at 12:45 has to be
   refused, and refused for a NAMED reason rather than by arriving at a book that happens not
   to want it.

Deliberately absent: the Calm-NKD switch
----------------------------------------
The scratch loop carries a `calm_nkd` branch. Calm-NKD was regenerated on the current
sleeve's basis and failed, then re-tested as a standalone tight-stop strategy and failed
again (290 of 471 stop exits booked at prices the market had already passed), then tested
with widened stops and live-stop semantics and failed a third time. It is closed. Carrying a
dead branch for a rejected strategy is how a rejected strategy comes back, so it is not here,
and the equivalence gate runs the scratch side with the switch off.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from global_index.net_exposure_multi import (ClusterBudget, MultiClusterGuard, Position,
                                             entry_priority_key)
from global_index.track1_params import (ACCOUNT, CAPS, FAMILY_CLUSTERS, FAMILY_GROSS,
                                        FAMILY_NET, ROUTE, WINDOWS_ET)

class BootstrapRefused(RuntimeError):
    """A bootstrap could not be resumed. Raised rather than returned: a caller that
    proceeds on a book it could not rebuild is trading on a book it invented."""


SWING = "roska4_swing"
CALM = "roska4_calm"
STRESS = "roska4_stress"
NKD = "global_nkd"

#: Sleeves that may hold a position across a day boundary. The other two open and close
#: inside one session, which is why they take their stop at the fill instead of deferring it.
CROSS_DAY_SLEEVES: frozenset = frozenset({SWING, NKD})

#: Which sleeves block a candidate from taking a symbol another sleeve already holds.
#: Named as data rather than written inline so the rule can be pointed at, mutated by a
#: test, and read without tracing an `if`. Stress is absent on purpose: it does not defer to
#: a holder, it displaces one — see `evaluate`.
SAME_SYMBOL_BLOCKERS: dict = {
    SWING: (STRESS, CALM),
    CALM: (SWING, STRESS),
}

#: Which sleeves a Stress entry may displace on its own symbol.
STRESS_DISPLACES: tuple = (SWING, CALM)

# Decision verbs. One per distinct outcome, because "it did not trade" is not a diagnosis —
# the same complaint `route_checkpoint.Refusal` was built to answer.
TAKE = "take"
REJECT_CAP = "reject_cap"
REJECT_FAMILY_CAP = "reject_family_cap"
SUPPRESS_SAME_SYMBOL = "suppress_same_symbol"
SUPPRESS_SAME_SLEEVE = "suppress_same_sleeve"
REJECT_WINDOW = "reject_window"
HALT_BREAKER = "halt_breaker"

DECISIONS = (TAKE, REJECT_CAP, REJECT_FAMILY_CAP, SUPPRESS_SAME_SYMBOL,
             SUPPRESS_SAME_SLEEVE, REJECT_WINDOW, HALT_BREAKER)


@dataclass(frozen=True)
class Candidate:
    """One proposed entry.

    `qty` is on the CANDIDATE, not looked up from the instrument. That is the whole point of
    this dataclass existing: MNQ under Normal is one micro and MNQ under Stress is seven, on
    the same day, and `contracts_by_inst[inst]` has no key that can say so.

    `risk_dollars` is the number the cap gate reads. For the ATR-proxy sleeves it is
    `qty x mult x daily_atr x point_value`; for Calm A it is the TRUE stop distance times
    point value times qty. Both arrive here already computed, because the two are different
    quantities and a single formula in this file would have to pick one and be wrong for the
    other.
    """
    trade_id: str
    sleeve: str
    instrument: str
    direction: str
    qty: int
    risk_dollars: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    pnl_sized: float = 0.0
    source: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def as_position(self) -> Position:
        return Position(self.instrument, self.direction, int(self.qty),
                        float(self.risk_dollars), self.sleeve)


@dataclass
class Held:
    """A position the route believes it holds."""
    candidate: Candidate
    position: Position


@dataclass(frozen=True)
class ForcedClose:
    """A position a Stress entry displaced. Never produced unless the Stress entry has
    already passed every gate — the close is the second half of an admitted decision, never
    a speculative one."""
    held: Held
    reason: str = "stress_switch"


@dataclass(frozen=True)
class Decision:
    candidate: Candidate
    verdict: str
    detail: str = ""
    forced_closes: tuple[ForcedClose, ...] = ()

    @property
    def taken(self) -> bool:
        return self.verdict == TAKE


@dataclass(frozen=True)
class Settlement:
    """A position that closed, and for how much."""
    ts: pd.Timestamp
    trade_id: str
    sleeve: str
    instrument: str
    pnl: float
    reason: str = "scheduled"


def make_guard(account: float = ACCOUNT) -> MultiClusterGuard:
    """The Track 1 cap set. Built here rather than taken from `DEFAULT_CLUSTERS`, which
    carries legacy's stress cap of 2.5% and has no Calm budget at all — a Calm candidate
    reaching legacy's guard raises `KeyError` from `_cluster_of`."""
    return MultiClusterGuard(
        clusters={name: ClusterBudget(name, gross, net) for name, (gross, net) in CAPS.items()},
        account=float(account))


def _day(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return (t.tz_localize(None) if t.tz is not None else t).normalize()


def _hhmm_on(ts, clock: str) -> str:
    """Wall-clock HH:MM of a timestamp, read on `clock`.

    An AWARE stamp is converted — that is an instant conversion with one right answer. A
    naive stamp is taken as already naming the clock, which is the convention every naive
    stamp in this route carries.

    This function used to be `_et_hhmm` and refused to convert anything, on the stated
    grounds that "the replay tables carry ET-aware entry times". That was true of every
    table that existed when the sentence was written, and false of the first Tokyo one: the
    committed NKD rows are stamped +09:00, and reading their wall clock as ET rejected 26
    of them from the replay. A docstring describing the data is a description that expires;
    converting by rule does not.
    """
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert(clock)
    return f"{t.hour:02d}:{t.minute:02d}"


def window_verdict(sleeve: str, ts) -> tuple[bool, str]:
    """Is this instant inside the sleeve's detection window?

    A sleeve with no declared window is always inside one: it enters at whatever bar its
    engine chose, and bounding that here would be inventing a rule. **Since Stage 5M-B that
    is `global_nkd` alone** — this docstring used to say "Normal, NKD", and declaring
    `roska4_swing` in `WINDOWS_ET` moved Normal-R4 to the other side of this branch.

    That is a real behavioural change and it is the intended one: a Normal-R4 candidate
    stamped outside 14:05-15:55 is now REFUSED rather than admitted. The measured rule cannot
    produce such a candidate — it scans from the 14:00 resume bar and takes the first admitted
    signal — so anything outside the window came from somewhere the rule did not.

    Calm A is a ONE-SHOT at 10:00 ET. A missed 10:00 is not entered late — the entry is the
    10:00 open and the exit is the 15:55 open, so a 10:20 entry is a different trade at a
    price that has already moved. That is the same shape as the one-shot 15:55 execution that
    was ruled a design error rather than a tolerance question.

    Stress is a WINDOW, 10:35 to 12:30 ET inclusive. Inside it a missed slot costs nothing —
    the break can be detected on any later slot. Outside it there is no entry at any price.

    Normal-R4 is a WINDOW too, 14:05 to 15:55 ET inclusive, mirroring the legacy entry slots
    minute for minute.
    """
    # The SESSION window where one is declared, the ET slot band otherwise. For every US
    # sleeve they are the same thing; for Tokyo they are not, and a candidate is a product
    # of the RULE, which decides in its session — the ET band is when the scheduler fires.
    from global_index.track1_params import SESSION_WINDOW_CLOCKS, SESSION_WINDOWS
    win = SESSION_WINDOWS.get(sleeve) or WINDOWS_ET.get(sleeve)
    if win is None:
        return True, ""
    lo, hi = win
    clock = SESSION_WINDOW_CLOCKS.get(sleeve, "America/New_York")
    clock_label = "JST" if clock == "Asia/Tokyo" else "ET"
    now = _hhmm_on(ts, clock)
    if lo <= now <= hi:
        return True, ""
    if lo == hi:
        return False, (f"{sleeve} is a one-shot at {lo} {clock_label} and this instant is {now}; "
                       f"a late entry is a different trade at a moved price")
    return False, (f"{sleeve} window is {lo}-{hi} {clock_label} and this instant is {now}")


def family_verdict(proposed: Position, open_positions: Sequence[Position], *,
                   account: float = ACCOUNT,
                   gross_cap: float | None = FAMILY_GROSS,
                   net_cap: float | None = FAMILY_NET) -> tuple[bool, str]:
    """Normal and Calm share one combined budget on top of their own.

    They are one correlation family: Calm A is long MES/MNQ into the same session Normal is
    trend-following, so two independent 5% budgets can put 10% of the account behind one
    directional view. No production equivalent exists — `MultiClusterGuard.admits` checks a
    candidate against its own cluster only, and does so deliberately.
    """
    if gross_cap is None or proposed.cluster not in FAMILY_CLUSTERS:
        return True, ""
    book = [p for p in open_positions if p.cluster in FAMILY_CLUSTERS] + [proposed]
    long_r = sum(p.risk_dollars for p in book if p.direction == "LONG")
    short_r = sum(p.risk_dollars for p in book if p.direction == "SHORT")
    gross = max(long_r, short_r) / account
    if gross > gross_cap:
        return False, f"family gross {gross:.2%} > cap {gross_cap:.2%}"
    if net_cap is not None:
        net = abs(long_r - short_r) / account
        if net > net_cap:
            return False, f"family net {net:.2%} > cap {net_cap:.2%}"
    return True, ""


@dataclass
class Track1Book:
    """The route's open book, its ledger and its gates.

    One object so that "what is open", "what is the equity" and "what would be admitted" can
    never be answered from two places. Every mutation goes through a method that returns what
    it did, so a caller in shadow mode can record the decision without applying it.
    """
    guard: MultiClusterGuard = field(default_factory=make_guard)
    breaker: Any = None
    account: float = ACCOUNT
    equity: float = ACCOUNT
    open_book: list = field(default_factory=list)
    cur_day: pd.Timestamp | None = None
    enforce_windows: bool = True
    family_gross: float | None = FAMILY_GROSS
    family_net: float | None = FAMILY_NET
    counters: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    booked: dict = field(default_factory=dict)
    route: str = ROUTE
    #: Set when a run stopped at a cut. Carried into the bootstrap so a resume can prove it
    #: is starting from the same instant the write stopped at, not from a calendar day.
    cut_instant: Any = None

    def __post_init__(self) -> None:
        for name in self.guard.clusters:
            self.counters.setdefault(f"taken:{name}", 0)
            self.counters.setdefault(f"rejected:{name}", 0)
        for verb in DECISIONS:
            self.counters.setdefault(verb, 0)
        self.counters.setdefault("double_booked", 0)
        self.counters.setdefault("forced_closes", 0)

    # ── state queries ────────────────────────────────────────────────────────
    def positions(self) -> list:
        return [h.position for h in self.open_book]

    def holders_of(self, inst: str, sleeves: Iterable[str]) -> list:
        s = set(sleeves)
        return [h for h in self.open_book
                if h.position.instrument == inst and h.position.cluster in s]

    # ── ledger ───────────────────────────────────────────────────────────────
    def _book(self, ts, cand: Candidate, pnl: float, reason: str) -> Settlement:
        self.equity += float(pnl)
        n = self.booked.get(cand.trade_id, 0) + 1
        self.booked[cand.trade_id] = n
        if n > 1:
            # A counter, never an admission input. Two settlements for one trade id is a
            # defect in whoever produced them; refusing the second here would hide it.
            self.counters["double_booked"] += 1
        ev = Settlement(pd.Timestamp(ts), cand.trade_id, cand.sleeve, cand.instrument,
                        round(float(pnl), 6), reason)
        self.events.append(ev)
        return ev

    def settle_due(self, ts) -> list:
        """Close every position whose exit time has arrived. Returns what closed."""
        out, still = [], []
        for h in self.open_book:
            xt = h.candidate.exit_time
            if xt is not None and pd.Timestamp(xt) <= pd.Timestamp(ts):
                out.append(self._book(ts, h.candidate, h.candidate.pnl_sized, "scheduled"))
            else:
                still.append(h)
        self.open_book = still
        return out

    def begin_instant(self, ts) -> bool:
        """Roll the day if it changed, mark the breaker, and report whether entries are
        allowed. Returns True when the breaker permits new risk.

        Order matters and is inherited: the day is re-based AFTER this instant's closes have
        been booked by `settle_due`, which is `decide_day`'s ordering and therefore the
        ordering every measured Track 1 figure was produced under.
        """
        day = _day(ts)
        if self.cur_day is None or day != self.cur_day:
            if self.breaker is not None:
                self.breaker.start_day(self.equity)
            self.cur_day = day
        if self.breaker is None:
            return True
        self.breaker.update(self.equity)
        return bool(self.breaker.status(self.equity).get("allow_new_entries", True))

    # ── the rule set ─────────────────────────────────────────────────────────
    def evaluate(self, cand: Candidate, *, allow: bool) -> Decision:
        """What would happen to this candidate. Applies nothing.

        Split from `apply` so that shadow mode can record a full decision stream without a
        book that drifts from the one a live run would have. The two are the same rules
        because there is only one copy of them.
        """
        if not allow:
            return Decision(cand, HALT_BREAKER, "circuit breaker refuses new entries")

        if self.enforce_windows:
            ok, why = window_verdict(cand.sleeve, cand.entry_time)
            if not ok:
                return Decision(cand, REJECT_WINDOW, why)

        # Same sleeve, same instrument. Not in the scratch loop; inert on the replay tables
        # and asserted to be inert by the equivalence test.
        if self.holders_of(cand.instrument, (cand.sleeve,)):
            return Decision(cand, SUPPRESS_SAME_SLEEVE,
                            f"{cand.sleeve} already holds {cand.instrument}")

        if cand.sleeve == STRESS:
            # Stress may displace Normal and Calm on its own symbol — but only after it has
            # passed the cap gate against the book it would leave behind. Testing the cap
            # against the surviving book rather than the current one is what makes the
            # ordering safe: nothing is closed for an entry that then gets refused.
            displaced = self.holders_of(cand.instrument, STRESS_DISPLACES)
            survivors = [h.position for h in self.open_book if h not in displaced]
            ok, why = self.guard.admits(cand.as_position(), survivors)
            if not ok:
                return Decision(cand, REJECT_CAP, why)
            return Decision(cand, TAKE, "",
                            tuple(ForcedClose(h) for h in displaced))

        if cand.sleeve in SAME_SYMBOL_BLOCKERS:
            blocking = self.holders_of(cand.instrument, SAME_SYMBOL_BLOCKERS[cand.sleeve])
            if blocking:
                held = ", ".join(sorted({h.position.cluster for h in blocking}))
                return Decision(cand, SUPPRESS_SAME_SYMBOL,
                                f"{held} already holds {cand.instrument}")
            book = self.positions()
            ok, why = self.guard.admits(cand.as_position(), book)
            if not ok:
                return Decision(cand, REJECT_CAP, why)
            ok, why = family_verdict(cand.as_position(), book, account=self.account,
                                     gross_cap=self.family_gross, net_cap=self.family_net)
            if not ok:
                return Decision(cand, REJECT_FAMILY_CAP, why)
            return Decision(cand, TAKE)

        ok, why = self.guard.admits(cand.as_position(), self.positions())
        if not ok:
            return Decision(cand, REJECT_CAP, why)
        return Decision(cand, TAKE)

    def apply(self, ts, decision: Decision, *,
              early_exit_value: Callable[[Held, pd.Timestamp], float | None] | None = None
              ) -> Decision:
        """Commit a decision to the book. Returns it unchanged, for chaining.

        `early_exit_value(held, ts)` prices a position the switch displaces. It is injected
        because the two callers value it differently and neither should be hard-coded here:
        offline it is the replay's price series, live it is the fill the broker reports back
        from the close leg. A valuer that returns None leaves the position in place — a
        position that cannot be priced must not be silently dropped from the book.
        """
        self.counters[decision.verdict] = self.counters.get(decision.verdict, 0) + 1
        cand = decision.candidate
        if not decision.taken:
            if decision.verdict in (REJECT_CAP, REJECT_FAMILY_CAP):
                key = f"rejected:{cand.sleeve}"
                self.counters[key] = self.counters.get(key, 0) + 1
            return decision

        for fc in decision.forced_closes:
            pnl = None
            if early_exit_value is not None:
                pnl = early_exit_value(fc.held, pd.Timestamp(ts))
            if pnl is None:
                continue
            self._book(ts, fc.held.candidate, float(pnl), fc.reason)
            self.open_book = [h for h in self.open_book if h is not fc.held]
            self.counters["forced_closes"] += 1

        self.open_book.append(Held(cand, cand.as_position()))
        key = f"taken:{cand.sleeve}"
        self.counters[key] = self.counters.get(key, 0) + 1
        return decision

    # ── the loop ─────────────────────────────────────────────────────────────
    def process_instant(self, ts, candidates: Sequence[Candidate], *,
                        early_exit_value=None) -> list:
        """One instant: settle what is due, mark the breaker, then decide each candidate in
        risk-high-first order. Returns the decisions, in the order they were made."""
        self.settle_due(ts)
        allow = self.begin_instant(ts)
        out = []
        for cand in sorted(candidates, key=lambda c: entry_priority_key(
                {"risk_sized": c.risk_dollars})):
            d = self.evaluate(cand, allow=allow)
            out.append(self.apply(ts, d, early_exit_value=early_exit_value))
        return out


def restore(book: "Track1Book", state: Mapping[str, Any],
            candidates: Iterable[Candidate]) -> "Track1Book":
    """Rebuild a book from a bootstrap, or refuse.

    Every carried value is restored, not a subset. Stage 2C mutated each one and required
    the resumed run to diverge: `open_pos`, `equity`, `peak_equity`, `day_start_equity`,
    `cur_day` and each position's `cluster` and `risk` all change which trades are ADMITTED,
    not merely how they are reported. A bootstrap missing one of them resumes a book whose
    breaker starts from the wrong peak and refuses or allows a whole day of entries.

    `booked` is restored too, but as the double-settlement COUNTER it is — Stage 2C mutated
    it and the match was a control, not a gap.

    A bootstrap with no `cut_instant` is REFUSED rather than resumed. The day-keyed cut it
    would have come from is not a prefix of the event sequence, which is the defect Stage 2C
    found; accepting such a file would silently reintroduce it.
    """
    if not isinstance(state, Mapping):
        raise BootstrapRefused("bootstrap is not a mapping")
    if state.get("route") not in (None, book.route):
        raise BootstrapRefused(
            f"bootstrap route={state.get('route')!r} but this book is {book.route!r}")
    if not state.get("cut_instant"):
        raise BootstrapRefused(
            "bootstrap carries no cut_instant — it was written by the old day-keyed cut and "
            "cannot be resumed correctly")
    missing = [k for k in ("equity", "peak_equity", "cur_day", "positions")
               if k not in state]
    if missing:
        raise BootstrapRefused(f"bootstrap is missing carried value(s): {missing}")

    by_id = {c.trade_id: c for c in candidates}
    book.equity = float(state["equity"])
    book.cur_day = (pd.Timestamp(state["cur_day"]).normalize()
                    if state.get("cur_day") else None)
    if book.breaker is not None:
        book.breaker.peak_equity = float(state["peak_equity"])
        dse = state.get("day_start_equity")
        book.breaker._day_start_equity = None if dse is None else float(dse)
    book.booked = dict(state.get("booked_counter") or {})
    book.open_book = []
    for row in state["positions"]:
        cand = by_id.get(row["trade_id"])
        if cand is None:
            raise BootstrapRefused(
                f"bootstrap holds {row['trade_id']!r}, which is not in this candidate "
                f"stream — the book and the stream describe different worlds")
        # The POSITION is rebuilt from the bootstrap's own cluster/qty/risk, not from the
        # candidate, so a mutation of any of those three is visible rather than healed.
        book.open_book.append(Held(cand, Position(row["instrument"], row["direction"],
                                                  int(row["qty"]),
                                                  float(row["risk_dollars"]),
                                                  row["sleeve"])))
    book.cut_instant = pd.Timestamp(state["cut_instant"])
    return book


def cut_instant_for(candidates: Iterable[Candidate], stop_after) -> pd.Timestamp:
    """The last event instant at or before `stop_after`.

    An ABSOLUTE instant, never a calendar day. `_day` strips a timezone without converting
    it, so a Tokyo-dated MNKD event can carry the next local date while occurring EARLIER
    than that afternoon's ET events — a day-keyed cut is therefore not a prefix of the true
    sequence. On the floor window that left two events on 2022-01-10 in neither half and a
    resumed book silently skipped a Stress override. Stage 2C fixed it with exactly this.

    A bare date means "the last event still inside that local day"; an explicit instant is
    used as given, which is the only way to place a cut INSIDE a trading day.
    """
    times = set()
    for c in candidates:
        times.add(pd.Timestamp(c.entry_time))
        if c.exit_time is not None:
            times.add(pd.Timestamp(c.exit_time))
    st = pd.Timestamp(stop_after)
    if st == st.normalize():
        eligible = [t for t in times if _day(t) <= _day(st)]
    else:
        eligible = [t for t in times if t <= st]
    if not eligible:
        raise ValueError(f"cut {stop_after} precedes every event in this candidate stream")
    return max(eligible)


def run_candidates(candidates: Iterable[Candidate], *, book: Track1Book,
                   early_exit_value=None, stop_after=None,
                   resume_from=None) -> tuple[list, list]:
    """Drive a whole candidate stream through one book, in absolute time order.

    Returns `(settlements, decisions)`.

    Time order is ABSOLUTE, never day-keyed. `_day` strips a timezone without converting it,
    so a Tokyo-dated MNKD event can carry the next local date while occurring earlier than
    that afternoon's ET events — a day-keyed ordering is therefore not a prefix of the true
    sequence. That is the defect Stage 2C fixed with `cut_instant`, and re-introducing a
    day key here would re-introduce it.
    """
    cands = list(candidates)
    by_time: dict = {}
    times = set()
    for c in cands:
        t = pd.Timestamp(c.entry_time)
        by_time.setdefault(t, []).append(c)
        times.add(t)
        if c.exit_time is not None:
            times.add(pd.Timestamp(c.exit_time))
    cut = pd.Timestamp(stop_after) if stop_after is not None else None
    if cut is not None and cut == cut.normalize():
        cut = cut_instant_for(cands, cut)
    start_after = pd.Timestamp(resume_from) if resume_from is not None else None

    decisions = []
    for ts in sorted(times):
        # `<=`, not `<`. The cut instant's own events are on the WRITTEN side, so resuming
        # must skip them or every event at the boundary is settled twice.
        if start_after is not None and ts <= start_after:
            continue
        if cut is not None and ts > cut:
            break
        decisions.extend(book.process_instant(ts, by_time.get(ts, []),
                                              early_exit_value=early_exit_value))
    if cut is not None:
        book.cut_instant = cut
    # Anything still open at the end stays open. Force-settling here would invent an exit
    # the strategy never took, and the end state is what a resume has to reproduce.
    return list(book.events), decisions


def daily_series(settlements: Iterable[Settlement]) -> "pd.Series":
    realized: dict = {}
    for s in settlements:
        d = _day(s.ts)
        realized[d] = realized.get(d, 0.0) + float(s.pnl)
    return pd.Series(realized).sort_index() if realized else pd.Series(dtype=float)


def event_key(s: Settlement) -> tuple:
    """The tuple two implementations must agree on, element for element.

    Counts and sums are deliberately not enough: two books that traded entirely differently
    can carry the same total, which is why the Stage 2C gate compares the ordered list.
    """
    return (str(s.ts), s.trade_id, s.sleeve, s.instrument, round(float(s.pnl), 6))
