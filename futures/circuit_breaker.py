"""
futures/circuit_breaker.py — combined-portfolio drawdown circuit breaker
========================================================================
Self-contained (imports only futures.basket). Tracks the COMBINED portfolio
equity (both engines, all instruments) and halts NEW entries when drawdown from
peak crosses thresholds. This is the "brake" the validated backtest never had
(backtest runs forever regardless of losses).

Two active protection layers (binary — full size or full stop, no gradual de-risk):
  HALT      at hard DD  (15%)   → no new entries; manage/exit open positions only.
  HALT_DAY  at daily loss (>4%) → no new entries today.

WARN layer (10% DD) — INTENTIONALLY NOT WIRED:
  status() returns level="WARN" and size_multiplier=0.5 at 10% DD, but the deploy
  path (decide_day / FuturesRunner) reads only allow_new_entries and ignores
  size_multiplier. This is a deliberate design decision: the system runs at full
  size until HALT, with no gradual de-risking in between. Wiring size_multiplier
  would change trade sizing and requires re-validating WFO and vault results.
  size_multiplier is a dead field by intent — do not wire without re-validation.

  Note: WARN is also nearly unreachable in practice. A same-day loss of 10% trips
  HALT_DAY (4% daily stop) before the WARN branch is evaluated, so WARN only
  surfaces through gradual multi-day accumulation where no single day loses > 4%.

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
