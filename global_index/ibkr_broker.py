"""
global_index/ibkr_broker.py — IBKRBroker for the futures runner
=================================================================
Implements global_index/broker.py::Broker for Interactive Brokers futures.

Three mandatory specs (E-injection suite from DIVERGENCE_SWEEP.md):
  C3: fetch_bars MUST sort bars by timestamp.
      IBKR historical-data API can return bars out-of-order on reconnect/backfill.
      Unsorted bars break chandelier ratchet (np.maximum.accumulate on wrong order
      → wrong stop levels). Always sort_index() before returning.
  C5: reconnect MUST reconcile broker positions vs runner state.
      If runner.state.open_positions has a duplicate (inst, cluster) entry — which
      can happen when a reconnect fires a second OPEN for the same instrument before
      the runner deduplicates — reconcile_positions() removes the duplicate and
      prevents double CLOSE + doubled pnl. Call after every reconnect, before
      the next run_day().
  C6: fetch_bars MUST normalize column names to lowercase.
      IBKR reqHistoricalData returns uppercase OPEN/HIGH/LOW/CLOSE/VOLUME. The
      backtest engine expects lowercase. Lowercase on every fetch, unconditionally.

ib_insync is NOT imported at module level — lazy import inside methods so this
module can be imported offline (tests, CI) without ib_insync installed.

Usage
-----
    from global_index.ibkr_broker import IBKRBroker
    broker = IBKRBroker(host="127.0.0.1", port=7497, client_id=1)
    broker.connect()
    try:
        runner.run_history(days)
    finally:
        broker.disconnect()

After any reconnect:
    broker.reconnect()
    n = broker.reconcile_positions(runner.state)
    # n == 0 expected; n > 0 means duplicates were removed (log this)
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import pandas as pd

from futures.basket import BASKET
from global_index.broker import Broker, Order, Fill, BrokerPosition
from global_index.specs import SPECS

log = logging.getLogger(__name__)

# IBKR error codes that are purely informational — no action required.
# These appear as "Error NNNN" in ib_insync output but are NOT failures.
#   10349 — Order TIF overridden by account preset (e.g. DAY). Order still
#            processes normally. ib_insync also logs a misleading "Canceled order"
#            line when it receives this code; the trade's FINAL status is FILLED.
#   2109  — outsideRth flag "ignored based on order type/destination" — IBKR
#            confirming the order is being processed; not an error.
#   2174  — endDateTime without explicit timezone (deprecated format warning).
#            The current "%Y%m%d %H:%M:%S" format works and returns correct bars.
#            Fix properly when IBKR removes implied-tz support (next API release).
#   10147 — OrderId not found — can fire on cancel-after-fill race; harmless.
#   202   — Order cancelled by API request — logged at WARNING (not debug) so
#            broker-initiated cancellations surface alongside our own timeout cancels.
_IBKR_INFORMATIONAL: frozenset[int] = frozenset({10349, 2109, 2174, 10147})

# raits internal instrument name → IBKR Future symbol (where they differ).
#
# "MNKD" is the Micro Dollar-Denominated Nikkei 225: point_value $0.50, tick 5 index
# points, tick value $2.50 (global_index/specs.py). IBKR lists it as "MNK".
#
# This said "NKD" until 2026-08-14, which is the FULL-SIZE contract at $5/pt — ten times
# the size. specs.py carried the warning all along ("confirm ticker w/ IBKR"); the
# confirmation was never done and the full-size ticker stood in as a placeholder.
#
# What that cost, measured from the IBKR Flex statement rather than inferred: four NKD
# executions on 2026-08-10/11 realised −$1,400.00 at the broker while the sleeve ledger
# booked −$140.00, because _book_realised prices fills with specs.py's $0.50. Exactly
# 10.0000×. Entry and exit prices matched the statement to the cent — only the multiplier
# was wrong, so the signals were right and the position size was not.
#
# Confirmed against IBKR before changing (reqContractDetails, read-only):
#   NKD → NKDU6, conId 652545722, multiplier 5,   minTick 5.0  ← what was traded
#   MNK → MNKU6, conId 863279730, multiplier 0.5, minTick 5.0  ← what specs.py describes
# MNK carried 2,473 one-minute bars over two days against NKD's 2,472, and 2,746 lots of
# volume against 4,819 — thinner but continuously quoted, which at one contract is not a
# constraint. Ticks are 5.0 on both, so slippage evidence gathered on NKD stays
# comparable.
#
# Deliberately NOT changed: the historical data path. update_futures_data.py,
# update_ibkr_daily.py and repair_parquet_utc.py fetch NKD bars for MNKD on purpose —
# micro and full track one index, and the full-size series is the longer one. Only order
# routing was ever wrong.
# Derived, not declared. This was a hand-written literal until 2026-08-15; the whole
# defect above is what a second copy of an instrument's identity costs when it drifts
# from the first. Contract.ibkr is now the single place any layer asks "what do I put
# on the order", and this map cannot disagree with it because it is built from it.
_RAITS_TO_IBKR: dict[str, str] = {
    name: contract.ibkr
    for name, contract in {**BASKET, **SPECS}.items()
    if contract.ibkr != name
}

# IBKR exchange override per symbol. MYM (Micro Dow) trades on CBOT, not CME, in IBKR.
# All other basket instruments (MES/MNQ/M2K/NKD) trade on CME.
_IBKR_EXCHANGE: dict[str, str] = {
    "MYM": "CBOT",
}

# IBKR symbol → runner name. Order lookups read contract.symbol but every caller asks
# by the runner's name, so NKD must come back as MNKD or an NKD position reads as
# unprotected on every slot and B4 stacks a duplicate stop on it.
_IBKR_TO_RAITS: dict[str, str] = {v: k for k, v in _RAITS_TO_IBKR.items()}


# LONG is protected by a SELL stop, SHORT by a BUY stop. A stop on the wrong side does
# not close the position — it doubles it. Live 2026-08-05 carried exactly that: a SELL
# MYM stop against a SHORT MYM position, left over from an earlier LONG.
#
# Declared here, imported by check_open_orders/repair_stops. It used to live only in the
# CLI tool, so the broker's own checks had no notion of side at all and counted any stop
# on the contract as protection. Two copies of this mapping would be two chances to
# disagree about what "protected" means — the exact failure these tools exist to catch.
PROTECTIVE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}


def _to_runner(symbol: str) -> str:
    """Translate an IBKR contract symbol into the runner's vocabulary.

    IBKR calls the micro Nikkei contract MNK; the runner calls it MNKD. Every other
    instrument agrees, so a site that forgets to translate is invisible until a Nikkei
    position exists — which is how six sites were found one at a time, the last of them
    on 2026-08-10 when get_positions reported the live position under a name
    live_positions.json did not use. B3 counted that one position twice, as missing and
    as an orphan, and halted every entry.

    "NKD" deliberately no longer maps back to MNKD (it did until 2026-08-14, while orders
    were being routed to the full-size contract by mistake). The reverse map is derived
    from _RAITS_TO_IBKR, so it now translates MNK only. A leftover NKD position must
    surface under its own name and be treated as an orphan: it is ten times the size of
    anything this system sizes, and quietly re-adopting it as MNKD would put a stop on it
    computed for the micro. An orphan that halts entries is the correct alarm here.

    The rule is not "remember the mapping at each call". It is that nothing leaves this
    class speaking IBKR's vocabulary, and test_symbol_boundary reads this file to check
    it, so a seventh site cannot be added quietly.

    Unknown symbols pass through: dropping or guessing one would be worse than showing
    a name nobody recognises.
    """
    return _IBKR_TO_RAITS.get(symbol, symbol)

# ── Order fill timeouts ────────────────────────────────────────────────────────
# Design constraint [1]: ENTRY timeout 30s → cancel → Fill(status='CANCELLED').
# EXIT uses MARKET order; no protocol timeout per design [2] but we add a safety
# limit to prevent process hang if exchange is in maintenance window.
# Measure actual fill times in first paper weeks and update if needed (A4).
ENTRY_FILL_TIMEOUT_SECS: int = 30
EXIT_FILL_TIMEOUT_SECS: int = 120

# How long to re-poll a Trade that reports Cancelled with nothing filled, before
# accepting that verdict. See _verified_status() for why a bare Cancelled is not
# trustworthy. Short: this only runs on an already-terminal order.
CANCEL_VERIFY_SECS: float = 5.0

# ── C2: Rollover schedule ─────────────────────────────────────────────────────
#
# Backtest uses continuous (roll-adjusted) parquet.  Live needs the specific
# front-month contract for each instrument.
#
# Roll rule: roll ROLL_BDAYS_BEFORE_EXPIRY business days before last trading day (LTD).
#   CME micro equity (MES/MNQ/MYM/M2K): LTD = 3rd Friday of March/June/Sep/Dec.
#   NKD (Nikkei/Dollar CME): LTD = 2nd Friday of March/June/Sep/Dec.
#
# 2026 pre-computed roll dates (LTD - 5 bdays):
#
# | Inst          | LTD        | Roll (5 bday before) |
# |---------------|------------|----------------------|
# | MES/MNQ/MYM/M2K | 2026-03-20 | 2026-03-13         |
# |               | 2026-06-19 | 2026-06-12           |
# |               | 2026-09-18 | 2026-09-11           |
# |               | 2026-12-18 | 2026-12-11           |
# | NKD           | 2026-03-13 | 2026-03-06           |
# |               | 2026-06-12 | 2026-06-05           |
# |               | 2026-09-11 | 2026-09-04           |
# |               | 2026-12-11 | 2026-12-04           |
#
# Next-month contract code: "YYYYMM" e.g. "202606" for June 2026.
# IB Future contract: ibi.Future(symbol, lastTradeDateOrContractMonth="202606", exchange="CME")
#
# ROLL_SCHEDULE maps inst → list of (roll_date, front_month, next_month) tuples.
# A row means: on roll_date, close front_month and open next_month.

ROLL_BDAYS_BEFORE_EXPIRY = 5

ROLL_SCHEDULE: dict[str, list[tuple[str, str, str]]] = {
    # (roll_date, close_this_contract_month, open_this_contract_month)
    "MES": [
        ("2026-03-13", "202603", "202606"),
        ("2026-06-12", "202606", "202609"),
        ("2026-09-11", "202609", "202612"),
        ("2026-12-11", "202612", "202703"),
    ],
    "MNQ": [
        ("2026-03-13", "202603", "202606"),
        ("2026-06-12", "202606", "202609"),
        ("2026-09-11", "202609", "202612"),
        ("2026-12-11", "202612", "202703"),
    ],
    "MYM": [
        ("2026-03-13", "202603", "202606"),
        ("2026-06-12", "202606", "202609"),
        ("2026-09-11", "202609", "202612"),
        ("2026-12-11", "202612", "202703"),
    ],
    "M2K": [
        ("2026-03-13", "202603", "202606"),
        ("2026-06-12", "202606", "202609"),
        ("2026-09-11", "202609", "202612"),
        ("2026-12-11", "202612", "202703"),
    ],
    "NKD": [
        ("2026-03-06", "202603", "202606"),
        ("2026-06-05", "202606", "202609"),
        ("2026-09-04", "202609", "202612"),
        ("2026-12-04", "202612", "202703"),
    ],
    # MNK is the micro on the same CME Nikkei series as NKD, so it shares the expiry
    # cycle and therefore the roll dates. Keyed by IBKR symbol because that is what
    # _current_front_month is called with — every call site resolves the symbol through
    # _RAITS_TO_IBKR first.
    #
    # This entry is not optional. Without it _current_front_month("MNK") returns None,
    # the call sites fall through to the unqualified `ibi.Future("MNK", exchange=...)`
    # branch, and IBKR rejects it as ambiguous: MNKU6 and MNKZ6 are both live. That is
    # the failure the comment above _current_front_month describes, and it would fire on
    # the first bar fetch or the first order — not at import, where it would be obvious.
    "MNK": [
        ("2026-03-06", "202603", "202606"),
        ("2026-06-05", "202606", "202609"),
        ("2026-09-04", "202609", "202612"),
        ("2026-12-04", "202612", "202703"),
    ],
}


def get_roll_event(inst: str, today) -> "tuple[str, str] | None":
    """
    Return (front_month, next_month) if today is a roll date for inst, else None.
    today: str "YYYY-MM-DD" or pd.Timestamp.

    C1: resolve the symbol first, like every other ROLL_SCHEDULE lookup.

    ROLL_SCHEDULE is keyed by IBKR symbol, and its own comment says "every call site
    resolves the symbol through _RAITS_TO_IBKR first". This function was the one that
    did not. Its caller is _handle_rollover, which is handed `pos.inst` — the RUNNER
    name — straight from runner.py:1229, and run_live_day.py:88 sets NKD_INST = "MNKD".
    So the lookup asked for a key that has never existed and got None: "not a roll day",
    every day, for the only instrument whose key needed translating.

    The bug was invisible because it was ASYMMETRIC and silent. Four of five instruments
    are their own IBKR symbol, so they rolled correctly; only Nikkei did not, and a
    missing roll produces no error — just a position that quietly stays in an expiring
    contract while send_order/place_stop/_fetch_raw (which DO resolve) move to the next
    month. From the roll date the orders and the position sit in different contracts, and
    the next CLOSE is a market SELL on a contract holding nothing: it opens a short.

    Fixed here rather than by adding a "MNKD" row to ROLL_SCHEDULE. A third copy of the
    same expiry cycle beside MNK and NKD is three chances to drift instead of two — the
    L1 defect — and it would leave the next runner-named instrument broken the same way.
    Resolving is idempotent: keys already in IBKR form map to themselves, so MES, MNK and
    NKD lookups are bit-identical to before.
    """
    ibkr_sym = _RAITS_TO_IBKR.get(inst, inst)
    today_str = str(pd.Timestamp(today).date())
    for roll_date, front, nxt in ROLL_SCHEDULE.get(ibkr_sym, []):
        if roll_date == today_str:
            return front, nxt
    return None


def _current_front_month(inst: str, today=None) -> "str | None":
    """
    Return the active front-month contract string (e.g. '202609') for inst on today.
    Walks ROLL_SCHEDULE: before first roll → use first front_month; after each roll → switch to nxt.
    Returns None if inst not in ROLL_SCHEDULE (caller falls back to unqualified contract).

    Resolves the symbol first, exactly as get_roll_event does — same table, so the same
    rule. Callers were expected to translate before calling, and that expectation has
    already been broken once for real: repair_parquet_utc records "Passing the raits
    name returned None, the contract went out with no month, and IBKR rejected it as
    ambiguous across fifteen listed expiries." A lookup that is only correct when every
    caller remembers something is a lookup waiting for the caller that does not.
    Idempotent: symbols already in IBKR form map to themselves.
    """
    today_str = str(pd.Timestamp(today or pd.Timestamp.now(tz="America/New_York")).date())
    schedule = ROLL_SCHEDULE.get(_RAITS_TO_IBKR.get(inst, inst), [])
    if not schedule:
        return None
    current = schedule[0][1]  # front_month of first row = pre-roll default
    for roll_date, _front, nxt in schedule:
        if roll_date <= today_str:
            current = nxt
    return current


def ibkr_symbol_and_exchange(inst: str) -> "tuple[str, str]":
    """(IBKR symbol, exchange) for a runner instrument — the whole routing rule, once.

    Both halves must be answered from the SAME name. _IBKR_EXCHANGE is keyed by IBKR
    symbol, so asking it with the runner's name silently returns the default: correct
    today only because the one instrument that needs translating (MNKD -> MNK) happens
    to trade on CME. monitor/backend/ibkr_reader did exactly that — resolved the symbol
    on one line and asked for the exchange with the untranslated name on the next.

    Two copies of a routing rule is how MNKD reached the full-size contract to begin
    with, so there is one copy and everything asks it.
    """
    sym = _RAITS_TO_IBKR.get(inst, inst)
    return sym, _IBKR_EXCHANGE.get(sym, "CME")


class ContractResolutionError(RuntimeError):
    """Raised when an instrument cannot be resolved to exactly one listed contract."""


def _front_month_contract(ib, ibi, inst: str):
    """Build the qualified front-month contract for a runner instrument, or raise.

    Three call sites duplicated this and all three ended in `qualifyContracts`, which
    does not raise: ib_insync leaves an unresolvable contract with conId 0 and logs a
    warning. The request then goes out against a contract IBKR never confirmed, and the
    failure surfaces as something else entirely — a missing bar set, or an order that
    does not appear.

    Two ways the resolution can be wrong, both of which used to pass silently:

    1. No ROLL_SCHEDULE entry. `_current_front_month` returns None, the old code fell
       through to an unqualified `ibi.Future(sym)`, and IBKR rejects it as ambiguous
       whenever two months are live. This is the failure MNK would have hit on the first
       order after routing moved to it, because ROLL_SCHEDULE was keyed on NKD only.

    2. A month the exchange does not list. ROLL_SCHEDULE rolls MNK to 202703 on
       2026-12-04, but CME currently lists MNK only out to Z6 — the micro carries far
       fewer forward months than the full-size contract (2 against 15, measured
       2026-08-14). If MNKH7 is not listed by then, the roll produces a contract that
       cannot resolve.

    Both now raise with the instrument named, because this whole incident began with a
    contract identity the system inferred and then assumed existed.
    """
    ibkr_sym = _RAITS_TO_IBKR.get(inst, inst)
    front_month = _current_front_month(ibkr_sym)
    if not front_month:
        raise ContractResolutionError(
            f"{inst} routes to IBKR symbol {ibkr_sym!r} but has no ROLL_SCHEDULE entry. "
            f"An unqualified future is ambiguous whenever two months are live; add "
            f"ROLL_SCHEDULE[{ibkr_sym!r}] rather than letting the request go out."
        )
    return _month_contract(ib, ibi, inst, front_month)


def _month_contract(ib, ibi, inst: str, month: str):
    """Build the qualified contract for a runner instrument in a SPECIFIC month, or raise.

    H1. Split out of _front_month_contract so the roll path can share it.

    Appendix F gathered three call sites — _fetch_raw, send_order, place_stop — and
    reported the duplication closed. There were four. _handle_rollover builds two
    contracts of its own, and being outside the shared helper it kept every defect the
    helper exists to remove:

      * the runner's name went out as the IBKR symbol, so a Nikkei roll would have asked
        for "MNKD", which is not listed;
      * exchange was hardcoded "CME" while _IBKR_EXCHANGE declares MYM on CBOT, and the
        FIRST of the roll's two orders is the one that closes the position;
      * qualifyContracts was called and its result ignored, so an unlisted month became
        two market orders against a contract IBKR never confirmed.

    It stayed invisible because the roll path could not run for the one instrument whose
    symbol needed translating: get_roll_event was keyed on the IBKR name and asked with
    the runner name, so it always answered "not a roll day" (C1). Two defects hid each
    other — fixing C1 alone would have turned "never rolls" into "rolls into a contract
    that cannot resolve".

    The month is a parameter rather than derived here: a roll needs the OUTGOING month
    too, and _current_front_month answers "what is front now", which on the roll date is
    already the next one.
    """
    ibkr_sym, exchange = ibkr_symbol_and_exchange(inst)
    contract = ibi.Future(ibkr_sym, lastTradeDateOrContractMonth=month,
                          exchange=exchange)
    ib.qualifyContracts(contract)
    if not getattr(contract, "conId", 0):
        raise ContractResolutionError(
            f"{inst} -> {ibkr_sym} {month} on {exchange} did not resolve to a listed "
            f"contract (conId is unset after qualifyContracts). Check that the exchange "
            f"lists this month: micros carry fewer forward months than the full-size "
            f"contract, so a ROLL_SCHEDULE date can outrun the listed chain."
        )
    return contract


class IBKRConnectionError(RuntimeError):
    """Raised when IBKRBroker is called without a live IB Gateway connection."""


class IBKRBroker(Broker):
    """
    Futures broker backed by ib_insync / IB Gateway.

    Satisfies three pre-live specs (C3/C5/C6) provable without a live connection
    via the _raw_fetcher injection point (see Parameters).

    Parameters
    ----------
    host, port, client_id : IB Gateway address (7497=paper, 7496=live)
    bar_duration          : lookback string passed to reqHistoricalData
                            (default "2 D" = 2 trading days of 1-min bars)
    _raw_fetcher          : TEST ONLY — callable(inst, through) → raw DataFrame.
                            When provided, fetch_bars uses this instead of the
                            real IBKR API. Allows C3/C5/C6 injection tests to
                            run without a live Gateway.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 10,
        bar_duration: str = "2 D",
        _raw_fetcher: Optional[Callable] = None,
    ) -> None:
        self._host         = host
        self._port         = port
        self._client_id    = client_id
        self._bar_duration = bar_duration
        self._ib           = None          # ib_insync.IB; None until connect()
        self._positions: list[BrokerPosition] = []
        self._equity: float = 0.0

        # Injection point for tests (C3/C5/C6) — not used in production
        self._raw_fetcher = _raw_fetcher

        # A3/A2 test hooks — set by test scripts only, never in production
        # _test_entry_lmt_price: if set, OPEN uses LimitOrder at this price (guaranteed miss → timeout)
        # _test_entry_timeout:   if set, overrides ENTRY_FILL_TIMEOUT_SECS for this session
        self._test_entry_lmt_price: "float | None" = None
        self._test_entry_timeout:   "int   | None" = None

    # ── Connection lifecycle ──────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to IB Gateway. Raise IBKRConnectionError on failure."""
        try:
            import ib_insync as ibi  # type: ignore
        except ImportError as exc:
            raise ImportError("ib_insync not installed. Run: pip install ib_insync") from exc

        # Silence ib_insync BEFORE connect — initial data (execDetails, positions,
        # commissionReports) arrives during connect() and would flood the log otherwise.
        # propagate=False prevents records from reaching root-logger handlers even
        # if ib_insync internals reset the level after connect.
        for _ln in ("ib_insync", "ib_insync.ib", "ib_insync.wrapper",
                    "ib_insync.client", "ib_insync.util"):
            _l = logging.getLogger(_ln)
            _l.setLevel(logging.ERROR)
            _l.propagate = False
            if not any(isinstance(h, logging.NullHandler) for h in _l.handlers):
                _l.addHandler(logging.NullHandler())

        ib = ibi.IB()
        ib.connect(self._host, self._port, clientId=self._client_id)
        self._ib = ib

        # Take full ownership of errorEvent: remove ALL built-in ib_insync
        # handlers (which log every code at WARNING), then add ours which
        # downgrades informational codes to DEBUG.
        try:
            ib.errorEvent.clear()  # eventkit.Event.clear() — removes all listeners
        except AttributeError:
            try:
                ib.errorEvent -= ib._onError  # type: ignore[attr-defined]
            except Exception:
                pass
        ib.errorEvent += self._on_ibkr_error

        log.info("IBKRBroker connected: %s:%s clientId=%s", self._host, self._port, self._client_id)

    def _on_ibkr_error(self, reqId: int, errorCode: int, errorString: str, _contract) -> None:
        """Custom IBKR error event handler.

        ib_insync fires errorEvent for every TWS message code. We downgrade known
        informational codes to DEBUG so operator logs stay clean; unknown codes
        are emitted at WARNING for investigation.
        """
        if errorCode in _IBKR_INFORMATIONAL:
            log.debug(
                "IBKR notify code=%d reqId=%d: %s (informational — no action needed)",
                errorCode, reqId, errorString,
            )
        else:
            log.warning("IBKR code=%d reqId=%d: %s", errorCode, reqId, errorString)

    def disconnect(self) -> None:
        """Disconnect gracefully. Safe to call when already disconnected."""
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:
                pass
            self._ib = None
            log.info("IBKRBroker disconnected")

    def reconnect(self) -> None:
        """Disconnect then reconnect. Call before reconcile_positions() after a drop."""
        self.disconnect()
        self.connect()

    def _require_connection(self):
        if self._ib is None or not self._ib.isConnected():
            raise IBKRConnectionError(
                f"IBKRBroker not connected — call connect() first "
                f"(host={self._host}, port={self._port})"
            )
        return self._ib

    # ── C5: reconcile_positions ───────────────────────────────────────────────

    def reconcile_positions(self, runner_state) -> int:
        """
        After reconnect: remove duplicate (inst, cluster) entries from
        runner_state.open_positions. Returns the number of duplicates removed.

        Duplicates arise when reconnect fires a second OPEN for a position that
        is already in runner.state — runner.state becomes the source of truth
        (it has entry_day, cluster, pnl_sized that IBKR's position list lacks).
        Dedup keeps the FIRST occurrence per (inst, cluster) key.

        Call pattern:
            broker.reconnect()
            n = broker.reconcile_positions(runner.state)
            if n:
                log.warning("reconcile removed %d duplicate position(s)", n)
        """
        seen: dict = {}
        deduped = []
        for pos in runner_state.open_positions:
            key = (pos.inst, pos.cluster)
            if key not in seen:
                seen[key] = True
                deduped.append(pos)
            else:
                log.warning(
                    "reconcile_positions: duplicate (%s, %s) removed from runner state",
                    pos.inst, pos.cluster,
                )
        removed = len(runner_state.open_positions) - len(deduped)
        runner_state.open_positions = deduped
        return removed

    # ── Broker interface ──────────────────────────────────────────────────────

    def fetch_bars(self, inst: str, through) -> pd.DataFrame:
        """
        Return 1-min OHLCV bars for `inst` up to and including `through`.

        C3: always sort_index() — IBKR can return bars out of chronological order
            on reconnect / backfill; unsorted bars corrupt chandelier ratchet.
        C6: always lowercase column names — IBKR returns OPEN/HIGH/LOW/CLOSE/VOLUME
            (uppercase); backtest engine expects lowercase.
        """
        raw = self._fetch_raw(inst, through)
        if raw.empty:
            return raw
        # C6: lowercase column names unconditionally
        raw.columns = [c.lower() for c in raw.columns]
        # C3: sort by timestamp unconditionally
        raw = raw.sort_index()
        # causal: only bars up to `through`
        return raw[raw.index <= pd.Timestamp(through)]

    def _fetch_raw(self, inst: str, through) -> pd.DataFrame:
        """Return raw (unsorted, potentially uppercase) bars. Production uses IBKR API."""
        if self._raw_fetcher is not None:
            return self._raw_fetcher(inst, through)

        ib = self._require_connection()
        try:
            import ib_insync as ibi  # type: ignore

            # Resolves symbol, exchange and front month, and raises if the result is not
            # a single listed contract. See _front_month_contract.
            contract = _front_month_contract(ib, ibi, inst)

            bars = ib.reqHistoricalData(
                contract,
                endDateTime=pd.Timestamp(through).strftime("%Y%m%d %H:%M:%S"),
                durationStr=self._bar_duration,
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
                # P2: formatDate=1 returns strings in exchange local time (ET for CME/NKD).
                # Do NOT use formatDate=2 (epoch UTC) — ib_insync may not expose it cleanly.
                # Index is parsed below as naive ET (no UTC conversion).
                timeout=120,  # IBKR pacing: default 60s too short when 5+ contracts queued
            )
            if not bars:
                return pd.DataFrame()
            df = ibi.util.df(bars)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.set_index("date")
            # P2: ib_insync 0.9.86 parses formatDate=1 bars into tz-aware datetime (US/Central
            # for CME — Chicago exchange tz). Convert to ET naive so runner comparisons work.
            # If ib_insync ever returns naive strings instead, parse directly (assumed ET).
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_convert("America/New_York").tz_localize(None)
            return df
        except IBKRConnectionError:
            raise
        except Exception as exc:
            log.error("IBKRBroker._fetch_raw(%s) failed: %s", inst, exc)
            return pd.DataFrame()

    def send_order(self, order: Order) -> Fill:
        """
        Submit a futures market order to IBKR. BLOCKING — returns after fill confirmation.

        Full contract: see FILL_HANDLING_DESIGN.md

        Four design constraints (do not violate when implementing):

        [1] ENTRY timeout = 30s (ENTRY_FILL_TIMEOUT_SECS).
            After timeout: cancel order, return Fill(status='CANCELLED').
            Runner logs divergence (+1 to _entry_divergence_count) and skips the entry.
            NOTE: skip count is a FLOOR on true divergence — each skip frees cap and
            may admit a different trade, cascading. True optimism = paper P&L vs backtest.

        [2] EXIT order type = MARKET, no timeout.
            Exit CANCELLED/FAILED → return Fill(status='FAILED'), runner sets exit_pending=True.
            PARTIAL exit → runner flags remaining contracts exit_pending=True.
            exit_pending positions are retried via _retry_pending_exits() at next run_day start.
            NOTE: remaining uses exit_pending flag, NOT exit_day (already fired, won't re-trigger).

        [3] Exit fail escalation at 3× consecutive fails:
            Indicates market halt / instrument suspension — beyond automated resolution.
            Runner response: CRITICAL alert + halt new entries + continue retrying exits
            + flag operational_status "manual_required". Code cannot self-resolve.
            Operator must close manually via TWS or contact broker.

        [4] Blocking time budget (order counts MEASURED, fill times DESIGN ASSUMPTION):
            Order counts from IS 2018-2024 (N=1381 days):
              median = 2E+2X, p99 = 6E+5X, peak = 8E+5X (2018-03-27, all-cluster stress day)
            Fill times — NOT yet measured, unverified design assumptions:
              entry fast fill ~5s, entry timeout 30s; exit fast fill ~5s
            Block time = n_entries×entry_time + n_exits×exit_time:
              typical peak = 8×5s + 5×5s = 65s
              worst-case peak = 8×30s + 5×5s = 265s (4m25s, all entries timeout)
            Original "105s" estimate was p75 (3E+3X), not worst-case.
            At implementation: verify runner_start + 300s < session_end_time (5-min buffer).
            Emit WARN if remaining_session_time < 300s at run_day start.
            Verify actual fill times in first paper weeks; update 30s/5s assumptions.

        Production TODOs (not yet tested against live Gateway):
          - Build correct futures Contract (symbol, lastTradeDateOrContractMonth, exchange)
          - Use Market order for BOTH entry and exit (see [2])
          - Map cluster → contractMonth: use get_roll_event(inst, today) to check roll date;
            on roll date close front_month contract, open next_month. See _handle_rollover().
          - Implement _wait_for_fill(trade, timeout_secs=30 for entry, None for exit)
          - Extend Fill dataclass with status/filled_qty/avg_price/error_msg (see broker.py)
        """
        if self._raw_fetcher is not None:
            # Test mode: simulate fill
            if order.action == "OPEN":
                self._positions.append(BrokerPosition(
                    order.inst, order.direction, order.contracts, order.cluster,
                    order.ref_day, order.exit_day, order.pnl_sized))
            else:
                for i, p in enumerate(self._positions):
                    if (p.inst, p.cluster, p.direction) == (order.inst, order.cluster, order.direction):
                        self._positions.pop(i)
                        self._equity += order.pnl_sized
                        break
            return Fill(order.inst, order.action, order.direction,
                        order.contracts, order.cluster, order.pnl_sized)

        ib = self._require_connection()
        try:
            import ib_insync as ibi  # type: ignore

            # Order path: an unresolved contract here sends a live order against
            # something IBKR never confirmed, so this raises rather than proceeding.
            contract = _front_month_contract(ib, ibi, order.inst)

            # Map direction+action → IBKR BUY/SELL
            # OPEN LONG→BUY, OPEN SHORT→SELL, CLOSE LONG→SELL, CLOSE SHORT→BUY
            if order.action == "OPEN":
                ibkr_action = "BUY" if order.direction == "LONG" else "SELL"
                timeout_secs = (self._test_entry_timeout
                                if self._test_entry_timeout is not None
                                else ENTRY_FILL_TIMEOUT_SECS)
            else:
                ibkr_action = "SELL" if order.direction == "LONG" else "BUY"
                timeout_secs = EXIT_FILL_TIMEOUT_SECS

            # A3 hook: LimitOrder at unreachable price forces timeout (test only).
            # A2 hook: LimitOrder near market with large qty can trigger partial fill.
            if order.action == "OPEN" and self._test_entry_lmt_price is not None:
                ibkr_order = ibi.LimitOrder(ibkr_action, order.contracts,
                                            self._test_entry_lmt_price)
            else:
                ibkr_order = ibi.MarketOrder(ibkr_action, order.contracts)
            # Futures trade 23h/day (electronic session 18:00–17:00 ET).
            # outsideRth=True lets IBKR execute outside regular trading hours (RTH 09:30–16:15).
            # Without this, IBKR's "DAY" order preset cancels orders placed after RTH close.
            ibkr_order.outsideRth = True
            # TIF must be set explicitly. Left blank, IBKR applies the account order
            # preset and emits code 10349 "Order TIF was set to DAY based on order
            # preset". 10349 is a warning, but it is absent from ib_insync's hardcoded
            # `warningCodes` set (wrapper.py:1097), so ib_insync treats it as an error
            # and sets trade.orderStatus.status = Cancelled *client-side* while IBKR
            # goes on to fill the order. Setting TIF removes the trigger; the fill
            # verification in _verified_status() covers every other code that could do
            # the same thing. Listing 10349 in _IBKR_INFORMATIONAL only quiets our own
            # log line — ib_insync has already mutated the status by then.
            ibkr_order.tif = "DAY"
            t0 = time.time()
            trade = ib.placeOrder(contract, ibkr_order)
            log.info(
                "send_order: placed %s %s %s ×%d cluster=%s",
                order.action, ibkr_action, order.inst, order.contracts, order.cluster,
            )

            # Poll until terminal state or timeout
            deadline = t0 + timeout_secs
            while not trade.isDone() and time.time() < deadline:
                ib.sleep(0.1)

            elapsed = time.time() - t0

            if not trade.isDone():
                ib.cancelOrder(trade.order)
                ib.sleep(2.0)
                if order.action == "OPEN":
                    log.warning(
                        "send_order: ENTRY timeout %ss %s %s — CANCELLED (elapsed=%.1fs)",
                        timeout_secs, order.inst, order.direction, elapsed,
                    )
                    return Fill(order.inst, order.action, order.direction,
                                order.contracts, order.cluster,
                                status="CANCELLED",
                                error_msg=f"entry timeout after {timeout_secs}s")
                else:
                    log.error(
                        "send_order: EXIT timeout %ss %s %s — FAILED, exit_pending (elapsed=%.1fs)",
                        timeout_secs, order.inst, order.direction, elapsed,
                    )
                    return Fill(order.inst, order.action, order.direction,
                                order.contracts, order.cluster,
                                status="FAILED",
                                error_msg=f"exit timeout after {timeout_secs}s")

            status, actual_filled, avg_price = self._verified_status(ib, trade)
            commission = self._trade_commission(trade)

            if status == "Filled":
                # Partial fill: filled < ordered (rare for MARKET on liquid futures)
                if 0 < actual_filled < order.contracts:
                    log.warning(
                        "send_order: PARTIAL %s %s %d/%d @ %.4f (elapsed=%.1fs)",
                        order.action, order.inst, actual_filled, order.contracts,
                        avg_price, elapsed,
                    )
                    return Fill(order.inst, order.action, order.direction,
                                order.contracts, order.cluster,
                                status="PARTIAL", filled_qty=actual_filled,
                                avg_price=avg_price, commission=commission,
                                # A partial fill is still a fill, on a real contract.
                                # Omitting this put the position in the book with an
                                # unknown month — unreachable at one lot per order, and
                                # live the moment the system scales.
                                contract_month=getattr(
                                    contract, "lastTradeDateOrContractMonth", None))

                log.info(
                    "send_order: FILLED %s %s ×%d @ %.4f (elapsed=%.1fs)",
                    order.action, order.inst, order.contracts, avg_price, elapsed,
                )
                return Fill(order.inst, order.action, order.direction,
                            order.contracts, order.cluster,
                            # pnl_sized=0: live equity tracked via get_equity(), not pnl accumulation
                            pnl_sized=0.0, status="FILLED", avg_price=avg_price,
                            commission=commission,
                            # The month this order actually went to, read off the
                            # contract that was sent rather than derived again.
                            contract_month=getattr(
                                contract, "lastTradeDateOrContractMonth", None))

            # Terminal but not Filled (Cancelled / ApiCancelled / Inactive)
            if order.action == "OPEN":
                log.warning(
                    "send_order: OPEN %s %s not filled — status=%s",
                    order.inst, order.direction, status,
                )
                return Fill(order.inst, order.action, order.direction,
                            order.contracts, order.cluster,
                            status="CANCELLED", error_msg=f"order status: {status}")
            else:
                log.error(
                    "send_order: CLOSE %s %s not filled — status=%s (will retry next day)",
                    order.inst, order.direction, status,
                )
                return Fill(order.inst, order.action, order.direction,
                            order.contracts, order.cluster,
                            status="FAILED", error_msg=f"exit order status: {status}")

        except IBKRConnectionError:
            raise
        except Exception as exc:
            log.error(
                "send_order(%s %s %s ×%d) failed: %s",
                order.action, order.inst, order.direction, order.contracts, exc,
            )
            fail_status = "CANCELLED" if order.action == "OPEN" else "FAILED"
            return Fill(order.inst, order.action, order.direction,
                        order.contracts, order.cluster,
                        status=fail_status, error_msg=str(exc))

    def _verified_status(self, ib, trade) -> "tuple[str, int, float]":
        """Read (status, filled, avg_price) off a Trade, refusing to trust a bare
        'Cancelled' that carries no fill.

        ib_insync sets `trade.orderStatus.status = Cancelled` on ANY IBKR message whose
        code is missing from its hardcoded `warningCodes` set (wrapper.py:1097) — pure
        warnings included. The mutation is client-side only; the order keeps running at
        IBKR. Confirmed live 2026-08-03: three OPEN orders were reported Cancelled 18ms
        after submission (code 10349) and all three filled. Because the STP block in
        runner.py is gated on fill status, the resulting positions were carried
        overnight with no stop order and no alert.

        On a Cancelled/Inactive reading with nothing filled, re-poll briefly and let
        `trade.fills` decide: an execution report exists only if the order really
        traded, so it outranks the local status flag.
        """
        status = trade.orderStatus.status
        filled = int(trade.orderStatus.filled or 0)
        avg = float(trade.orderStatus.avgFillPrice or 0.0)
        if status not in ("Cancelled", "ApiCancelled", "Inactive") or filled:
            return status, filled, avg

        for _ in range(int(CANCEL_VERIFY_SECS / 0.25)):
            ib.sleep(0.25)
            if trade.fills or trade.orderStatus.status == "Filled":
                break

        status = trade.orderStatus.status
        filled = int(trade.orderStatus.filled or 0)
        avg = float(trade.orderStatus.avgFillPrice or 0.0)

        if not filled and trade.fills:
            # orderStatus never caught up — derive from the execution reports.
            filled = int(sum(f.execution.shares for f in trade.fills))
            if filled:
                avg = sum(f.execution.shares * f.execution.price
                          for f in trade.fills) / filled

        if filled:
            log.warning(
                "send_order: orderId=%s reported status=%s but %d contract(s) executed "
                "@ %.4f — trusting the execution report (ib_insync false-cancel)",
                trade.order.orderId, status, filled, avg,
            )
            status = "Filled"
        return status, filled, avg

    @staticmethod
    def _trade_commission(trade) -> "float | None":
        total = 0.0
        seen = False
        for fill in getattr(trade, "fills", []) or []:
            report = getattr(fill, "commissionReport", None)
            value = getattr(report, "commission", None)
            try:
                if value is not None:
                    total += float(value)
                    seen = True
            except (TypeError, ValueError):
                continue
        return round(total, 2) if seen else None

    def get_positions(self) -> list:
        """Return current open positions from IBKR.

        Live path: calls ib.positions() which returns ib_insync-cached data
        (ib_insync auto-subscribes to position updates on connect). Fields
        cluster/entry_day/pnl_sized are not available from IBKR — set to
        sentinel values. Caller (B3 reconcile) compares only inst/direction/contracts.

        Uses retry-until-stable: reads until two consecutive results are identical,
        confirming the subscription has settled. A sleep-only approach cannot verify
        settlement — IB pushes position data asynchronously and a single empty read
        may arrive before IB has sent all positions.

        Test path (_raw_fetcher set): returns self._positions directly (injected).
        """
        if self._raw_fetcher is not None:
            return list(self._positions)
        ib = self._require_connection()

        def _read() -> "tuple[frozenset, list]":
            result = []
            for pos in ib.positions():
                qty = pos.position   # signed: positive = LONG, negative = SHORT
                if qty == 0:
                    continue
                result.append(BrokerPosition(
                    inst=_to_runner(pos.contract.symbol),
                    direction="LONG" if qty > 0 else "SHORT",
                    contracts=int(abs(qty)),
                    cluster="UNKNOWN",   # IBKR has no cluster concept; B3 ignores
                    entry_day=None,
                    exit_day=None,
                    pnl_sized=0.0,
                ))
            return frozenset((p.inst, p.direction, p.contracts) for p in result), result

        # Read until two consecutive reads match (subscription settled).
        # Max 4 reads × 2s = ~8s; warns and returns last result if not stable.
        _DELAY_S, _MAX = 2.0, 4
        ib.sleep(_DELAY_S)
        prev_key, prev_result = _read()
        for _n in range(_MAX - 1):
            ib.sleep(_DELAY_S)
            curr_key, curr_result = _read()
            if curr_key == prev_key:
                log.debug("get_positions: stable at read %d (%d position(s))", _n + 2, len(curr_result))
                return curr_result
            log.debug("get_positions: read %d %d→%d positions — still settling",
                      _n + 2, len(prev_result), len(curr_result))
            prev_key, prev_result = curr_key, curr_result

        log.warning(
            "get_positions: not stable after %d reads (%.0fs) — returning last result (%d positions)",
            _MAX, _MAX * _DELAY_S, len(prev_result),
        )
        return prev_result

    def get_equity(self) -> float:
        """Return current account equity (NetLiquidation) in account base currency.

        ib_insync auto-subscribes to account updates on connect — reqAccountUpdates()
        is redundant and causes hangs. Just sleep to let initial data arrive, then read
        the cached accountValues(). Accept any currency (CAD/USD/BASE accounts all work).
        """
        if self._raw_fetcher is not None:
            return self._equity

        ib = self._require_connection()
        try:
            # Retry up to 4× with increasing delay: account subscription push from IB
            # can arrive slowly (especially on first connect after a fast reconnect).
            # equity=0 on attempt 1 is normal — this is "slow, retry" not "wrong, abort".
            for _attempt in range(4):
                ib.sleep(2.0 + _attempt)   # 2s, 3s, 4s, 5s — total ~14s max
                candidates = [av for av in ib.accountValues()
                              if av.tag == "NetLiquidation"]
                _val: "float | None" = None
                for av in candidates:
                    if av.currency == "BASE":
                        _val = float(av.value); break
                if _val is None:
                    for av in candidates:
                        if av.currency in ("USD", "CAD"):
                            _val = float(av.value); break
                if _val is None and candidates:
                    _val = float(candidates[0].value)
                if _val is not None and _val > 0:
                    return _val
                if _val == 0.0 and _attempt < 3:
                    log.warning(
                        "get_equity: attempt %d returned 0 — "
                        "account subscription settling, retrying...", _attempt + 1,
                    )
            # Exhausted retries
            if _val is not None:
                if _val == 0.0:
                    raise IBKRConnectionError(
                        "get_equity: NetLiquidation=0 after 4 attempts "
                        "(~14s) — check account subscription / paper balance"
                    )
                return _val
            raise IBKRConnectionError("NetLiquidation not found in IBKR account values")
        except IBKRConnectionError:
            raise
        except Exception as exc:
            raise IBKRConnectionError(f"get_equity() failed: {exc}") from exc

    # ── STP: stop order management ───────────────────────────────────────────

    def place_stop(self, inst: str, direction: str, contracts: int,
                   stop_price: float, cluster: str) -> str:
        """Place a GTC stop order for overnight exit protection on a multi-day position.

        LONG  → SELL STP at stop_price  (exit if price falls to stop_price)
        SHORT → BUY  STP at stop_price  (exit if price rises to stop_price)

        outsideRth=True: stop triggers in extended/overnight Globex session.
        tif='GTC': order survives session boundaries until manually cancelled.

        Returns IBKR orderId string on success, '' on failure.
        Failure is non-fatal — runner logs ALERT and continues (position open without STP).
        """
        if self._raw_fetcher is not None:
            return f"mock-stp-{inst}"  # offline / test mode

        ib = self._require_connection()
        try:
            import ib_insync as ibi  # type: ignore

            contract = _front_month_contract(ib, ibi, inst)

            ibkr_action = "SELL" if direction == "LONG" else "BUY"
            # Chandelier levels are continuous; IBKR only accepts prices on the tick
            # grid and rejects anything else with code 110.
            tick_price = self._round_stop_to_tick(inst, direction, stop_price)
            if tick_price != stop_price:
                log.info("place_stop: %s %s stop %.4f → %.4f (tick %s)",
                         inst, direction, stop_price, tick_price,
                         self._tick_size(inst))
            stp_order = ibi.StopOrder(ibkr_action, contracts, tick_price)
            stp_order.outsideRth = True
            stp_order.tif = "GTC"

            trade = ib.placeOrder(contract, stp_order)
            accepted, status, reason = self._await_stop_accepted(ib, trade)
            order_id = str(trade.order.orderId)
            if not accepted:
                log.error(
                    "place_stop: %s %s STP ×%d @ %.4f NOT ACCEPTED by IBKR — "
                    "status=%s orderId=%s (client-side id, no order exists) %s",
                    direction, inst, contracts, tick_price, status, order_id, reason,
                )
                return ""
            log.info(
                "place_stop: accepted %s %s STP ×%d @ %.4f orderId=%s status=%s cluster=%s",
                direction, inst, contracts, tick_price, order_id, status, cluster,
            )
            return order_id

        except IBKRConnectionError:
            raise
        except Exception as exc:
            log.error("place_stop(%s %s ×%d @ %.4f) failed: %s",
                      direction, inst, contracts, stop_price, exc)
            return ""

    # Statuses that mean IBKR holds the order. PendingSubmit is NOT one of them:
    # ib_insync sets it locally in placeOrder (ib.py:673) before IBKR says anything.
    _STP_LIVE_STATUS = ("PreSubmitted", "Submitted")
    _PROTECTIVE_SIDE = PROTECTIVE_SIDE
    _STP_DEAD_STATUS = ("Cancelled", "ApiCancelled", "Inactive", "Filled")
    STP_ACCEPT_SECS = 5.0

    @staticmethod
    def _tick_size(inst: str) -> "float | None":
        """Minimum price variation for `inst`, or None if not on record."""
        try:
            from futures.basket import BASKET as _BASKET
            c = _BASKET.get(inst)
            if c is not None and getattr(c, "tick", None):
                return float(c.tick)
        except Exception:
            pass
        try:
            from global_index import specs as _specs
            s = getattr(_specs, "SPECS", {}).get(inst)
            if s is not None and getattr(s, "tick", None):
                return float(s.tick)
        except Exception:
            pass
        return None

    def _round_stop_to_tick(self, inst: str, direction: str, price: float) -> float:
        """Snap a stop price onto the contract's tick grid, away from the market.

        IBKR rejects an off-grid price outright with code 110, "The price does not
        conform to the minimum price variation for this contract". That is what killed
        the stops on 2026-08-05: the chandelier levels 7758.86 (MES, tick 0.25),
        54708.68 (MYM, tick 1.0) and 3038.44 (M2K, tick 0.1) were all off-grid, IBKR
        refused all three, and place_stop reported success because it never checked.

        Direction decides which way to round. A LONG stop sits below the market and
        rounds down; a SHORT stop sits above and rounds up. Always away from the
        market: rounding toward it would tighten a stop the position was not sized for,
        and on a near-market level could push it through and fire on arrival.

        Unknown instrument → returned unchanged. Inventing a grid would be a guess, and
        IBKR will reject it loudly, which is the better failure.
        """
        tick = self._tick_size(inst)
        if not tick:
            return price
        import math
        steps = price / tick
        snapped = (math.floor(steps) if direction == "LONG" else math.ceil(steps)) * tick
        # tick sizes like 0.1 are not exact in binary; round to the tick's own precision
        decimals = max(0, -int(math.floor(math.log10(tick)))) + 2
        return round(snapped, decimals)

    def _await_stop_accepted(self, ib, trade) -> "tuple[bool, str, str]":
        """Wait until a freshly placed stop reaches a status IBKR actually reported.

        Returns (accepted, last_status, reason).

        The previous guard read `trade.order.orderId`, which ib_insync allocates
        client-side in placeOrder (`ib.py:654`: orderId = order.orderId or
        self.client.getReqId(), assigned at :671 before the call returns). It is
        therefore always non-zero and never evidence of anything. Live 2026-08-05:
        three stops logged with ids 62/66/70 did not exist at IBKR — absent from both
        reqAllOpenOrders and reqCompletedOrders — and three positions went unprotected
        overnight while the log and live_positions.json both said they were covered.

        Only a status IBKR sends back counts. Anything else — still PendingSubmit at
        timeout, or a rejection — returns False so the caller reports failure and B4
        can see a naked position instead of a fabricated id.
        """
        status, reason = "", ""
        polls = max(1, int(self.STP_ACCEPT_SECS / 0.2))
        for _ in range(polls):
            ib.sleep(0.2)
            status = getattr(trade.orderStatus, "status", "") or ""
            if status in self._STP_LIVE_STATUS or status in self._STP_DEAD_STATUS:
                break
        log_entries = getattr(trade, "log", None) or []
        if log_entries:
            reason = getattr(log_entries[-1], "message", "") or ""
        return (status in self._STP_LIVE_STATUS), status, reason

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by IBKR orderId. Returns True on success, False otherwise."""
        if self._raw_fetcher is not None:
            return True  # offline / test mode

        ib = self._require_connection()
        try:
            order_id_int = int(order_id)
            # reqAllOpenOrders first, exactly as has_working_stop does. ib.trades() is
            # session-local, and the runner reconnects fresh every 5-minute slot — so a
            # stop placed on an earlier day is never in it. Scanning trades() alone
            # reported "not found" for orders that were live at IBKR for days
            # (live 2026-08-05: orderIds 9 and 10, still PreSubmitted).
            # Use what reqAllOpenOrders RETURNS, not ib.openTrades(). openTrades reads
            # wrapper.trades, an accumulating cache that never evicts: IBKR pushes status
            # updates only to the client that owns an order, so a cross-client order that
            # fills is never marked done and lingers there forever (live 2026-08-06: a
            # filled M2K stop still read PreSubmitted 16 minutes later).
            matching = [t for t in ib.reqAllOpenOrders()
                        if t.order.orderId == order_id_int and not t.isDone()]
            if not matching:
                log.warning(
                    "cancel_order: orderId=%s not found among open orders at the broker "
                    "(checked across all clients)", order_id,
                )
                return False
            trade = matching[0]
            ib.cancelOrder(trade.order)
            # cancelOrder is a request. Confirm the order actually left the book before
            # calling it cancelled — live 2026-08-06 a wrong-side MYM stop was
            # "cancelled" twice, reported success both times, and stayed PreSubmitted
            # throughout (it belonged to another clientId). Reporting success there
            # tells the caller a live, dangerous order is gone.
            for _ in range(10):
                ib.sleep(0.5)
                if trade.isDone() or getattr(trade.orderStatus, "status", "") in (
                        "Cancelled", "ApiCancelled", "Filled", "Inactive"):
                    log.info("cancel_order: cancelled orderId=%s", order_id)
                    return True
            # IBKR only honours a cancel from the clientId that placed the order
            # (confirmed live 2026-08-06: MYM #10 refused cancels from clientIds 1, 77
            # and 82, then cancelled first try from 93, the id that placed it). Naming
            # the owner turns this from "it failed" into an instruction.
            owner = getattr(trade.order, "clientId", None)
            log.error(
                "cancel_order: orderId=%s STILL OPEN 5s after cancelOrder — status=%s, "
                "placed by clientId=%s. IBKR only accepts a cancel from the originating "
                "client: reconnect with clientId=%s, or cancel it in TWS.",
                order_id, getattr(trade.orderStatus, "status", "?"), owner, owner,
            )
            return False

        except IBKRConnectionError:
            raise
        except Exception as exc:
            log.error("cancel_order(orderId=%s) failed: %s", order_id, exc)
            return False

    def get_order_status(self, order_id: str) -> str:
        """Query order status by IBKR orderId.

        Returns 'FILLED' | 'CANCELLED' | 'PENDING' | 'NOT_FOUND'.
        Used by B3 reconciliation to distinguish STP-triggered exits from orphan positions.

        Note: after a TWS/Gateway daily restart, session-level trade history is cleared.
        A GTC STP that filled in the previous session may not appear in ib.trades(),
        but may appear in ib.fills() (execution reports) if the same session is still live.
        Return 'NOT_FOUND' if the order cannot be located — B3 will treat as mismatch.
        """
        if self._raw_fetcher is not None:
            return "PENDING"  # offline / test mode

        ib = self._require_connection()
        try:
            order_id_int = int(order_id)

            # Check open/recent trades
            for t in ib.trades():
                if t.order.orderId == order_id_int:
                    s = t.orderStatus.status
                    if s == "Filled":
                        return "FILLED"
                    if s in ("Cancelled", "ApiCancelled", "Inactive"):
                        return "CANCELLED"
                    return "PENDING"

            # Check execution reports (filled orders, current session)
            for fill in ib.fills():
                if getattr(fill.execution, "orderId", None) == order_id_int:
                    return "FILLED"

            # Check open/active orders — GTC STPs survive TWS daily restart (17:00 ET)
            # and are resubmitted by IB; they appear here even when ib.trades() is cleared.
            # This distinguishes "STP still live (GTC resubmitted)" from "STP filled/gone".
            #
            # reqAllOpenOrders first: openTrades() carries orders from other clientIds —
            # or from this runner's own earlier process — only after that request. Without
            # it a stop placed yesterday reads NOT_FOUND, which B3 escalates to CRITICAL
            # and a halt. Same blind spot as cancel_order had.
            for t in ib.reqAllOpenOrders():
                if t.order.orderId == order_id_int:
                    s = t.orderStatus.status
                    if s == "Filled":
                        return "FILLED"
                    if s in ("Cancelled", "ApiCancelled", "Inactive"):
                        return "CANCELLED"
                    return "PENDING"   # Submitted / PreSubmitted = live GTC on exchange

            return "NOT_FOUND"

        except IBKRConnectionError:
            raise
        except Exception as exc:
            log.error("get_order_status(orderId=%s) failed: %s", order_id, exc)
            return "NOT_FOUND"

    def has_working_stop(self, inst: str, direction: "str | None" = None,
                         contracts: "int | None" = None) -> bool:
        """True if this position is already covered by live stops at IBKR.

        B4 calls this before re-placing a stop for a position whose stop_order_id is
        missing, to avoid stacking a second STP on the same contract (both firing
        would close the position twice and open the opposite side).

        reqAllOpenOrders() is issued first so orders placed by *other* clientIds — or
        by an earlier process — are visible; openTrades() alone only reflects orders
        this session knows about.

        With `inst` alone the answer is "does ANY stop exist on this symbol", which is
        what this method used to ask and what makes it wrong for two positions sharing a
        contract: the first one's stop makes B4 refuse to place the second one's, and
        `unprotected_positions` reports the symbol as covered. Passing `direction` and
        `contracts` narrows it to this position's own protective side and its own size.

        Side matters on its own: a SELL stop does not protect a SHORT, it doubles it.
        The symbol-level form cannot tell the difference, which is why the sharper form
        exists rather than the old one being tightened in place — the loose answer is
        still the right one for callers that only want "is anything working here".
        """
        if self._raw_fetcher is not None:
            return False  # offline / test mode

        want = self._PROTECTIVE_SIDE.get(direction) if direction else None
        need = int(contracts or 0)
        covered = 0
        ib = self._require_connection()
        for t in ib.reqAllOpenOrders():
            if _to_runner(t.contract.symbol) != inst:
                continue
            if t.order.orderType not in ("STP", "STP LMT"):
                continue
            if t.orderStatus.status not in self._STP_LIVE_STATUS:
                continue
            if want is None:
                log.info("has_working_stop(%s): orderId=%s status=%s — already protected",
                         inst, t.order.orderId, t.orderStatus.status)
                return True
            if getattr(t.order, "action", None) != want:
                continue
            covered += int(getattr(t.order, "totalQuantity", 0) or 0)
            if covered >= need:
                log.info("has_working_stop(%s %s x%d): covered %d — already protected",
                         inst, direction, need, covered)
                return True
        if want is not None and 0 < covered < need:
            # Partly covered is not covered. Say so — B4 will not stack a top-up (it
            # cannot know why the shortfall exists), and a silent "False" here would
            # read as "no stop at all" in the alert.
            log.warning("has_working_stop(%s %s x%d): only %d contract(s) covered",
                        inst, direction, need, covered)
        return False

    def unprotected_positions(self) -> "list | None":
        """Open positions whose OWN contract is not fully covered by stops on THEIR side.

        get_working_stops and the symbol-only form of has_working_stop both match on the
        instrument symbol, which answers "is there a stop for MES" rather than "is this
        position protected". Those differ in three ways, and this method is where each is
        resolved:

          * different expiry — after a rollover, _handle_rollover moves the position to
            the next contract and the old contract's STP is left working. Matching on
            (symbol, expiry) is done here because this is where the IBKR contract objects
            are; nothing above needs a new field.
          * wrong side — a SELL stop against a SHORT does not close it, it doubles it.
            This used to filter on order type and status only, so any live stop on the
            contract counted as protection regardless of direction.
          * short size — this used to test `exp in have`, the EXISTENCE of a stop. A
            1-lot stop under a 2-lot position satisfied that. Contracts are now summed
            and compared against the position.

        Returns None offline — cannot testify rather than testifying falsely.
        Each entry: {"inst", "expiry", "qty", "covered", "stop_expiries"}.

        KNOWN BLIND SPOT — netting. ib.positions() reports the NET position per contract,
        so two sleeves holding opposite sides of the same contract (swing LONG 1 + stress
        SHORT 1) net to zero and BOTH disappear from this scan at `if not p.position`.
        No broker-side check can see them; the account genuinely holds nothing. The book
        is the only witness, which is why B3 compares the file against the net and why
        two clusters must not hold opposing sides of one contract. See OPERATIONS.md,
        "STRESS_MID: tại sao cron 10:20 bị TẮT".
        """
        if self._raw_fetcher is not None:
            return None

        ib = self._require_connection()
        covered: dict = {}      # (sym, expiry, action) -> contracts working
        anywhere: dict = {}     # sym -> expiries carrying a live stop, for the report
        for t in ib.reqAllOpenOrders():
            if t.order.orderType not in ("STP", "STP LMT"):
                continue
            if t.orderStatus.status not in self._STP_LIVE_STATUS:
                continue
            sym = _to_runner(t.contract.symbol)
            exp = t.contract.lastTradeDateOrContractMonth
            act = getattr(t.order, "action", None)
            qty = int(getattr(t.order, "totalQuantity", 0) or 0)
            covered[(sym, exp, act)] = covered.get((sym, exp, act), 0) + qty
            anywhere.setdefault(sym, set()).add(exp)

        out = []
        for p in ib.positions():
            if not p.position:
                continue
            sym = _to_runner(p.contract.symbol)
            exp = p.contract.lastTradeDateOrContractMonth
            qty = int(p.position)
            want = self._PROTECTIVE_SIDE["LONG" if qty > 0 else "SHORT"]
            have = covered.get((sym, exp, want), 0)
            if have >= abs(qty):
                continue
            out.append({"inst": sym, "expiry": exp, "qty": qty, "covered": have,
                        "stop_expiries": sorted(anywhere.get(sym, set()))})
        return out

    def get_working_stops(self) -> "dict | None":
        """{inst: [orderId, ...]} for every stop working at IBKR, across all clients.

        One reqAllOpenOrders round trip covers every position, so B4 and the
        end-of-session check can afford to run it on each 5-minute slot.

        A LIST per instrument, not one id. `working[inst] = orderId` overwrote, so with
        two stops on one contract the dict remembered only the last — and the caller,
        asking `p.inst in working`, was answered about an order belonging to someone
        else. The id is what makes the answer checkable per position.

        Returns None only when this broker is offline (test mode), never {} — the
        caller must be able to tell "nothing working" from "cannot say".
        """
        if self._raw_fetcher is not None:
            return None  # offline / test mode — cannot testify

        ib = self._require_connection()
        working: dict = {}
        for t in ib.reqAllOpenOrders():
            if t.order.orderType not in ("STP", "STP LMT"):
                continue
            if t.orderStatus.status not in self._STP_LIVE_STATUS:
                continue
            working.setdefault(_to_runner(t.contract.symbol), []).append(
                str(t.order.orderId))
        return working

    def find_execution(self, order_id: str, inst: str | None = None) -> "dict | None":
        """The execution record for order_id, or None.

        Uses ib.reqExecutions() — IB's server-side history, which survives the TWS daily
        restart (unlike ib.fills(), session-only, cleared at 17:00 ET). Two-day lookback
        covers a STP fired during yesterday's session plus overnight fills.

        Returns the fill's price, size, time and permId. It used to return a bare True
        and drop all of it, which is how the exit price of every stop-triggered close
        went unrecorded: the runner sends no order when a stop fires, so nothing else
        writes one, and this is the single moment the record is in hand. Measured
        2026-08-07: reqExecutions served a fill on the day it happened and had forgotten
        it by the next, so the data is only available here, once.

        permId is included because it is IBKR's stable global identifier. orderId
        repeats across clients — the ambiguity behind the #62-vs-#9 mix-up.

        Falsy (None) on not-found OR any error — callers must treat that conservatively
        (halt the strategy, not silently infer a clean exit).
        """
        if self._raw_fetcher is not None:
            return None    # test mode — caller uses get_order_status() FILLED path
        ib = self._require_connection()
        try:
            import ib_insync as ibi
            import datetime
            # 2-day lookback covers: STP fired yesterday before 17:00 ET boundary
            # (IB's "previous trading day") plus overnight + early-morning fills.
            lookback = (
                datetime.date.today() - datetime.timedelta(days=2)
            ).strftime("%Y%m%d 00:00:00")
            order_id_int = int(order_id)
            fills = ib.reqExecutions(ibi.ExecutionFilter(time=lookback))

            # M3: orderId alone does not identify an execution, and the docstring above
            # has said so all along while the code matched on it and took the first hit.
            # cancel_order records clientIds 1, 77, 82 and 93 on this account on
            # 2026-08-06; _book_realised takes price and shares from whatever comes back
            # and moves the sleeve ledger with them, so a collision books the sleeve at
            # a stranger's fill.
            #
            # The instrument is free disambiguation — both call sites hold the OpenPos —
            # and an execution on a different contract is definitely not ours.
            candidates = []
            for fill in fills:
                ex = fill.execution
                if getattr(ex, "orderId", None) != order_id_int:
                    continue
                if inst is not None:
                    _sym = getattr(getattr(fill, "contract", None), "symbol", "") or ""
                    if _sym and _to_runner(_sym) != inst:
                        continue
                candidates.append(fill)

            if not candidates:
                return None
            if len(candidates) > 1:
                # Nothing left to tell them apart, so there is no right answer to
                # return and the first one is wrong half the time, silently. None sends
                # the caller down the no-execution-record path, which books the placed
                # stop level and marks the row an estimate — a number that admits what
                # it is beats a precise one belonging to someone else.
                log.error(
                    "find_execution(orderId=%s inst=%s): %d executions match and "
                    "nothing distinguishes them (permIds %s). Refusing to pick one; "
                    "the caller will book the placed stop level as an estimate.",
                    order_id, inst, len(candidates),
                    [getattr(f.execution, "permId", None) for f in candidates],
                )
                return None

            for fill in candidates:
                ex = fill.execution
                return {
                    "order_id": order_id_int,
                    "perm_id":  getattr(ex, "permId", None),
                    "price":    float(getattr(ex, "price", 0.0) or 0.0),
                    "shares":   float(getattr(ex, "shares", 0.0) or 0.0),
                    "time":     str(getattr(ex, "time", "") or ""),
                    "commission": (
                        float(getattr(getattr(fill, "commissionReport", None), "commission"))
                        if getattr(getattr(fill, "commissionReport", None), "commission", None) is not None
                        else None
                    ),
                }
            return None
        except Exception as exc:
            log.warning("find_execution(orderId=%s) failed: %s", order_id, exc)
            return None

    # ── C2: Rollover ──────────────────────────────────────────────────────────

    def _handle_rollover(self, inst: str, today, _direction: str,
                         _contracts: int, _cluster: str) -> "tuple[Fill, Fill] | None":
        """
        C2: Roll a futures position from front-month to next-month contract.

        Called by runner._handle_rollover_if_needed() at the START of run_day
        for each open position, BEFORE signal generation.

        Roll logic:
          1. Check get_roll_event(inst, today) → (front_month, next_month) or None.
          2. If roll day:
             a. CLOSE front_month: placeOrder(Future(inst, front_month), direction, SELL, contracts)
             b. OPEN  next_month:  placeOrder(Future(inst, next_month),  direction, BUY,  contracts)
          3. Return (close_fill, open_fill) so runner can update position contract_month.
          4. Position identity is preserved: entry_day/exit_day/cluster/risk$ unchanged,
             only contract_month updates.

        Position identity across roll:
          runner.state.open_positions keeps the same OpenPos object; only the
          contract_month field (TBD in OpenPos) changes.  P&L accounting is based
          on risk_dollars and exit_day — not contract price — so no adjustment needed.

        Code implemented. Not yet tested against live IBKR — verify contract month
        mapping on first real paper roll event. Offline (MockBroker) path returns
        synthetic fills and is unit-testable without a live Gateway connection.
        """
        roll = get_roll_event(inst, today)
        if roll is None:
            return None  # not a roll day

        front_month, next_month = roll
        log.info(
            "C2: ROLLOVER %s on %s — close %s → open %s (×%d cluster=%s)",
            inst, pd.Timestamp(today).date(), front_month, next_month, _contracts, _cluster,
        )

        # Test path: synthetic fills so runner rollover logic can be unit-tested offline
        if self._raw_fetcher is not None:
            return (
                Fill(inst, "CLOSE", _direction, _contracts, _cluster,
                     status="FILLED", avg_price=0.0),
                Fill(inst, "OPEN",  _direction, _contracts, _cluster,
                     status="FILLED", avg_price=0.0),
            )

        ib = self._require_connection()
        import ib_insync as ibi  # type: ignore

        close_side = "SELL" if _direction == "LONG" else "BUY"
        open_side  = "BUY"  if _direction == "LONG" else "SELL"

        # ── CLOSE front month ────────────────────────────────────────────────
        # H1: the shared resolver, not a fourth hand-rolled contract. It translates the
        # symbol (MNKD -> MNK), picks the exchange per symbol (MYM -> CBOT) and raises
        # rather than letting an unresolved conId 0 become a live market order.
        front_contract = _month_contract(ib, ibi, inst, front_month)
        close_ibkr = ibi.MarketOrder(close_side, _contracts)
        close_ibkr.outsideRth = True
        close_ibkr.tif = "DAY"   # see send_order: blank TIF triggers code 10349
        t0 = time.time()
        close_trade = ib.placeOrder(front_contract, close_ibkr)
        log.info("C2: placed CLOSE %s %s ×%d", close_side, front_month, _contracts)

        deadline = t0 + EXIT_FILL_TIMEOUT_SECS
        while not close_trade.isDone() and time.time() < deadline:
            ib.sleep(0.1)
        elapsed = time.time() - t0

        if not close_trade.isDone():
            ib.cancelOrder(close_trade.order)
            ib.sleep(2.0)
            log.critical(
                "C2: ROLLOVER CLOSE timed out %s %s (%.1fs) — roll ABORTED; "
                "position unchanged in runner state",
                inst, front_month, elapsed,
            )
            return (
                Fill(inst, "CLOSE", _direction, _contracts, _cluster, status="FAILED",
                     error_msg=f"roll-close timeout {EXIT_FILL_TIMEOUT_SECS}s"),
                Fill(inst, "OPEN",  _direction, _contracts, _cluster, status="FAILED",
                     error_msg="skipped — close timed out"),
            )

        close_st, _close_qty, close_price = self._verified_status(ib, close_trade)
        close_commission = self._trade_commission(close_trade)
        close_fill  = Fill(inst, "CLOSE", _direction, _contracts, _cluster,
                           status="FILLED" if close_st == "Filled" else "FAILED",
                           avg_price=close_price,
                           commission=close_commission,
                           contract_month=front_month,
                           error_msg=None if close_st == "Filled"
                                     else f"roll-close status: {close_st}")

        if close_fill.status != "FILLED":
            log.critical(
                "C2: ROLLOVER CLOSE status=%s for %s %s — roll ABORTED; position unchanged",
                close_st, inst, front_month,
            )
            return (
                close_fill,
                Fill(inst, "OPEN", _direction, _contracts, _cluster, status="FAILED",
                     error_msg="skipped — close did not fill"),
            )

        log.info("C2: CLOSE filled %s %s @ %.4f (%.1fs)", inst, front_month, close_price, elapsed)

        # ── OPEN next month ──────────────────────────────────────────────────
        # H1. Note this one resolves AFTER the close has filled: if the next month is not
        # listed, the position is already flat and the runner is told so (the OPEN-failed
        # branch removes it from the book and emits CRITICAL). Raising here is still
        # better than opening a position on a contract IBKR never confirmed.
        next_contract = _month_contract(ib, ibi, inst, next_month)
        open_ibkr = ibi.MarketOrder(open_side, _contracts)
        open_ibkr.outsideRth = True
        open_ibkr.tif = "DAY"   # see send_order: blank TIF triggers code 10349
        t0 = time.time()
        open_trade = ib.placeOrder(next_contract, open_ibkr)
        log.info("C2: placed OPEN %s %s ×%d", open_side, next_month, _contracts)

        deadline = t0 + ENTRY_FILL_TIMEOUT_SECS
        while not open_trade.isDone() and time.time() < deadline:
            ib.sleep(0.1)
        elapsed = time.time() - t0

        if not open_trade.isDone():
            ib.cancelOrder(open_trade.order)
            ib.sleep(2.0)
            log.critical(
                "C2: ROLLOVER OPEN timed out %s %s (%.1fs) AFTER CLOSE SUCCEEDED — "
                "POSITION IS NOW FLAT IN IBKR. Manual intervention required.",
                inst, next_month, elapsed,
            )
            return (
                close_fill,
                Fill(inst, "OPEN", _direction, _contracts, _cluster, status="FAILED",
                     error_msg=f"roll-open timeout {ENTRY_FILL_TIMEOUT_SECS}s — position flat"),
            )

        open_st, _open_qty, open_price = self._verified_status(ib, open_trade)
        open_commission = self._trade_commission(open_trade)
        open_fill  = Fill(inst, "OPEN", _direction, _contracts, _cluster,
                          status="FILLED" if open_st == "Filled" else "FAILED",
                          avg_price=open_price,
                          commission=open_commission,
                          # The month the runner will record on the position — the whole
                          # point of returning both fills from here.
                          contract_month=next_month,
                          error_msg=None if open_st == "Filled"
                                    else f"roll-open status: {open_st} — position flat")

        if open_fill.status == "FILLED":
            log.info(
                "C2: ROLLOVER complete %s: close %s@%.4f → open %s@%.4f  "
                "roll_slippage=%.4f",
                inst, front_month, close_price, next_month, open_price,
                abs(open_price - close_price),
            )
        else:
            log.critical(
                "C2: ROLLOVER OPEN status=%s for %s %s AFTER CLOSE SUCCEEDED — "
                "POSITION IS NOW FLAT IN IBKR. Manual intervention required.",
                open_st, inst, next_month,
            )

        return close_fill, open_fill
