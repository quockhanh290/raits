"""
futures/circuit_breaker.py — combined-portfolio drawdown circuit breaker
========================================================================
Self-contained (imports only futures.basket). Tracks the COMBINED portfolio
equity (both engines, all instruments) and halts NEW entries when drawdown from
peak crosses thresholds. This is the "brake" the validated backtest never had
(backtest runs forever regardless of losses).

Three layers (escalating):
  WARN  at target DD (10%)  → log + flag; reduce new size (caller may halve).
  HALT  at hard DD  (15%)   → no new entries; manage/exit open positions only.
  DAILY loss stop           → optional intraday loss cap (no new entries today).

State is explicit (peak_equity, current_equity) so it can be persisted/restored
across runner restarts. Halt is on NEW entries; it never forces-closes (exits
follow the strategy's own stops) unless the caller opts in.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from futures.basket import RISK


@dataclass
class CircuitBreaker:
    account: float = field(default_factory=lambda: RISK["account"])
    target_dd_pct: float = field(default_factory=lambda: RISK["target_drawdown_pct"])  # 0.10
    hard_dd_pct: float = field(default_factory=lambda: RISK["max_drawdown_pct"])        # 0.15
    daily_loss_pct: float = 0.04          # no new entries after −4% in a day
    peak_equity: float = field(default=None)
    _day_start_equity: float = field(default=None)

    def __post_init__(self):
        if self.peak_equity is None:
            self.peak_equity = self.account

    # ── update on each equity mark ────────────────────────────────────────────
    def update(self, current_equity: float):
        self.peak_equity = max(self.peak_equity, current_equity)
        if self._day_start_equity is None:
            self._day_start_equity = current_equity

    def start_day(self, current_equity: float):
        self._day_start_equity = current_equity

    # ── status ────────────────────────────────────────────────────────────────
    def drawdown_pct(self, current_equity: float) -> float:
        return (self.peak_equity - current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0

    def daily_loss_pct_now(self, current_equity: float) -> float:
        if not self._day_start_equity:
            return 0.0
        return (self._day_start_equity - current_equity) / self._day_start_equity

    def status(self, current_equity: float) -> dict:
        dd = self.drawdown_pct(current_equity)
        dl = self.daily_loss_pct_now(current_equity)
        if dd >= self.hard_dd_pct:
            level = "HALT"
        elif dl >= self.daily_loss_pct:
            level = "HALT_DAY"
        elif dd >= self.target_dd_pct:
            level = "WARN"
        else:
            level = "OK"
        return dict(level=level, drawdown_pct=dd, daily_loss_pct=dl,
                    allow_new_entries=level in ("OK", "WARN"),
                    size_multiplier=0.5 if level == "WARN" else 1.0)

    def allow_new_entries(self, current_equity: float) -> bool:
        return self.status(current_equity)["allow_new_entries"]


if __name__ == "__main__":
    cb = CircuitBreaker()
    cb.start_day(50_000)
    for eq in (50_000, 52_000, 48_000, 46_800, 44_200):  # peak 52k then drawdown
        cb.update(eq)
        s = cb.status(eq)
        print(f"equity ${eq:,}: {s['level']:<8} dd={s['drawdown_pct']:.1%} "
              f"new_entries={s['allow_new_entries']} size×{s['size_multiplier']}")
