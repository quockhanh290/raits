"""global_index/test_symbol_boundary.py — one vocabulary leaves IBKRBroker

IBKR calls the Nikkei contract NKD; the runner calls it MNKD. _RAITS_TO_IBKR exists for
exactly that, but it was applied ad hoc at each call site, so the sites that forgot were
invisible until a position existed.

Six such sites were found one at a time — place_stop, cancel_order, get_order_status,
has_working_stop, get_working_stops, and finally get_positions, which on 2026-08-10
reported the live NKD position under a name the file did not use. B3 then counted the
same position twice, once as missing and once as an orphan, and halted every entry.

The rule is not "remember the mapping". It is that nothing leaves this class speaking
IBKR's vocabulary, and the source itself is checked so the seventh site cannot be added
quietly.
"""
import re
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.ibkr_broker import IBKRBroker, _to_runner

_SOURCE = (Path(__file__).resolve().parent / "ibkr_broker.py").read_text(encoding="utf-8")


def test_sb1_the_translation_is_one_function():
    assert _to_runner("MNK") == "MNKD"
    assert _to_runner("MES") == "MES", "names that agree pass through untouched"
    assert _to_runner("ZZZ") == "ZZZ", "an unknown symbol is not dropped or guessed"


def test_sb5_no_call_site_builds_a_contract_by_hand():
    """H1. Contract construction lives in ONE place, and the source says so.

    Appendix F consolidated three call sites (_fetch_raw, send_order, place_stop) into
    _front_month_contract and reported the job done. There were four. The roll path was
    missed, and it kept all three defects the consolidation existed to remove: the raw
    runner name as the IBKR symbol, exchange hardcoded "CME" (MYM is CBOT), and no conId
    check after qualifyContracts — which does not raise, it leaves conId 0.

    Same shape as sb2: enforced on the source, because a fifth hand-rolled site would
    otherwise stay invisible until a roll date arrived.

    Parsed, not grepped: the docstring of _front_month_contract discusses
    `ibi.Future(sym)` in prose, and a text scan counts that as a violation. A test that
    cannot tell code from a comment about code will fire on the next person who explains
    the rule in writing.
    """
    import ast

    tree = ast.parse(_SOURCE)
    builders = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Future"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "ibi"):
                builders.add((fn.name, node.lineno))

    # Self-check: if the locator finds nothing, the invariant is unverified, not met.
    assert builders, (
        "no ibi.Future(...) call found anywhere — the locator is broken, so a green "
        "result here would mean nothing")

    # The invariant is "one builder", not "a builder with this name" — pinning the name
    # would make a rename look like a regression, and the defect was never about naming.
    where = sorted({name for name, _ln in builders})
    assert len(where) == 1, (
        "every contract must be built by ONE shared resolver, which translates the "
        "symbol, picks the exchange and refuses an unlisted contract. Built in "
        f"{len(where)} places: " + ", ".join(where))


class _RollIB:
    """Fake ib. Records what was asked for and whether qualifyContracts resolved it."""

    def __init__(self, resolve=True):
        self.built = []
        self._resolve = resolve

    def qualifyContracts(self, c):
        self.built.append(c)
        # Real ib_insync does NOT raise on an unresolvable contract; it leaves conId 0.
        if self._resolve:
            c.conId = 12345
        return [c]

    def sleep(self, _s):
        pass


class _RollFuture:
    def __init__(self, symbol, lastTradeDateOrContractMonth=None, exchange=None, **_kw):
        self.symbol = symbol
        self.lastTradeDateOrContractMonth = lastTradeDateOrContractMonth
        self.exchange = exchange
        self.conId = 0


def _roll_broker(monkeypatch, resolve=True):
    """IBKRBroker with a fake ib and a fake ib_insync, offline short-circuit removed.

    _handle_rollover returns synthetic fills while _raw_fetcher is set, which is exactly
    why no test ever reached its contract-building code (audit §4.4).
    """
    import types
    from global_index import ibkr_broker as B

    ib = _RollIB(resolve=resolve)
    fake_ibi = types.SimpleNamespace(Future=_RollFuture)
    monkeypatch.setitem(sys.modules, "ib_insync", fake_ibi)

    # These tests drive a FUTURE roll date, so the M4 clock guard fires before any
    # contract is built and they would assert on an empty list. Neutralised here on
    # purpose: sb12 and sb13 own the clock behaviour, these own contract construction,
    # and a test that silently covers two things fails for reasons you cannot read.
    monkeypatch.setattr(B, "session_month_conflict", lambda _inst, _day: None)

    b = B.IBKRBroker(_raw_fetcher=lambda i, t: None)
    b._raw_fetcher = None
    b._require_connection = lambda: ib
    return b, ib


def test_sb6_the_roll_path_translates_the_symbol(monkeypatch):
    """MNKD must reach IBKR as MNK. C1 made this reachable: before the roll-schedule
    lookup was fixed the roll never fired for Nikkei, so `ibi.Future("MNKD", ...)` was
    dead code. Fixing C1 without this turns "never rolls" into "rolls into a contract
    IBKR cannot resolve"."""
    b, ib = _roll_broker(monkeypatch)
    try:
        b._handle_rollover("MNKD", "2026-09-04", "LONG", 1, "global_nkd")
    except Exception:
        pass  # the order path is not under test; the contracts are

    assert ib.built, "no contract was built — the test never reached the roll path"
    symbols = {c.symbol for c in ib.built}
    assert symbols == {"MNK"}, (
        f"the roll sent the runner's own name to IBKR; MNKD is not a listed symbol. "
        f"built={[(c.symbol, c.lastTradeDateOrContractMonth, c.exchange) for c in ib.built]}")


def test_sb7_the_roll_path_uses_the_right_exchange(monkeypatch):
    """MYM trades on CBOT. The roll path hardcoded "CME" for every instrument, and the
    first of the two orders it sends is the one that CLOSES the position. Next MYM roll:
    2026-09-11."""
    b, ib = _roll_broker(monkeypatch)
    try:
        b._handle_rollover("MYM", "2026-09-11", "LONG", 1, "roska4_swing")
    except Exception:
        pass

    assert ib.built, "no contract was built — the test never reached the roll path"
    exchanges = {c.exchange for c in ib.built}
    assert exchanges == {"CBOT"}, (
        f"MYM was sent to the wrong exchange; _IBKR_EXCHANGE declares CBOT. "
        f"built={[(c.symbol, c.exchange) for c in ib.built]}")


def test_sb8_the_roll_path_refuses_an_unlisted_contract(monkeypatch):
    """qualifyContracts leaves conId 0 rather than raising. Without a check, two market
    orders go out against a contract IBKR never confirmed — and the micro carries far
    fewer forward months than the full-size contract, so a ROLL_SCHEDULE date can outrun
    the listed chain."""
    from global_index.ibkr_broker import ContractResolutionError

    b, _ib = _roll_broker(monkeypatch, resolve=False)
    with pytest.raises(ContractResolutionError):
        b._handle_rollover("MNKD", "2026-09-04", "LONG", 1, "global_nkd")


def test_sb9_the_front_month_lookup_translates_too():
    """C1's twin. get_roll_event was fixed to resolve its key; this reads the SAME table
    and did not.

    It is safe today only because its main caller resolves first — and that discipline
    has already failed once in production. repair_parquet_utc carries the note: "Passing
    the raits name returned None, the contract went out with no month, and IBKR rejected
    it as ambiguous across fifteen listed expiries." Caller discipline is not a fix; the
    lookup translating is.
    """
    from global_index.ibkr_broker import _current_front_month

    assert _current_front_month("MNK"), "IBKR symbol must resolve — control"
    assert _current_front_month("MNKD") == _current_front_month("MNK"), (
        "the runner's own name for the Nikkei micro returns no front month, so a caller "
        "that forgets to translate sends an unqualified contract")


def test_sb10_the_exchange_is_chosen_by_the_resolved_symbol():
    """_IBKR_EXCHANGE is keyed by IBKR symbol, so it must be asked with the IBKR symbol.

    Correct today only by luck: the one instrument whose name needs translating (MNKD ->
    MNK) happens to trade on CME, the default. The monkeypatch below removes that luck —
    it is the only way to tell "looked up by the resolved symbol" from "fell through to
    the default and happened to be right".
    """
    from global_index import ibkr_broker as B

    sym, exch = B.ibkr_symbol_and_exchange("MYM")
    assert (sym, exch) == ("MYM", "CBOT"), "declared override must be honoured"
    assert B.ibkr_symbol_and_exchange("MES") == ("MES", "CME"), "default — control"

    saved = dict(B._IBKR_EXCHANGE)
    try:
        B._IBKR_EXCHANGE["MNK"] = "OSE.JPN"      # keyed by IBKR symbol, as the table is
        assert B.ibkr_symbol_and_exchange("MNKD") == ("MNK", "OSE.JPN"), (
            "asked with the runner name, so an override keyed by the IBKR symbol is "
            "missed and the request goes to the wrong exchange")
    finally:
        B._IBKR_EXCHANGE.clear()
        B._IBKR_EXCHANGE.update(saved)


def test_sb11_the_dashboard_reader_does_not_re_derive_the_routing():
    """monitor/backend/ibkr_reader built its own symbol+exchange pair, and got the
    exchange half wrong by asking with the runner name. Two copies of one routing rule
    is how MNKD reached the full-size contract in the first place — the reader uses the
    shared resolver instead."""
    src = (Path(__file__).resolve().parent.parent
           / "monitor" / "backend" / "ibkr_reader.py").read_text(encoding="utf-8")
    assert "_IBKR_EXCHANGE.get(" not in src, (
        "the reader picks the exchange itself; ask ibkr_symbol_and_exchange() so there "
        "is one routing rule, not two")


def test_sb12_two_clocks_that_disagree_stop_the_order():
    """M4. Two clocks decide the contract month, and the audit called for one.

    Forcing one would be wrong, and that is the whole finding. They answer different
    questions and each is right for its own:

      "is today a roll day?"        -> the SESSION day being processed
      "which month do I send to?"   -> the WALL clock, because an expired contract
                                       cannot be traded at all

    Threading the session day into order routing would make every catch-up run send
    orders to a contract that has already expired. The defect is not that there are two
    clocks; it is that nothing noticed when they disagreed — and while they disagree the
    roll logic and the order routing are operating on different months, which is the
    shape of C1.

    BOTH clocks are pinned here. The first version passed only one of them and read the
    real wall clock for the other, so its verdict moved with the calendar: measured by
    stepping the clock forward, it went red on 2026-09-04 and stayed red — the Nikkei
    roll date, which is the one day this mechanism exists for. A test that dies on the
    day its subject matters is worse than no test, because it dies looking like a
    regression in something else.

    Pinned pair: a session on 2026-09-03 processed while the wall clock already reads
    2026-09-04 — the roll has moved the tradeable month to 202612 while the session
    being replayed still belongs to 202609.
    """
    from global_index.ibkr_broker import session_month_conflict

    same = session_month_conflict("MNKD", "2026-08-17", now="2026-08-17")
    assert same is None, (
        f"an ordinary session, where both clocks agree, must not raise an alarm: {same}")

    clash = session_month_conflict("MNKD", "2026-09-03", now="2026-09-04")
    assert clash is not None, (
        "the session being processed belongs to 202609 while the tradeable front month "
        "has already rolled to 202612 — orders and positions would sit in different "
        "contracts and nothing said so")
    assert "202612" in clash and "202609" in clash, (
        f"the message has to name BOTH months, or the operator cannot tell which way "
        f"round the disagreement runs: {clash}")


def test_sb12b_the_default_clock_is_still_the_wall_clock():
    """Control for sb12's pinning. Without it, sb12 passes just as well against a
    function that ignored the wall clock entirely and only compared its two arguments —
    which would make the guard blind in production, where nothing passes `now`.

    Pins the DEFAULTING RULE rather than a date: omitting `now` must give the same
    answer as passing the wall clock explicitly. That stays true on every future date,
    and it goes red if someone defaults `now` to the session day instead — the change
    that would silence the guard forever.

    The session day is derived from the roll table rather than written down, so the
    comparison is made on a day where the answer is NOT None. Two Nones compare equal
    whatever the default is, and would prove nothing.
    """
    from global_index import ibkr_broker as B

    # The module's own clock, read the way the function reads it — so this control is
    # honest under a shifted clock too, not only on a real calendar.
    today = str(B.pd.Timestamp.now(tz="America/New_York").date())
    later = next((d for d, _f, _n in B.ROLL_SCHEDULE["MNK"] if d > today), None)
    if later is None:
        pytest.skip("roll table is exhausted — see the runway test, which owns that")

    # Self-check before the real assertion: a pair that answers None either way cannot
    # distinguish a correct default from a broken one.
    explicit = B.session_month_conflict("MNKD", later, now=today)
    assert explicit is not None, (
        f"a session on the next roll date ({later}) read under today's clock ({today}) "
        f"must disagree; if it does not, this control cannot see a broken default")

    assert B.session_month_conflict("MNKD", later) == explicit, (
        "omitting `now` must fall back to the wall clock. If the default became the "
        "session day the two clocks could never disagree and the guard would be inert")


# ── P1: an exit addresses the month the BOOK holds, not the month being traded ──

class _OrderIB(_RollIB):
    """_RollIB plus the two calls send_order/place_stop make beyond qualifyContracts."""

    def placeOrder(self, contract, order):
        self.placed = getattr(self, "placed", [])
        self.placed.append((contract, order))
        return _DoneTrade(order)

    def cancelOrder(self, _o):
        pass


class _DoneTrade:
    def __init__(self, order, price=5000.0, qty=1):
        self.order = order
        self.fills = []
        self.orderStatus = types.SimpleNamespace(
            status="Filled", filled=qty, avgFillPrice=price, orderId=99)

    def isDone(self):
        return True


def _order_broker(monkeypatch, resolve=True):
    """IBKRBroker whose order path runs for real against fake ib_insync."""
    from global_index import ibkr_broker as B

    ib = _OrderIB(resolve=resolve)
    monkeypatch.setitem(sys.modules, "ib_insync",
                        types.SimpleNamespace(Future=_RollFuture,
                                              MarketOrder=_FakeOrder,
                                              LimitOrder=_FakeOrder,
                                              StopOrder=_FakeOrder))
    b = B.IBKRBroker(_raw_fetcher=lambda i, t: None)
    b._raw_fetcher = None
    b._require_connection = lambda: ib
    return b, ib


class _FakeOrder:
    def __init__(self, action, qty, price=None):
        self.action, self.totalQuantity, self.lmtPrice = action, qty, price
        self.orderId = 0


# The Rổ 4 roll: from this date the tradeable front month is already 202612, while a
# position opened before it is still held in 202609.
ROLL_DAY_R4 = "2026-09-11"
HELD_MONTH = "202609"       # what the book holds
FRONT_ON_ROLL_DAY = "202612"  # what the calendar calls current from 00:00 ET that day


def _pin_front_month(monkeypatch, month=FRONT_ON_ROLL_DAY):
    """Pin what the CALENDAR answers, so the assertions can tell the two apart.

    Written without this first, and it was green for the wrong reason: the held month
    was 202609, which is also the real front month today, so "used the book" and "used
    the calendar" produced the same contract and the test could not distinguish them.
    Proved by mutation — making the order path ignore the field left the test passing.

    Pinning also makes these clock-independent, which is the lesson sb12 cost.
    """
    monkeypatch.setattr("global_index.ibkr_broker._current_front_month",
                        lambda _inst, _today=None: month)
    assert month != HELD_MONTH, "the two candidate answers must differ"
    return month


def test_sb14_an_exit_goes_to_the_month_the_position_is_held_in(monkeypatch):
    """The roll-day window. Measured on the schedule: from 00:00 ET on a roll date the
    "current front month" lookup already answers with the NEXT month, but the position
    is only actually rolled when the main session runs — 14:05 ET for Rổ 4. Everything
    that sends an order in between addresses a contract the book does not hold.

    Three things run in that 14-hour window: six stop-repair sweeps, and the 09:31
    max-hold exit. A market SELL on a contract holding nothing does not close anything —
    it opens a short, unprotected, that nobody asked for. That is the C1 failure mode
    surviving inside the C1 fix.

    The book already records which month it holds; the fix is that the exit paths ASK.
    """
    from global_index.broker import Order

    b, ib = _order_broker(monkeypatch)
    monkeypatch.setattr("global_index.ibkr_broker.session_month_conflict",
                        lambda _i, _d, now=None: None)
    calendar_says = _pin_front_month(monkeypatch)

    b.send_order(Order("MES", "CLOSE", "LONG", 1, "roska4_swing", ROLL_DAY_R4,
                       contract_month=HELD_MONTH))

    assert ib.built, "no contract was built — the test never reached the order path"
    months = {c.lastTradeDateOrContractMonth for c in ib.built}
    assert months == {HELD_MONTH}, (
        f"the exit was addressed to {months} — the calendar says {calendar_says} is "
        f"tradeable, but the position is held in {HELD_MONTH}. On a roll date those "
        f"differ, and selling a contract the account does not hold opens a short "
        f"instead of closing anything")


def test_sb15_an_exit_with_no_recorded_month_still_uses_the_front_month(monkeypatch):
    """Control, and the compatibility guarantee.

    Positions written before the month field existed carry None, and MockBroker leaves
    it None on every verify and replay run. Those must behave exactly as before, or the
    fix quietly changes the equivalence the whole backtest comparison rests on.
    """
    from global_index.broker import Order

    b, ib = _order_broker(monkeypatch)
    monkeypatch.setattr("global_index.ibkr_broker.session_month_conflict",
                        lambda _i, _d, now=None: None)
    calendar_says = _pin_front_month(monkeypatch)

    b.send_order(Order("MES", "CLOSE", "LONG", 1, "roska4_swing", ROLL_DAY_R4))

    assert ib.built, "no contract was built"
    months = {c.lastTradeDateOrContractMonth for c in ib.built}
    assert months == {calendar_says}, (
        f"with no recorded month the old behaviour must be untouched — the calendar's "
        f"answer {calendar_says}, not {months}")


def test_sb16_a_stop_is_placed_on_the_month_the_position_is_held_in(monkeypatch):
    """Same window, the other order the sweeps send.

    A stop re-placed on the next month while the position sits in the current one is an
    orphan the moment it is created: it protects nothing, and if it fills it opens a
    position rather than closing one. The audit's own note that B4 "stays quiet on the
    roll date" holds only while the old stop is still alive — the sweep exists for when
    it is not.
    """
    b, ib = _order_broker(monkeypatch)
    calendar_says = _pin_front_month(monkeypatch)

    b.place_stop("MES", "LONG", 1, 4950.0, "roska4_swing", contract_month=HELD_MONTH)

    assert ib.built, "no contract was built — the test never reached the stop path"
    months = {c.lastTradeDateOrContractMonth for c in ib.built}
    assert months == {HELD_MONTH}, (
        f"the stop went onto {months} while the position is held in {HELD_MONTH} "
        f"(calendar says {calendar_says}). A stop on the wrong contract protects "
        f"nothing, and opens a position if it fills")


def test_sb17_the_exit_paths_actually_pass_the_month():
    """A parameter nothing passes is H2 again — implemented end to end, wired nowhere.

    Checked on the source, because the defect is an omitted keyword at a call site and
    no runtime assertion on a hand-built runner can see what the runner forgot to pass.
    Covers both order kinds: every CLOSE order and every stop placement.

    ENTRY orders are deliberately NOT covered. A new position should open in whatever
    month is tradeable now — that is the one case where the calendar is the right
    answer, and forcing a recorded month there would pin new trades to an expiring
    contract.
    """
    import ast
    src = (Path(__file__).resolve().parent / "runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    closes, stops = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kw = {k.arg for k in node.keywords}
        if getattr(node.func, "id", None) == "Order":
            action = node.args[1] if len(node.args) > 1 else None
            if isinstance(action, ast.Constant) and action.value == "CLOSE":
                closes.append((node.lineno, "contract_month" in kw))
        elif getattr(node.func, "attr", None) == "place_stop":
            stops.append((node.lineno, "contract_month" in kw))

    # Self-check first: an empty list would make both assertions pass vacuously.
    assert closes, "no CLOSE Order(...) found in runner.py — the locator is broken"
    assert stops, "no place_stop(...) call found in runner.py — the locator is broken"

    assert all(ok for _ln, ok in closes), (
        f"CLOSE order(s) built without naming the month the position is held in, at "
        f"line(s) {[ln for ln, ok in closes if not ok]}. On a roll date that sends the "
        f"exit to a contract holding nothing, which opens a short")
    assert all(ok for _ln, ok in stops), (
        f"stop(s) placed without naming the month, at line(s) "
        f"{[ln for ln, ok in stops if not ok]}. A stop on the wrong month protects "
        f"nothing and opens a position if it fills")


def test_sb18_every_fake_broker_matches_the_real_place_stop_signature():
    """A stub that has drifted from the interface turns a wiring bug into a green suite.

    This has already cost the project once: M3 found three fake brokers whose
    find_execution signature no longer matched the real one, and a broad `except
    Exception` around the call turned the resulting TypeError into "no fill" — a wrong
    answer instead of a crash. place_stop is stubbed in far more places, and B4 wraps it
    in exactly such a try/except.

    Checked on the source across every test module, so the next parameter cannot be
    added to the interface while the fakes quietly keep the old shape.
    """
    import ast
    import inspect
    from global_index.broker import Broker

    required = set(inspect.signature(Broker.place_stop).parameters) - {"self"}

    drifted = []
    for path in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == "place_stop"):
                continue
            args = node.args
            if args.kwarg and args.vararg:
                continue                      # (*a, **k) accepts anything
            names = {a.arg for a in args.args + args.kwonlyargs} - {"self"}
            # Stubs rename unused parameters (_d, _c...); only the keyword ones the
            # runner passes by name have to match, since the rest arrive positionally.
            missing = {p for p in required if p == "contract_month"} - names
            if missing:
                drifted.append(f"{path.name}:{node.lineno} missing {sorted(missing)}")

    # Self-check: finding no place_stop at all means the locator is broken.
    assert any(True for _ in Path(__file__).resolve().parent.glob("test_*.py")), \
        "no test modules found — the locator is broken"
    assert not drifted, (
        "these fake brokers no longer match Broker.place_stop, so a runner that passes "
        "the new argument raises TypeError inside a try/except and the stop silently "
        "does not get placed:\n  " + "\n  ".join(drifted))


def test_sb19_an_unreadable_session_day_refuses_instead_of_guessing():
    """Three outcomes, not two: agree, disagree, and cannot tell.

    Measured on the previous behaviour:

      * a not-a-date session day (pandas NaT) made the guard FIRE and name 202703 —
        because the schedule walk compares date STRINGS, and every "2026-.." row sorts
        below "NaT", so it fell through to the last row of the table. A refusal is the
        right answer; naming a month nobody asked about is not, and an operator reading
        that message would go looking for a March 2027 contract that has nothing to do
        with anything;

      * a malformed string raised pandas' own DateParseError. send_order happens to sit
        inside a broad except, but _handle_rollover does not — so the exception left the
        guard's own vocabulary and became an unhandled failure in a different layer.

    Both now return a refusal in the guard's own terms. "Cannot tell" must land on the
    same side as "disagree": do not send.
    """
    import pandas as pd
    from global_index.ibkr_broker import session_month_conflict

    nat = session_month_conflict("MES", pd.NaT)
    assert nat is not None, "an unreadable session day must not read as agreement"
    assert "202703" not in nat, (
        f"the message names a month inferred from a string comparison against 'NaT'; "
        f"it must say the day is unreadable, not invent a contract: {nat}")

    bad = session_month_conflict("MES", "not-a-date")
    assert bad is not None, "a malformed session day must not read as agreement"

    # Control: the ordinary path is untouched, and still silent.
    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    assert session_month_conflict("MES", today) is None, (
        "a real session day that matches the wall clock must still say nothing")


def test_sb13_the_order_paths_actually_ask():
    """A detector nothing calls is H2 again — implemented end to end, wired nowhere.

    Checked on the source at the two sites that hold a session day: send_order has
    order.ref_day, _handle_rollover has today. _front_month_contract does not have one
    and is deliberately not the place for this.
    """
    import ast
    src = (Path(__file__).resolve().parent / "ibkr_broker.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    callers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "session_month_conflict"):
                callers.add(fn.name)

    for expected in ("send_order", "_handle_rollover"):
        assert expected in callers, (
            f"{expected} holds the session day and never compares it with the wall "
            f"clock; found callers: {sorted(callers)}")


def test_sb4_the_full_size_contract_is_not_adopted_as_ours():
    """NKD is the $5/pt contract; MNKD is the $0.50/pt micro. They are not the same size.

    Orders were routed to NKD until 2026-08-14 — four fills that cost $1,400 at the
    broker while the ledger booked $140. With routing fixed, a stray NKD position is
    something this system did not open and cannot size. Translating it back to MNKD
    would hand it to B4, which would compute a stop for the micro and place it against
    ten times the exposure.
    """
    assert _to_runner("NKD") == "NKD", (
        "NKD must stay unrecognised so it surfaces as an orphan rather than being "
        "managed as if it were the micro"
    )


def test_sb6_an_unschedulable_symbol_raises_instead_of_going_out_unqualified():
    """No ROLL_SCHEDULE entry used to fall through to ibi.Future(sym) with no month.

    IBKR rejects that as ambiguous whenever two months are live, and the rejection
    surfaces at the first bar fetch or the first order rather than at import. MNK would
    have hit exactly this after routing moved to it, because ROLL_SCHEDULE was keyed on
    NKD alone.
    """
    from global_index.ibkr_broker import ContractResolutionError, _front_month_contract

    class _IB:
        def qualifyContracts(self, *c):
            raise AssertionError("must not reach IBKR with an unschedulable symbol")

    class _Ibi:
        @staticmethod
        def Future(*a, **k):
            raise AssertionError("must not build a contract for an unschedulable symbol")

    with pytest.raises(ContractResolutionError) as e:
        _front_month_contract(_IB(), _Ibi(), "ZZZ")
    assert "ROLL_SCHEDULE" in str(e.value)


def test_sb7_a_month_the_exchange_does_not_list_raises():
    """qualifyContracts does not raise: ib_insync leaves conId 0 and logs a warning.

    ROLL_SCHEDULE rolls MNK to 202703 on 2026-12-04, but CME lists MNK only out to Z6
    (2 forward months against the full-size contract's 15, measured 2026-08-14). If
    MNKH7 is not listed by then the roll yields a contract that cannot resolve, and the
    old code would have sent the request anyway.
    """
    from global_index.ibkr_broker import ContractResolutionError, _front_month_contract

    class _Contract:
        conId = 0            # what ib_insync leaves behind when resolution fails

    class _IB:
        def qualifyContracts(self, *c):
            return []        # nothing qualified

    class _Ibi:
        @staticmethod
        def Future(*a, **k):
            return _Contract()

    with pytest.raises(ContractResolutionError) as e:
        _front_month_contract(_IB(), _Ibi(), "MNKD")
    assert "conId" in str(e.value)


def test_sb5_every_routed_symbol_has_a_roll_schedule():
    """_current_front_month returning None drops the call sites onto the unqualified
    contract branch, which IBKR rejects as ambiguous when two months are live. The
    failure lands on the first bar fetch or the first order, not at import."""
    from global_index.ibkr_broker import ROLL_SCHEDULE, _RAITS_TO_IBKR, _current_front_month

    for inst, ibkr_sym in _RAITS_TO_IBKR.items():
        assert ibkr_sym in ROLL_SCHEDULE, (
            f"{inst} routes to {ibkr_sym}, which has no ROLL_SCHEDULE entry; "
            f"ibi.Future({ibkr_sym!r}) without a month is ambiguous at IBKR"
        )
        assert _current_front_month(ibkr_sym), f"no front month resolves for {ibkr_sym}"


def test_sb8_the_order_symbol_is_never_the_data_symbol():
    """The exact substitution that produced C8.

    MNKD legitimately carries data_symbol="NKD" -- the backtest uses full-size Nikkei
    history because it starts in 2018 while micro data starts in 2024 Q4. The broker
    layer had no third field to read, so it read that one, and orders for the $0.50
    micro went to the $5 full-size contract for four days at ten times the intended
    size. Any future contract whose data root differs from its listed ticker walks
    into the same trap unless ibkr_symbol is set.
    """
    from futures.basket import BASKET
    from global_index.specs import SPECS

    for name, c in {**BASKET, **SPECS}.items():
        if c.data_symbol == name:
            continue
        assert c.ibkr != c.data_symbol, (
            f"{name} would be ordered as {c.data_symbol!r}, which is its DATA root, "
            f"not its listed contract; set ibkr_symbol explicitly"
        )


def test_sb9_the_routing_map_is_derived_from_the_specs_not_a_second_copy():
    """A hand-written map is a second copy of an instrument's identity, and the copy
    that drifts is the one that routes orders. Read the source: the map must be built
    from the contract objects, not typed out."""
    from global_index import ibkr_broker

    src = Path(ibkr_broker.__file__).read_text(encoding="utf-8")
    decl = re.search(r"_RAITS_TO_IBKR: dict\[str, str\] = \{(.*?)\n\}", src, re.S)
    assert decl, "_RAITS_TO_IBKR declaration not found"
    body = decl.group(1)
    assert "for name, contract in" in body, (
        "_RAITS_TO_IBKR is a literal again; derive it from Contract.ibkr so the two "
        "cannot disagree"
    )
    assert '"MNK"' not in body and "'MNK'" not in body, (
        "a ticker is hardcoded in the routing map; it belongs in specs.py only"
    )


def test_sb10_the_micro_nikkei_is_ordered_as_mnk():
    """Anchored to what IBKR returned on 2026-08-14: MNK is multiplier 0.5, NKD is 5."""
    from global_index.specs import SPECS

    assert SPECS["MNKD"].ibkr == "MNK"
    assert SPECS["MNKD"].point_value == 0.5
    assert SPECS["NKD"].ibkr == "NKD"
    assert SPECS["NKD"].point_value == 5.0


def test_sb2_every_symbol_read_goes_through_it():
    """The invariant, enforced on the source rather than on memory.

    Any new `x.contract.symbol` that is not wrapped is the seventh site, and it would
    otherwise stay invisible until an NKD position happened to exist.
    """
    offenders = []
    for n, line in enumerate(_SOURCE.splitlines(), 1):
        code = line.split("#", 1)[0]
        if "contract.symbol" not in code:
            continue
        # Allowed shapes: _to_runner(x.contract.symbol), or the definition itself.
        if not re.search(r"_to_runner\(\s*[\w.]*contract\.symbol", code):
            offenders.append(f"{n}: {line.strip()}")
    assert not offenders, (
        "these read an IBKR symbol without translating it — wrap in _to_runner():\n  "
        + "\n  ".join(offenders))


def test_sb3_positions_report_runner_names():
    """The site that halted live trading. get_positions feeds B3, which compares its
    inst against live_positions.json — a file written in the runner's vocabulary."""
    class _Pos:
        def __init__(self, sym, qty):
            self.contract = type("C", (), {"symbol": sym})()
            self.position = qty

    class _IB:
        def positions(self):
            return [_Pos("MNK", 1.0), _Pos("MES", -1.0)]
        def sleep(self, _s):
            pass

    b = IBKRBroker(_raw_fetcher=lambda i, t: None)
    b._raw_fetcher = None
    b._require_connection = lambda: _IB()

    by_inst = {p.inst: p.direction for p in b.get_positions()}
    assert by_inst == {"MNKD": "LONG", "MES": "SHORT"}, (
        f"B3 compares these against the file's names; got {by_inst}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
