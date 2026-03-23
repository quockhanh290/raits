"""
raits/coordinator/conflict_resolver.py
----------------------------------------
Signal priority, position limits, and same-stock deduplication.

Blueprint reference: Section 4.6 (Multi-Strategy Integration & Conflict Resolution)
Requirement level:  SHALL

Rules (applied in order):
    1. Safety Mode  — if system state is not ACTIVE, reject all signals.
    2. Duplicate    — never hold two positions in the same ticker.
    3. Limits       — per-strategy and global position caps.
    4. Priority     — when multiple strategies fire on the same ticker,
                      TREND_FOLLOW > ORB > VWAP_MR wins.

Position limits (Blueprint §4.1):
    ORB:          max 2 concurrent
    VWAP_MR:      max 3 concurrent
    TREND_FOLLOW: max 2 concurrent
    TOTAL:        max 5 across all strategies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger("RAITS.coordinator.conflict")

# ---------------------------------------------------------------------------
# Constants — position caps
# ---------------------------------------------------------------------------

MAX_POSITIONS: dict[str, int] = {
    "ORB":          2,
    "VWAP_MR":      3,
    "TREND_FOLLOW": 2,
    "TOTAL":        5,
}


# ---------------------------------------------------------------------------
# Signal priority (lower int = higher priority)
# ---------------------------------------------------------------------------

class SignalPriority(IntEnum):
    """
    Priority ordering for conflict resolution.
    Lower value = evaluated first = wins when multiple strategies fire.
    """
    TREND_FOLLOW = 1
    ORB          = 2
    VWAP_MR      = 3


# ---------------------------------------------------------------------------
# ConflictResolver
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedSignal:
    """Output of ConflictResolver.resolve() when a signal is accepted."""
    strategy: str           # "ORB" | "VWAP_MR" | "TREND_FOLLOW"
    ticker: str
    signal: dict            # raw signal dict from the strategy engine
    reason: str             # why this signal was chosen


class ConflictResolver:
    """
    Applies position limits and priority rules to a batch of candidate signals.

    Usage
    -----
    resolver = ConflictResolver()

    # Each bar, after strategy engines have generated their signals:
    candidates = {
        "ORB":    {"AAPL": {...signal...}, "TSLA": {...signal...}},
        "VWAP_MR": {"MSFT": {...signal...}},
    }
    open_tickers   = {"NVDA", "GOOG"}   # currently held positions (any strategy)
    positions_by_strategy = {"ORB": 1, "VWAP_MR": 0, "TREND_FOLLOW": 2}

    accepted = resolver.resolve(candidates, open_tickers, positions_by_strategy)
    # → list[ResolvedSignal], one per ticker accepted this bar
    """

    def resolve(
        self,
        candidates: dict[str, dict[str, dict]],
        open_tickers: set[str],
        positions_by_strategy: dict[str, int],
    ) -> list[ResolvedSignal]:
        """
        Filter and prioritise candidate signals.

        Parameters
        ----------
        candidates : {strategy_name: {ticker: signal_dict}}
            Raw signals from strategy engines this bar.
            A strategy that produced no signals should be absent or empty.

        open_tickers : set[str]
            Tickers currently held (across all strategies).
            No new signal for these tickers will be accepted.

        positions_by_strategy : {strategy_name: current_count}
            Number of open positions per strategy right now.
            Missing strategies are treated as 0.

        Returns
        -------
        list[ResolvedSignal]
            Zero or more accepted signals, highest-priority first.
            Multiple signals may be accepted in one bar (different tickers).
        """
        accepted: list[ResolvedSignal] = []
        total_open = sum(positions_by_strategy.get(s, 0)
                         for s in MAX_POSITIONS if s != "TOTAL")

        # Flatten all candidates into (priority, strategy, ticker, signal)
        # so we evaluate highest-priority signals first across all strategies.
        flat: list[tuple[int, str, str, dict]] = []
        for strategy, signals in candidates.items():
            prio = self._priority(strategy)
            for ticker, signal in signals.items():
                flat.append((prio, strategy, ticker, signal))

        # Sort: lowest prio int = highest priority = first
        flat.sort(key=lambda x: x[0])

        # Track what we've accepted THIS bar (for intra-bar dedup)
        accepted_tickers: set[str] = set()
        accepted_strategy_counts: dict[str, int] = dict(positions_by_strategy)

        for prio, strategy, ticker, signal in flat:

            # ── Rule 1: Duplicate ticker ─────────────────────────────────────
            if ticker in open_tickers or ticker in accepted_tickers:
                logger.debug(
                    "SKIP %s/%s: already have position in %s",
                    strategy, ticker, ticker,
                )
                continue

            # ── Rule 2: Global position cap ──────────────────────────────────
            current_total = (total_open
                             + sum(v - positions_by_strategy.get(k, 0)
                                   for k, v in accepted_strategy_counts.items()))
            # Simpler: track running total
            intra_bar_total = sum(
                accepted_strategy_counts.get(s, 0) - positions_by_strategy.get(s, 0)
                for s in MAX_POSITIONS if s != "TOTAL"
            )
            projected_total = total_open + intra_bar_total

            if projected_total >= MAX_POSITIONS["TOTAL"]:
                logger.debug(
                    "SKIP %s/%s: global position cap %d reached",
                    strategy, ticker, MAX_POSITIONS["TOTAL"],
                )
                continue

            # ── Rule 3: Per-strategy position cap ───────────────────────────
            strategy_limit = MAX_POSITIONS.get(strategy)
            if strategy_limit is not None:
                current_for_strategy = accepted_strategy_counts.get(strategy, 0)
                if current_for_strategy >= strategy_limit:
                    logger.debug(
                        "SKIP %s/%s: strategy cap %d reached",
                        strategy, ticker, strategy_limit,
                    )
                    continue

            # ── Accepted ─────────────────────────────────────────────────────
            accepted.append(ResolvedSignal(
                strategy=strategy,
                ticker=ticker,
                signal=signal,
                reason=f"{strategy} priority={prio}; {projected_total+1}/{MAX_POSITIONS['TOTAL']} positions",
            ))
            accepted_tickers.add(ticker)
            accepted_strategy_counts[strategy] = accepted_strategy_counts.get(strategy, 0) + 1

            logger.info(
                "ACCEPTED %s/%s: %s | total=%d/%d strategy=%d/%d",
                strategy, ticker, signal.get("direction", "?"),
                projected_total + 1, MAX_POSITIONS["TOTAL"],
                accepted_strategy_counts[strategy],
                MAX_POSITIONS.get(strategy, 99),
            )

        return accepted

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _priority(strategy: str) -> int:
        """Return numeric priority for a strategy name. Lower = higher priority."""
        mapping = {
            "TREND_FOLLOW": SignalPriority.TREND_FOLLOW,
            "ORB":          SignalPriority.ORB,
            "VWAP_MR":      SignalPriority.VWAP_MR,
        }
        return int(mapping.get(strategy, 99))

    @staticmethod
    def check_position_limits(
        strategy: str,
        positions_by_strategy: dict[str, int],
        total_open: int,
    ) -> tuple[bool, str]:
        """
        Standalone limit check for a single strategy (used by router directly).

        Returns (allowed: bool, reason: str).
        """
        strategy_limit = MAX_POSITIONS.get(strategy)
        if strategy_limit is not None:
            current = positions_by_strategy.get(strategy, 0)
            if current >= strategy_limit:
                return False, f"{strategy} cap reached ({current}/{strategy_limit})"

        if total_open >= MAX_POSITIONS["TOTAL"]:
            return False, f"Global cap reached ({total_open}/{MAX_POSITIONS['TOTAL']})"

        return True, "ok"
