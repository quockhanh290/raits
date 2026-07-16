"""
global_index/hmm_stale_guard.py — HMM staleness guards (G1 + G2) for futures
=============================================================================
Consistent with stocks HMM_LEVEL2_PROTECTION (raits/live/context_feed.py +
raits/live/runner.py entries_blocked_regime_unreliable pattern).

G1: SPY CSV stale — regime gate wrong, all 3 clusters affected.
    Tighter thresholds than stocks (2/5 vs 5/10) because the futures regime
    gate controls the STRESS_MID hedge — staleness is more operationally critical.
    SOFT >2 bday : notify WARN once on transition; trade continues
    HARD >5 bday : regime_unreliable=True → BLOCK new entries, KEEP exits; notify
    Recovery ≤2 bday (when was hard-stale): clear flag; notify RESUMED
    Anti-oscillation: recovery threshold == soft, which is < hard.

G2: Model age — fit_end too old. Warn only (no halt) because an old model still
    decodes regime correctly for recent data — accuracy degrades gradually, unlike
    a stale CSV which causes an immediate wrong-regime error.
    SOFT >12 months: notify MODEL AGE WARN once
    HARD >18 months: notify MODEL AGE URGENT once

G3: Re-freeze data coverage — futures/refreeze.py (not here).

Wire into FuturesRunner:
    stale_guard = HMMStaleGuard(regime_csv="spy_daily_live.csv", fit_end="2024-12-31")
    runner = FuturesRunner(..., hmm_stale_guard=stale_guard)

runner.run_day() calls stale_guard.check_day(day) each day. If regime_unreliable,
the runner clears entry_candidates before decide_day — exits run normally.

For offline testing, pass spy_last_date_override to check_day() to skip CSV read.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from global_index.notify import notify

log = logging.getLogger(__name__)

# ── G1 thresholds (futures — tighter than stocks 5/10) ────────────────────────
G1_SOFT_BDAYS     = 2   # >2 bday → WARN; trade continues
G1_HARD_BDAYS     = 5   # >5 bday → halt entries
G1_RECOVERY_BDAYS = 2   # must recover to ≤2 to clear hard halt (== soft)

# ── G2 thresholds ─────────────────────────────────────────────────────────────
G2_SOFT_MONTHS = 12
G2_HARD_MONTHS = 18


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spy_gap_bdays(spy_last_date: pd.Timestamp, today: pd.Timestamp) -> int:
    """Business-day gap between spy_last_date and today.
    Returns 0 when spy_last_date is null or >= today.
    Mirror of raits/live/context_feed._spy_gap_bdays.
    """
    if spy_last_date is None or pd.isna(spy_last_date):
        return 0
    last = pd.Timestamp(spy_last_date).normalize()
    cur  = pd.Timestamp(today).normalize()
    if cur <= last:
        return 0
    return max(0, len(pd.bdate_range(last, cur)) - 1)


def _read_spy_last_date(csv_path: Path) -> pd.Timestamp:
    """Read last date from spy regime CSV (expects 'date' column)."""
    df = pd.read_csv(csv_path, usecols=["date"])
    return pd.Timestamp(df["date"].max())


def _months_since(ts: pd.Timestamp, today: pd.Timestamp) -> int:
    """Whole calendar months elapsed since ts (0 if same month, clamped ≥ 0)."""
    return max(0, (today.year - ts.year) * 12 + (today.month - ts.month))


# ── Guard ─────────────────────────────────────────────────────────────────────

class HMMStaleGuard:
    """
    Per-day HMM staleness checker. Passed to FuturesRunner at construction.

    State transitions:
        G1 fresh → G1 soft-stale : notify WARN once
        G1 soft  → G1 hard-stale : notify HALTED once (regime_unreliable=True)
        G1 hard  → G1 recovered  : notify RESUMED (regime_unreliable=False)
        G2 fresh → G2 soft       : notify MODEL AGE WARN once
        G2 soft  → G2 hard       : notify MODEL AGE URGENT once
    """

    def __init__(self, regime_csv, fit_end: str):
        """
        regime_csv : path to spy_daily CSV (production — read to get last date).
        fit_end    : HMM fit-end date string, e.g. "2024-12-31" (G2 age check).
        """
        self.regime_csv = Path(regime_csv)
        self.fit_end    = pd.Timestamp(fit_end)

        # G1 live state
        self.regime_unreliable: bool = False
        self.entries_blocked:   int  = 0
        self._g1_soft_active:   bool = False   # True while gap > SOFT

        # G2 — emit each level once
        self._g2_soft_notified: bool = False
        self._g2_hard_notified: bool = False

    # ── Public ────────────────────────────────────────────────────────────────

    def check_day(self, today: pd.Timestamp,
                  spy_last_date_override: "pd.Timestamp | None" = None) -> bool:
        """
        Run G1 + G2 checks for today.
        Returns True if new entries are allowed (regime_unreliable is False).

        spy_last_date_override: inject last CSV date directly (for offline tests).
        When None, reads self.regime_csv from disk.
        """
        if spy_last_date_override is not None:
            spy_last = pd.Timestamp(spy_last_date_override)
        else:
            spy_last = _read_spy_last_date(self.regime_csv)
        self._check_g1(today, spy_last)
        self._check_g2(today)
        return not self.regime_unreliable

    # ── G1 ────────────────────────────────────────────────────────────────────

    def _check_g1(self, today: pd.Timestamp, spy_last: pd.Timestamp) -> None:
        gap = _spy_gap_bdays(spy_last, today)

        if gap > G1_HARD_BDAYS:
            if not self.regime_unreliable:
                notify(
                    "TRADING HALTED",
                    f"SPY regime CSV STALE {gap} business days "
                    f"(last={spy_last.date()}, today={today.date()}). "
                    f"New futures entries BLOCKED. Update spy_daily.csv to resume.",
                )
                log.error(
                    "G1 HARD-STALE: gap=%d bday spy_last=%s today=%s — entries halted",
                    gap, spy_last.date(), today.date(),
                )
            self.regime_unreliable = True
            self._g1_soft_active   = True

        elif gap > G1_SOFT_BDAYS:
            if not self._g1_soft_active:
                notify(
                    "REGIME WARN",
                    f"SPY regime CSV is {gap} business days old "
                    f"(last={spy_last.date()}, today={today.date()}). "
                    f"Regime labels slightly stale — futures trading continues.",
                )
                log.warning(
                    "G1 SOFT-STALE: gap=%d bday spy_last=%s today=%s",
                    gap, spy_last.date(), today.date(),
                )
                self._g1_soft_active = True

        elif self.regime_unreliable and gap <= G1_RECOVERY_BDAYS:
            notify(
                "TRADING RESUMED",
                f"SPY regime CSV fresh ({gap} bday gap, last={spy_last.date()}). "
                f"Entry halt cleared — normal futures trading resumes.",
            )
            log.info("G1 RECOVERED: gap=%d bday — regime_unreliable cleared", gap)
            self.regime_unreliable = False
            self._g1_soft_active   = False

        else:
            if self._g1_soft_active and not self.regime_unreliable:
                self._g1_soft_active = False

    # ── G2 ────────────────────────────────────────────────────────────────────

    def _check_g2(self, today: pd.Timestamp) -> None:
        months = _months_since(self.fit_end, today)

        if months > G2_HARD_MONTHS and not self._g2_hard_notified:
            notify(
                "MODEL AGE URGENT",
                f"HMM model is {months} months old "
                f"(fit_end={self.fit_end.date()}, today={today.date()}). "
                f"Schedule re-freeze immediately (futures/refreeze.py). "
                f"Trading continues but model accuracy degrades.",
            )
            log.error(
                "G2 HARD: model %d months old (fit_end=%s) — re-freeze immediately",
                months, self.fit_end.date(),
            )
            self._g2_hard_notified = True

        elif months > G2_SOFT_MONTHS and not self._g2_soft_notified:
            notify(
                "MODEL AGE WARN",
                f"HMM model is {months} months old "
                f"(fit_end={self.fit_end.date()}, today={today.date()}). "
                f"Plan annual re-freeze (futures/refreeze.py). Trading continues.",
            )
            log.warning(
                "G2 SOFT: model %d months old (fit_end=%s) — plan re-freeze",
                months, self.fit_end.date(),
            )
            self._g2_soft_notified = True
