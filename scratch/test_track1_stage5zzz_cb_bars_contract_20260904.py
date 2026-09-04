"""Stage 5ZZZ-CB. Bars were read from the contract an ORDER goes to.

The second half of Stage 5Q-7, and it has the same fingerprint.

5Q-7 found that `fetch_bars("MNKD")` resolved through the ORDER map and fetched the $0.50
micro MNK while the parquet holds full-size NKD: "1,155 of 1,186 shared minutes disagreed". It
fixed WHICH INSTRUMENT by routing the live fetch through `history_ibkr_symbol`. It did not fix
WHICH MONTH, and on 2026-09-04 that half arrived:

    our roll calendar moved NKD to 202612 on the roll date (5 bdays before the 09-11 LTD)
    IBKR's continuous series, which the parquet is built from, was still on 202609
    -> 1,069 of 1,080 shared minutes disagreed, 12 NKD slots refused

The rule was already written at the top of the roll section in `ibkr_broker`: "Backtest uses
continuous (roll-adjusted) parquet. Live needs the specific front-month contract." Two
different things for two different jobs. The bar fetch had taken the order half.

MEASURED AGAINST THE LIVE BROKER, 2026-09-04 00:4x ET:

    before   1,069 of 1,080 shared minutes disagreed   (12 slots refused that night)
    after    0 of 1,185 disagreed
    control  MES, not in its roll window, 0 of 1,185 either way -- the change is inert
             outside the few days a quarter when the two calendars differ

Everything here runs against fakes. The broker measurements above are in the commit message;
what is pinned in this file is the resolution rule, which is what a future edit can undo.
"""
from __future__ import annotations

import inspect

import pytest

from global_index import ibkr_broker as B


class _Contract:
    """Enough of an ib_insync contract for the resolution path, and no more."""

    def __init__(self, symbol="", lastTradeDateOrContractMonth="", exchange="", **kw):
        self.symbol = symbol
        self.lastTradeDateOrContractMonth = lastTradeDateOrContractMonth
        self.exchange = exchange
        self.localSymbol = ""
        self.conId = 0
        self.secType = kw.get("secType", "")


class _Ibi:
    """A stand-in for the ib_insync module: ContFuture and Future build tagged contracts."""

    @staticmethod
    def ContFuture(symbol, exchange=""):
        c = _Contract(symbol=symbol, exchange=exchange, secType="CONTFUT")
        return c

    @staticmethod
    def Future(symbol, lastTradeDateOrContractMonth="", exchange=""):
        return _Contract(symbol=symbol,
                         lastTradeDateOrContractMonth=lastTradeDateOrContractMonth,
                         exchange=exchange, secType="FUT")


class _Ib:
    """`qualifyContracts` is where IBKR answers. The continuous month it reports is the whole
    point of the fix, so it is a parameter of the fake rather than a constant."""

    def __init__(self, continuous_month="20260910", qualify=True):
        self.continuous_month = continuous_month
        self.qualify = qualify
        self.asked: list = []

    def qualifyContracts(self, contract):
        self.asked.append((contract.secType, contract.symbol,
                           contract.lastTradeDateOrContractMonth, contract.exchange))
        if not self.qualify:
            return [contract]
        contract.conId = 111
        if contract.secType == "CONTFUT":
            # IBKR fills the ContFuture in with the expiry it currently tracks.
            contract.lastTradeDateOrContractMonth = self.continuous_month
            contract.localSymbol = contract.symbol + "U6"
        else:
            contract.localSymbol = contract.symbol + "?"
        return [contract]


# -- the instrument: the history's symbol, not the order map's ----------------------------
def test_bars_ask_for_the_symbol_the_history_was_built_from():
    """5Q-7's half, kept. `MNKD` orders route to the micro MNK; the parquet holds full-size
    NKD, and a bar fetch that asks for MNK compares two different instruments."""
    ib = _Ib()
    B._bars_contract(ib, _Ibi(), "MNKD")
    symbols = {sym for _t, sym, _m, _e in ib.asked}
    assert symbols == {"NKD"}, ib.asked
    assert "MNK" not in symbols


def test_orders_still_route_to_the_micro():
    """The other half of the same sentence must not move: an order for MNKD is an order for
    MNK. If this ever equals the bars symbol, one of the two is wrong."""
    sym, _exch = B.ibkr_symbol_and_exchange("MNKD")
    assert sym == "MNK", sym


# -- the month: the continuous series', not our roll calendar's ---------------------------
def test_bars_use_the_month_the_continuous_series_is_on():
    """The defect. On the roll date our calendar says December and IBKR's continuous series is
    still on September; the parquet is the continuous one."""
    ib = _Ib(continuous_month="20260910")            # September
    c = B._bars_contract(ib, _Ibi(), "MNKD")
    assert c.lastTradeDateOrContractMonth == "202609", c.lastTradeDateOrContractMonth
    fut = [a for a in ib.asked if a[0] == "FUT"]
    assert fut and fut[0][2] == "202609", ib.asked


def test_bars_do_not_follow_our_roll_calendar():
    """Stated as a difference, because on 363 days a year the two agree and a test that only
    checks the value would pass while reading the wrong source."""
    ib = _Ib(continuous_month="20260910")
    c = B._bars_contract(ib, _Ibi(), "MNKD")
    ours = B._current_front_month("NKD")
    assert ours == "202612", ("the calendar moved on; this test's premise needs rechecking",
                              ours)
    assert c.lastTradeDateOrContractMonth != ours, c.lastTradeDateOrContractMonth


def test_the_continuous_month_is_asked_for_not_computed():
    """Whatever IBKR reports is what is used. A month inferred here would be a second roll
    calendar, and a second calendar is the thing that caused this."""
    # A month NEITHER calendar would produce. The first version used 202612, which is exactly
    # what our own roll calendar answers today -- so a mutation that read the wrong source
    # still passed. A test whose expected value collides with the wrong answer proves nothing.
    ib = _Ib(continuous_month="20270312")
    c = B._bars_contract(ib, _Ibi(), "MNKD")
    assert c.lastTradeDateOrContractMonth == "202703", c.lastTradeDateOrContractMonth
    assert c.lastTradeDateOrContractMonth != B._current_front_month("NKD")


# -- failure is refused, never guessed ----------------------------------------------------
def test_an_unqualified_continuous_contract_raises_rather_than_guessing():
    """ib_insync does not raise on an unresolvable contract -- it leaves conId 0 and logs. A
    bar request would then go out against something IBKR never confirmed, which is the exact
    failure `_front_month_contract` was written to stop."""
    ib = _Ib(qualify=False)
    with pytest.raises(B.ContractResolutionError):
        B._bars_contract(ib, _Ibi(), "MNKD")


def test_a_continuous_contract_with_no_month_raises():
    """A qualified contract carrying no expiry is not a month to fetch against."""
    ib = _Ib(continuous_month="")
    with pytest.raises(B.ContractResolutionError):
        B._bars_contract(ib, _Ibi(), "MNKD")


# -- the call sites -----------------------------------------------------------------------
def test_the_bar_fetch_uses_the_bars_contract():
    """The whole fix is one line in `_fetch_raw`, and a fix nothing calls is the shape this
    repo keeps finding: correct code, written docs, wired to nothing."""
    import re

    src = inspect.getsource(B.IBKRBroker._fetch_raw)
    # Comments are stripped first: the line above the call NAMES the old resolver to say what
    # it used to be, and a bare substring test read that as still calling it.
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "_bars_contract(ib, ibi, inst)" in code, code
    assert not re.search(r"_front_month_contract\s*\(", code), code


def test_orders_and_stops_still_use_the_front_month():
    """Bars moved; orders must not. An order has to name a contract that trades, and five
    business days before expiry that is the next month."""
    for fn in (B.IBKRBroker.send_order, B.IBKRBroker.place_stop):
        src = inspect.getsource(fn)
        assert "_bars_contract" not in src, (fn.__name__, "orders must not read the bars "
                                                          "contract")


def test_the_rule_this_rests_on_is_still_written_in_the_module():
    """If that sentence goes, the reason for two resolution paths goes with it and someone
    will reasonably merge them again."""
    import re

    src = re.sub(r"\s+#?\s*", " ", inspect.getsource(B))
    assert "Backtest uses continuous (roll-adjusted) parquet" in src
    assert "Live needs the specific front-month contract" in src
