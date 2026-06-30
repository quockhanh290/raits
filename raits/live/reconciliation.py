"""
raits/live/reconciliation.py

Structured per-order reconciliation logging + analysis.

Each filled/rejected order writes one record to:
  - a CSV (human-readable, importable)
  - a JSON-lines file (machine-readable)

ReconciliationLog.analyze() returns aggregate metrics:
  mean/median/p90 slippage ($), slippage_pct, latency, partial-fill rate,
  reject rate, per-strategy slippage, estimated P&L impact of slippage.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from .broker import FillStatus, Order


@dataclass
class ReconRecord:
    signal_ts: float
    ticker: str
    side: str
    strategy: str
    hmm_state: str
    intended_qty: int
    filled_qty: int
    expected_fill_price: float   # limit_price (pre-slippage)
    actual_fill_price: float
    slippage_usd: float          # (actual - expected) * filled_qty, sign: positive = bad
    slippage_pct: float          # slippage_usd / (expected * filled_qty)
    fill_latency_s: float        # fill_ts - signal_ts
    fill_status: str             # FILLED | PARTIAL | REJECTED
    reject_reason: str


def _make_record(order: Order) -> ReconRecord:
    slippage_usd = 0.0
    slippage_pct = 0.0
    if order.fill_status in (FillStatus.FILLED, FillStatus.PARTIAL) and order.filled_qty > 0:
        raw = (order.fill_price - order.limit_price) * order.filled_qty
        # For SELL orders slippage is reversed (lower fill = worse)
        slippage_usd = raw if order.side == "BUY" else -raw
        notional = order.limit_price * order.filled_qty
        slippage_pct = slippage_usd / notional if notional else 0.0

    latency = order.fill_ts - order.signal_ts if order.fill_ts > 0 else 0.0

    return ReconRecord(
        signal_ts=order.signal_ts,
        ticker=order.ticker,
        side=order.side,
        strategy=order.strategy,
        hmm_state=order.hmm_state,
        intended_qty=order.qty,
        filled_qty=order.filled_qty,
        expected_fill_price=order.limit_price,
        actual_fill_price=order.fill_price,
        slippage_usd=slippage_usd,
        slippage_pct=slippage_pct,
        fill_latency_s=latency,
        fill_status=order.fill_status.value,
        reject_reason=order.reject_reason,
    )


_CSV_FIELDS = [
    "signal_ts", "ticker", "side", "strategy", "hmm_state",
    "intended_qty", "filled_qty", "expected_fill_price", "actual_fill_price",
    "slippage_usd", "slippage_pct", "fill_latency_s", "fill_status", "reject_reason",
]


class ReconciliationLog:
    """
    Append-only reconciliation log.

    Usage:
        log = ReconciliationLog(out_dir="data/recon/2026-06-30")
        log.record(order)          # call after each order fills/rejects
        summary = log.analyze()    # call at end of session
    """

    def __init__(self, out_dir: str) -> None:
        os.makedirs(out_dir, exist_ok=True)
        self._csv_path  = os.path.join(out_dir, "orders.csv")
        self._jsonl_path = os.path.join(out_dir, "orders.jsonl")
        self._records: List[ReconRecord] = []

        # Write CSV header on creation
        with open(self._csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
            writer.writeheader()

    def record(self, order: Order) -> ReconRecord:
        """Build and persist a reconciliation record for one order."""
        rec = _make_record(order)
        self._records.append(rec)

        row = asdict(rec)
        with open(self._csv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
            writer.writerow(row)

        with open(self._jsonl_path, "a") as f:
            f.write(json.dumps(row) + "\n")

        return rec

    def analyze(self) -> Dict:
        """Return aggregate reconciliation metrics."""
        records = self._records
        n = len(records)
        if n == 0:
            return {"total_orders": 0}

        filled = [r for r in records if r.fill_status in ("FILLED", "PARTIAL")]
        rejected = [r for r in records if r.fill_status == "REJECTED"]
        partial = [r for r in records if r.fill_status == "PARTIAL"]

        slippages = [r.slippage_usd for r in filled]
        pcts      = [r.slippage_pct for r in filled]
        latencies = [r.fill_latency_s for r in filled]

        def _stats(vals: List[float]) -> Dict:
            if not vals:
                return {"mean": 0.0, "median": 0.0, "p90": 0.0}
            s = sorted(vals)
            p90_idx = int(len(s) * 0.9)
            return {
                "mean":   statistics.mean(s),
                "median": statistics.median(s),
                "p90":    s[min(p90_idx, len(s) - 1)],
            }

        # Per-strategy slippage
        strategies = sorted({r.strategy for r in filled})
        per_strategy: Dict[str, Dict] = {}
        for strat in strategies:
            s_recs = [r for r in filled if r.strategy == strat]
            per_strategy[strat] = {
                "count":           len(s_recs),
                "total_slip_usd":  sum(r.slippage_usd for r in s_recs),
                "mean_slip_usd":   statistics.mean(r.slippage_usd for r in s_recs),
                "mean_slip_pct":   statistics.mean(r.slippage_pct for r in s_recs),
            }

        total_slip_usd = sum(slippages)
        fill_rate = len(filled) / n if n else 0.0

        return {
            "total_orders":       n,
            "filled":             len(filled),
            "partial":            len(partial),
            "rejected":           len(rejected),
            "fill_rate":          fill_rate,
            "partial_fill_rate":  len(partial) / n,
            "reject_rate":        len(rejected) / n,
            "slippage_usd":       _stats(slippages),
            "slippage_pct":       _stats(pcts),
            "latency_s":          _stats(latencies),
            "total_slippage_usd": total_slip_usd,
            "per_strategy":       per_strategy,
            "csv_path":           self._csv_path,
            "jsonl_path":         self._jsonl_path,
        }
