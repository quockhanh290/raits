"""
raits/backtest/reject_funnel.py
--------------------------------
RejectFunnelHandler — a logging.Handler that captures, normalises, and
classifies every "skip / block / reject" message emitted by BacktestEngine.

Usage:
    from raits.backtest.reject_funnel import RejectFunnelHandler

    handler = RejectFunnelHandler()
    logging.getLogger("RAITS.backtest").addHandler(handler)
    logging.getLogger("RAITS.backtest").setLevel(logging.DEBUG)

    engine.run(...)

    for count, cls, reason in handler.funnel():
        print(f"{count:6d}  [{cls:11s}]  {reason}")
    print(f"{handler.mechanical_pct():.0%} of rejects are MECHANICAL")
"""

from __future__ import annotations

import collections
import logging
import re
from typing import List, Tuple

# ── Keywords used to decide whether a log record is a reject event ───────────
_CAPTURE_KEYWORDS: frozenset = frozenset(
    ["skip", "block", "reject", "no ", "empty", "missing"]
)

# ── Keywords that imply the reject is a deliberate FEATURE ───────────────────
_STRUCTURAL_KEYWORDS: frozenset = frozenset([
    "regime", "stress", "bear", "trend", "gap", "atr", "cooldown",
    "safety", "circuit", "pdt", "top-",
])

# ── Keywords that imply a setup was LOST due to missing/bad data ─────────────
_MECHANICAL_KEYWORDS: frozenset = frozenset([
    "no prior", "no or", "missing", "empty", "5-min", "no data", "no range",
])

# ── Regex patterns for normalisation ─────────────────────────────────────────
_TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")
_NUMBER_RE = re.compile(r"-?\d+\.?\d*%?")


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers (also tested directly)
# ─────────────────────────────────────────────────────────────────────────────

def normalise_message(msg: str) -> str:
    """
    Strip ticker symbols and numbers from a log message to produce a
    stable bucket key that merges identical rejects across different tickers.

    AAPL, TSLA, NVDA → <TK>
    0.43%, -7.2, 14  → <N>
    """
    s = _TICKER_RE.sub("<TK>", msg)
    s = _NUMBER_RE.sub("<N>", s)
    return s.strip()


def classify_reason(reason: str) -> str:
    """
    Classify a normalised reject reason as 'MECHANICAL' or 'structural'.

    MECHANICAL check runs first (more specific than structural).
    Unknown/ambiguous reasons default to 'structural' (conservative).

    structural → low trade count is a FEATURE (correct selectivity)
    MECHANICAL → setup was LOST due to data gaps or code bugs
    """
    r = reason.lower()
    if any(kw in r for kw in _MECHANICAL_KEYWORDS):
        return "MECHANICAL"
    if any(kw in r for kw in _STRUCTURAL_KEYWORDS):
        return "structural"
    return "structural"


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────

class RejectFunnelHandler(logging.Handler):
    """
    Attach to the 'RAITS.backtest' logger at DEBUG level.

    For every log record whose message contains a reject/skip keyword the
    handler:
      1. Strips ticker symbols and numbers to produce a normalised bucket key.
      2. Tallies that bucket in a Counter.

    After the backtest run call ``funnel()`` or ``mechanical_pct()`` to
    analyse the results.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.counts: collections.Counter = collections.Counter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        if not any(kw in msg.lower() for kw in _CAPTURE_KEYWORDS):
            return
        bucket = normalise_message(msg)
        self.counts[bucket] += 1

    # ── Analysis ─────────────────────────────────────────────────────────────

    def funnel(self) -> List[Tuple[int, str, str]]:
        """
        Return ``[(count, classification, reason), ...]`` sorted by count desc.

        classification is 'structural' or 'MECHANICAL'.
        """
        return [
            (count, classify_reason(reason), reason)
            for reason, count in self.counts.most_common()
        ]

    def mechanical_pct(self) -> float:
        """
        Fraction of total captured rejects that are MECHANICAL (0.0–1.0).
        Returns 0.0 when no rejects have been captured.
        """
        total = sum(self.counts.values())
        if total == 0:
            return 0.0
        mech = sum(
            count
            for reason, count in self.counts.items()
            if classify_reason(reason) == "MECHANICAL"
        )
        return mech / total
