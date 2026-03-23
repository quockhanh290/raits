"""
raits/risk/pdt_guard.py
-----------------------
Pattern Day Trader (PDT) rule enforcement.

SEC Rule 4210: a broker must classify a customer as a Pattern Day Trader if
they execute FOUR OR MORE day trades within FIVE business days AND those day
trades represent more than 6% of total trades.  The 6% exemption is ignored
here — we apply the stricter <=3 day-trades-per-5-business-day constraint
unconditionally, which is the conservative approach for a $25k account.

A "day trade" is defined as buying and selling (or selling short and covering)
the SAME security on the SAME calendar day.

Rolling window calculation
--------------------------
"5 business days" is approximated as the 5 most recent weekdays (Mon-Fri)
on or before the reference date.  US market holidays are NOT excluded —
the same simplification used throughout Phase 1A (Monday-proxy pattern).
This is slightly conservative (holidays shrink the effective window), which
is acceptable: better to under-trade than to violate PDT.

Blueprint reference: Section 5.1 (Layer 1 — Infrastructure Controls)
Requirement level:  SHALL
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from enum import Enum

logger = logging.getLogger("RAITS.risk.pdt_guard")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_DAY_TRADES_PER_WINDOW: int = 3   # 4th trade is blocked
WINDOW_TRADING_DAYS: int = 5         # rolling business-day lookback


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class PDTDecisionCode(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"    # 4th day-trade attempt — must hold overnight or skip


@dataclass(frozen=True)
class PDTDecision:
    """Immutable result returned by every PDTGuard method."""
    code: PDTDecisionCode
    reason: str
    data: dict = dc_field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.code == PDTDecisionCode.PASS

    def __repr__(self) -> str:
        return f"PDTDecision({self.code.value}: {self.reason})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prior_trading_days(as_of: date, n: int) -> list[date]:
    """
    Return the n most recent weekdays (Mon-Fri) on or before *as_of*,
    in ascending order (oldest first).

    Examples
    --------
    >>> _prior_trading_days(date(2026, 3, 23), 5)  # Monday
    [date(2026, 3, 17), date(2026, 3, 18), date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 23)]
    >>> _prior_trading_days(date(2026, 3, 21), 5)  # Saturday -> rolls back to Friday window
    [date(2026, 3, 16), date(2026, 3, 17), date(2026, 3, 18), date(2026, 3, 19), date(2026, 3, 20)]
    """
    days: list[date] = []
    cursor = as_of
    while len(days) < n:
        if cursor.weekday() < 5:   # 0=Mon ... 4=Fri
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


# ---------------------------------------------------------------------------
# PDTGuard
# ---------------------------------------------------------------------------

class PDTGuard:
    """
    Tracks day trades in a rolling 5-business-day window and blocks the
    4th day-trade attempt.

    Usage (backtesting)
    -------------------
    guard = PDTGuard()

    # Before generating a new same-day exit:
    result = guard.check_can_day_trade(as_of_date)
    if not result.passed:
        # must hold overnight or skip trade
        ...

    # After a round-trip closes on the same day it opened:
    result = guard.record_day_trade(trade_date)
    if not result.passed:
        # trade was the 4th -> blocked; do NOT count it
        ...

    State persistence
    -----------------
    The guard maintains a running list of day-trade dates.  For backtesting,
    create one instance per simulation run and call record_day_trade() for
    every confirmed day trade.  The guard automatically drops dates outside
    the rolling 5-day window to prevent unbounded memory growth.
    """

    def __init__(self) -> None:
        # List of calendar dates on which a confirmed day trade occurred.
        # Multiple day trades on the same date each occupy one slot.
        self._day_trade_dates: list[date] = []
        logger.debug(
            "PDTGuard initialised (max %d day trades per %d business days)",
            MAX_DAY_TRADES_PER_WINDOW, WINDOW_TRADING_DAYS,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_can_day_trade(self, as_of: date) -> PDTDecision:
        """
        Check whether a new day trade is permitted on *as_of*.

        Returns PASS if fewer than MAX_DAY_TRADES_PER_WINDOW trades have
        occurred in the rolling 5-business-day window, BLOCK otherwise.

        This is a read-only check — it does NOT record a trade.
        Call record_day_trade() only after the trade is confirmed executed.
        """
        count = self._count_in_window(as_of)
        remaining = MAX_DAY_TRADES_PER_WINDOW - count

        logger.debug(
            "PDT check as_of=%s: %d/%d day trades used, %d remaining",
            as_of, count, MAX_DAY_TRADES_PER_WINDOW, max(remaining, 0),
        )

        if count >= MAX_DAY_TRADES_PER_WINDOW:
            reason = (
                f"PDT limit reached: {count}/{MAX_DAY_TRADES_PER_WINDOW} "
                f"day trades used in rolling 5-day window ending {as_of}"
            )
            logger.info("BLOCK — %s", reason)
            return PDTDecision(
                code=PDTDecisionCode.BLOCK,
                reason=reason,
                data={"day_trades_used": count, "window_end": str(as_of)},
            )

        return PDTDecision(
            code=PDTDecisionCode.PASS,
            reason=f"{count}/{MAX_DAY_TRADES_PER_WINDOW} day trades used — {remaining} remaining",
            data={"day_trades_used": count, "remaining": remaining, "window_end": str(as_of)},
        )

    def record_day_trade(self, trade_date: date) -> PDTDecision:
        """
        Attempt to record a day trade on *trade_date*.

        - If the trade is allowed (count < limit), records it and returns PASS.
        - If the trade would be the 4th+, does NOT record it and returns BLOCK.

        Callers must respect the return value: a BLOCK result means the
        intended same-day exit must be converted to an overnight hold or
        the trade must be skipped entirely.
        """
        check = self.check_can_day_trade(trade_date)
        if not check.passed:
            logger.warning(
                "Day trade on %s BLOCKED (would exceed PDT limit). "
                "Convert to overnight hold or skip.",
                trade_date,
            )
            return check

        self._day_trade_dates.append(trade_date)
        self._purge_stale(trade_date)

        count = self._count_in_window(trade_date)
        logger.info(
            "Day trade recorded: %s — now %d/%d in rolling window",
            trade_date, count, MAX_DAY_TRADES_PER_WINDOW,
        )
        return PDTDecision(
            code=PDTDecisionCode.PASS,
            reason=f"Day trade recorded ({count}/{MAX_DAY_TRADES_PER_WINDOW} used)",
            data={"day_trades_used": count, "trade_date": str(trade_date)},
        )

    def day_trades_in_window(self, as_of: date) -> int:
        """Return the count of day trades in the rolling 5-business-day window."""
        return self._count_in_window(as_of)

    def window_dates(self, as_of: date) -> list[date]:
        """Return the 5 business days constituting the current rolling window."""
        return _prior_trading_days(as_of, WINDOW_TRADING_DAYS)

    def reset(self) -> None:
        """Clear all recorded day trades.  Use between simulation runs."""
        self._day_trade_dates.clear()
        logger.debug("PDTGuard reset — all day trade records cleared")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _count_in_window(self, as_of: date) -> int:
        """Count day-trade records that fall within the rolling 5-day window."""
        window = set(_prior_trading_days(as_of, WINDOW_TRADING_DAYS))
        return sum(1 for d in self._day_trade_dates if d in window)

    def _purge_stale(self, as_of: date) -> None:
        """
        Drop day-trade records older than the current rolling window.
        Prevents unbounded memory growth in long backtests.
        """
        window = set(_prior_trading_days(as_of, WINDOW_TRADING_DAYS))
        before = len(self._day_trade_dates)
        self._day_trade_dates = [d for d in self._day_trade_dates if d in window]
        purged = before - len(self._day_trade_dates)
        if purged:
            logger.debug("PDTGuard purged %d stale day-trade record(s)", purged)
