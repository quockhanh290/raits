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
from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

from global_index.broker import Broker, Order, Fill, BrokerPosition

log = logging.getLogger(__name__)


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
        Submit a futures market order to IBKR.

        Production TODO (not yet tested against live Gateway):
          - Build correct futures Contract (symbol, lastTradeDateOrContractMonth, exchange)
          - Use LimitOrder at bid/ask instead of MarketOrder for micro futures
          - Map cluster → contractMonth for rollover handling
          - Poll orderStatus events; return Fill after confirmation
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
        raise NotImplementedError(
            "send_order live path not yet implemented — pending IBKR account setup. "
            "Implement: build Contract, placeOrder, poll orderStatus, return Fill."
        )

    def get_positions(self) -> list:
        """Return current open positions known to this broker instance."""
        if self._raw_fetcher is not None:
            return list(self._positions)
        ib = self._require_connection()
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
