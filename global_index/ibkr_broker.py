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
from typing import Callable, Optional

import pandas as pd

from global_index.broker import Broker, Order, Fill, BrokerPosition

log = logging.getLogger(__name__)

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
}


def get_roll_event(inst: str, today) -> "tuple[str, str] | None":
    """
    Return (front_month, next_month) if today is a roll date for inst, else None.
    today: str "YYYY-MM-DD" or pd.Timestamp.
    """
    today_str = str(pd.Timestamp(today).date())
    for roll_date, front, nxt in ROLL_SCHEDULE.get(inst, []):
        if roll_date == today_str:
            return front, nxt
    return None


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

    # ── Connection lifecycle ──────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to IB Gateway. Raise IBKRConnectionError on failure."""
        try:
            import ib_insync as ibi  # type: ignore
        except ImportError as exc:
            raise ImportError("ib_insync not installed. Run: pip install ib_insync") from exc
        ib = ibi.IB()
        ib.connect(self._host, self._port, clientId=self._client_id)
        self._ib = ib
        log.info("IBKRBroker connected: %s:%s clientId=%s", self._host, self._port, self._client_id)

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

            # Build a generic futures contract (caller responsible for correct symbol)
            contract = ibi.Future(inst, exchange="CME")
            ib.qualifyContracts(contract)

            bars = ib.reqHistoricalData(
                contract,
                endDateTime=pd.Timestamp(through).strftime("%Y%m%d %H:%M:%S"),
                durationStr=self._bar_duration,
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=1,
            )
            df = ibi.util.df(bars).set_index("date")
            df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York").tz_localize(None)
            return df
        except IBKRConnectionError:
            raise
        except Exception as exc:
            log.error("IBKRBroker.fetch_bars(%s) failed: %s", inst, exc)
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

        self._require_connection()
        raise NotImplementedError(
            "send_order live path not yet implemented — pending IBKR account setup. "
            "Implement: build Contract, placeOrder, poll orderStatus, return Fill."
        )

    def get_positions(self) -> list:
        """Return current open positions known to this broker instance."""
        if self._raw_fetcher is not None:
            return list(self._positions)
        self._require_connection()
        raise NotImplementedError(
            "get_positions live path not yet implemented — pending IBKR account setup. "
            "Implement: ib.positions() → map to BrokerPosition list."
        )

    def get_equity(self) -> float:
        """Return current account equity (NetLiquidation)."""
        if self._raw_fetcher is not None:
            return self._equity

        ib = self._require_connection()
        try:
            import ib_insync as ibi  # type: ignore
            ib.reqAccountUpdates()
            ib.sleep(1.0)
            for av in ib.accountValues():
                if av.tag == "NetLiquidation" and av.currency == "USD":
                    return float(av.value)
            raise IBKRConnectionError("NetLiquidation not found in IBKR account values")
        except IBKRConnectionError:
            raise
        except Exception as exc:
            raise IBKRConnectionError(f"get_equity() failed: {exc}") from exc

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

        NOT YET IMPLEMENTED — pending IBKR account + get_roll_event() verification.
        Implement after send_order live path is working and first paper run confirms
        contract month mapping is correct.
        """
        roll = get_roll_event(inst, today)
        if roll is None:
            return None  # not a roll day

        front_month, next_month = roll
        log.info(
            "C2: ROLLOVER %s on %s — close %s, open %s (%s contracts, cluster=%s)",
            inst, pd.Timestamp(today).date(), front_month, next_month, contracts, cluster,
        )
        raise NotImplementedError(
            f"C2 rollover not yet implemented: "
            f"close {inst} {front_month} → open {inst} {next_month}. "
            f"Implement: build two ibi.Future contracts with lastTradeDateOrContractMonth, "
            f"call send_order for each, return (close_fill, open_fill). "
            f"See ROLL_SCHEDULE for 2026 dates. "
            f"(contracts={_contracts}, cluster={_cluster})"
        )
