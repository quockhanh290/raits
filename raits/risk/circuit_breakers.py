"""
raits/risk/circuit_breakers.py
-------------------------------
Layer 4 of the 4-layer defense-in-depth risk architecture.

Three independent kill switches that halt trading when account-level
thresholds are breached.  Any one trigger is sufficient to arm the breaker.

Kill Switch 1 — Daily Drawdown (-4%)
    Account loses >= 4% of session-start equity intraday.
    Halt for remainder of session; recovery is manual (next session).

Kill Switch 2 — Consecutive Losses (>= 5)
    Five or more consecutive trades close at a loss (pnl <= 0).
    Counter resets on a winning trade; persists across session boundaries.

Kill Switch 3 — MOC Imbalance (3:50 PM ET, position-level)
    MOC sell imbalance exceeds 50% of 20-day ADV for a held position.
    This is a POSITION-level trigger: it signals emergency exit for that
    specific ticker but does NOT disable account-wide trading.

Design
------
* CircuitBreakerManager is stateful.  One instance per backtest run;
  call reset_for_new_session() at each day boundary.
* The class is side-effect free: it records state and returns BreakerState
  / bool results but does NOT close positions itself.
* BreakerState exposes the current system state for the router.
* Consecutive-loss counter intentionally survives session resets.

Blueprint reference: Section 5.4 (Layer 4 — Systemic Controls)
Requirement level:  SHALL
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from datetime import date
from enum import Enum

logger = logging.getLogger("RAITS.risk.circuit_breakers")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAILY_DRAWDOWN_LIMIT: float   = -0.04   # -4% of session-start equity
CONSECUTIVE_LOSS_LIMIT: int   = 5       # halt after N consecutive losses
MOC_IMBALANCE_FRACTION: float = 0.50   # sell imbalance > 50% of 20-day ADV


# ---------------------------------------------------------------------------
# State / result types
# ---------------------------------------------------------------------------

class BreakerState(str, Enum):
    """Overall account-level circuit-breaker state."""
    ACTIVE   = "ACTIVE"    # normal — trading permitted
    HALTED   = "HALTED"    # kill switch armed — no new orders


class TriggerReason(str, Enum):
    DAILY_DRAWDOWN      = "DAILY_DRAWDOWN"
    CONSECUTIVE_LOSSES  = "CONSECUTIVE_LOSSES"
    MOC_IMBALANCE       = "MOC_IMBALANCE"      # position-level only


@dataclass(frozen=True)
class BreakerResult:
    """Immutable result returned by every CircuitBreakerManager check."""
    passed: bool          # True = trading OK, False = blocked or kill-switch
    kill_switch: bool     # True = newly or previously armed (account level)
    reason: str
    data: dict = dc_field(default_factory=dict)

    def __repr__(self) -> str:
        tag = "KILL" if self.kill_switch else ("PASS" if self.passed else "BLOCK")
        return f"BreakerResult({tag}: {self.reason})"


# ---------------------------------------------------------------------------
# CircuitBreakerManager
# ---------------------------------------------------------------------------

class CircuitBreakerManager:
    """
    Stateful kill-switch manager for a single trading session or backtest run.

    Properties
    ----------
    state              : BreakerState.ACTIVE or HALTED
    trigger_reason     : TriggerReason that armed the switch, or None
    consecutive_losses : current streak of consecutive losing trades
    session_date       : calendar date of the current session (for logging)
    """

    def __init__(self) -> None:
        self._state: BreakerState = BreakerState.ACTIVE
        self._trigger_reason: TriggerReason | None = None
        self._consecutive_losses: int = 0
        self._session_date: date | None = None
        logger.debug("CircuitBreakerManager initialised — state=ACTIVE")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def trigger_reason(self) -> TriggerReason | None:
        return self._trigger_reason

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def session_date(self) -> date | None:
        return self._session_date

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_for_new_session(self, session_date: date) -> None:
        """
        Re-arm the breaker for a new trading session.

        Resets account-level state (HALTED -> ACTIVE, clears trigger reason).
        The consecutive-loss counter is intentionally preserved: a losing
        streak that spans a weekend is still a losing streak.
        """
        prev = self._state.value
        self._state = BreakerState.ACTIVE
        self._trigger_reason = None
        self._session_date = session_date
        logger.info(
            "CircuitBreakerManager reset for session %s "
            "(was %s, consecutive_losses=%d carry-forward)",
            session_date, prev, self._consecutive_losses,
        )

    # ------------------------------------------------------------------
    # Pre-trade gate
    # ------------------------------------------------------------------

    def assert_trading_active(self) -> BreakerResult:
        """
        Lightweight gate check: call before generating any new order.
        Returns immediately if the kill switch is already armed.
        """
        if self._state == BreakerState.HALTED:
            return self._already_halted()
        return BreakerResult(passed=True, kill_switch=False, reason="Trading active")

    # ------------------------------------------------------------------
    # Kill Switch 1 — Daily Drawdown
    # ------------------------------------------------------------------

    def check_daily_drawdown(
        self,
        account_equity: float,
        session_start_equity: float,
    ) -> BreakerResult:
        """
        Return a kill-switch result if session drawdown has hit -4%, else PASS.

        Parameters
        ----------
        account_equity       : current mark-to-market account value (USD)
        session_start_equity : account value at 09:30 session open (USD)

        Call after every position close and at regular session intervals.
        """
        if self._state == BreakerState.HALTED:
            return self._already_halted()

        if session_start_equity <= 0:
            logger.warning(
                "check_daily_drawdown: session_start_equity=%s non-positive — skipped",
                session_start_equity,
            )
            return BreakerResult(
                passed=True, kill_switch=False,
                reason="session_start_equity non-positive — drawdown check skipped",
            )

        dd_pct = (account_equity - session_start_equity) / session_start_equity
        logger.debug(
            "Daily drawdown: equity=%.2f start=%.2f dd=%.4f (limit=%.4f)",
            account_equity, session_start_equity, dd_pct, DAILY_DRAWDOWN_LIMIT,
        )

        if dd_pct <= DAILY_DRAWDOWN_LIMIT:
            msg = (
                f"Daily drawdown {dd_pct:.2%} breached limit "
                f"{DAILY_DRAWDOWN_LIMIT:.0%} — kill switch activated"
            )
            return self._arm(TriggerReason.DAILY_DRAWDOWN, msg, {
                "daily_dd_pct": round(dd_pct, 6),
                "account_equity": account_equity,
                "session_start_equity": session_start_equity,
            })

        return BreakerResult(
            passed=True, kill_switch=False,
            reason=f"Daily drawdown {dd_pct:.2%} within limit {DAILY_DRAWDOWN_LIMIT:.0%}",
            data={"daily_dd_pct": round(dd_pct, 6)},
        )

    # ------------------------------------------------------------------
    # Kill Switch 2 — Consecutive Losses
    # ------------------------------------------------------------------

    def record_trade_result(self, pnl: float) -> BreakerResult:
        """
        Record a completed trade P&L and check the consecutive-loss limit.

        pnl <= 0 increments the streak; pnl > 0 resets it to zero.

        Returns PASS (streak below limit) or kill-switch (limit reached).
        Callers must check the return value before allowing further orders.
        """
        if self._state == BreakerState.HALTED:
            return self._already_halted()

        if pnl > 0:
            old = self._consecutive_losses
            self._consecutive_losses = 0
            logger.info("Trade WIN pnl=%.2f — loss streak reset (was %d)", pnl, old)
            return BreakerResult(
                passed=True, kill_switch=False,
                reason=f"Winning trade — streak reset (was {old})",
                data={"pnl": pnl, "consecutive_losses": 0},
            )

        # Loss or break-even
        self._consecutive_losses += 1
        logger.info(
            "Trade LOSS pnl=%.2f — consecutive losses now %d/%d",
            pnl, self._consecutive_losses, CONSECUTIVE_LOSS_LIMIT,
        )

        if self._consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
            msg = (
                f"{self._consecutive_losses} consecutive losing trades "
                f"reached limit ({CONSECUTIVE_LOSS_LIMIT}) — kill switch activated"
            )
            return self._arm(TriggerReason.CONSECUTIVE_LOSSES, msg, {
                "consecutive_losses": self._consecutive_losses,
                "last_pnl": pnl,
            })

        remaining = CONSECUTIVE_LOSS_LIMIT - self._consecutive_losses
        return BreakerResult(
            passed=True, kill_switch=False,
            reason=(
                f"{self._consecutive_losses}/{CONSECUTIVE_LOSS_LIMIT} "
                f"consecutive losses — {remaining} until halt"
            ),
            data={
                "consecutive_losses": self._consecutive_losses,
                "remaining_until_halt": remaining,
            },
        )

    # ------------------------------------------------------------------
    # Kill Switch 3 — MOC Imbalance (position-level)
    # ------------------------------------------------------------------

    def check_moc_imbalance(
        self,
        ticker: str,
        sell_imbalance_shares: float,
        adv_20: float,
    ) -> BreakerResult:
        """
        Check whether a MOC sell imbalance warrants emergency exit at 3:50 PM.

        POSITION-LEVEL trigger: does NOT arm the account-level kill switch.
        Returns kill_switch=True to signal the router to close this specific
        position; other positions and new signals remain unaffected.

        Parameters
        ----------
        ticker                : stock symbol (for logging)
        sell_imbalance_shares : shares on the sell side of the MOC book
        adv_20                : 20-day average daily volume (shares)
        """
        if adv_20 <= 0:
            logger.warning(
                "check_moc_imbalance %s: invalid adv_20=%s — check skipped",
                ticker, adv_20,
            )
            return BreakerResult(
                passed=True, kill_switch=False,
                reason=f"{ticker}: invalid ADV — MOC check skipped",
            )

        frac = sell_imbalance_shares / adv_20
        logger.debug(
            "MOC imbalance %s: sell=%,.0f ADV=%,.0f frac=%.2f%% (limit=%.0f%%)",
            ticker, sell_imbalance_shares, adv_20,
            frac * 100, MOC_IMBALANCE_FRACTION * 100,
        )

        if frac > MOC_IMBALANCE_FRACTION:
            msg = (
                f"{ticker}: MOC sell imbalance {frac:.1%} of ADV "
                f"exceeds {MOC_IMBALANCE_FRACTION:.0%} — emergency exit"
            )
            logger.warning("WARNING: %s", msg)
            # Position-level kill: do NOT change self._state
            return BreakerResult(
                passed=False, kill_switch=True,
                reason=msg,
                data={
                    "ticker": ticker,
                    "sell_imbalance_shares": sell_imbalance_shares,
                    "adv_20": adv_20,
                    "imbalance_frac": round(frac, 4),
                    "trigger": TriggerReason.MOC_IMBALANCE.value,
                },
            )

        return BreakerResult(
            passed=True, kill_switch=False,
            reason=f"{ticker}: MOC imbalance {frac:.1%} — within threshold",
            data={"ticker": ticker, "imbalance_frac": round(frac, 4)},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _arm(
        self,
        reason: TriggerReason,
        message: str,
        data: dict,
    ) -> BreakerResult:
        """Arm the account-level kill switch."""
        self._state = BreakerState.HALTED
        self._trigger_reason = reason
        logger.critical("KILL SWITCH -- %s | %s", reason.value, message)
        return BreakerResult(
            passed=False, kill_switch=True,
            reason=message,
            data={**data, "trigger": reason.value, "session_date": str(self._session_date)},
        )

    def _already_halted(self) -> BreakerResult:
        trigger = self._trigger_reason.value if self._trigger_reason else "UNKNOWN"
        return BreakerResult(
            passed=False, kill_switch=True,
            reason=f"Trading already halted (trigger={trigger})",
            data={"trigger": trigger},
        )
