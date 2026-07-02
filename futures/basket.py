"""
futures/basket.py — the deployable basket (RỔ 4) + contract specs
=================================================================
Self-contained config for the validated swing-TF engine. Rổ 4 = MES/MNQ/MYM/M2K
(micro E-mini S&P / Nasdaq / Dow / Russell). Chosen over ES+NQ: higher WFO Calmar
(2.29 vs 2.21), 2× the trades, 6/6 positive folds, all 4 instruments positive
under correct gap-fill. Frozen param from pooled WFO: ema=30, chandelier_mult=2.5.

Margins are ESTIMATES — confirm with IBKR before sizing (they vary by broker and
move with volatility). point_value / tick are exchange specs (stable).
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Contract:
    name: str            # micro symbol
    data_symbol: str     # root used in the parquet filenames (continuous front-month)
    point_value: float   # $ per index point
    tick: float          # index points per tick
    est_margin: float    # ESTIMATE day/overnight margin $ — CONFIRM with IBKR

    @property
    def tick_value(self) -> float:
        return self.tick * self.point_value


# ── RỔ 4 — the deployed basket ────────────────────────────────────────────────
BASKET = {
    "MES": Contract("MES", "ES", point_value=5.0,  tick=0.25, est_margin=1400),
    "MNQ": Contract("MNQ", "NQ", point_value=2.0,  tick=0.25, est_margin=2200),
    "MYM": Contract("MYM", "YM", point_value=0.5,  tick=1.0,  est_margin=900),
    "M2K": Contract("M2K", "RTY", point_value=5.0, tick=0.10, est_margin=800),
}

# ── frozen strategy param (pooled WFO winner, 5/6 folds) ──────────────────────
SWING_TF_PARAM = {"ema_period": 30, "chandelier_atr_mult": 2.5, "max_hold_days": 5}

# ── regime config (must match the validated path) ─────────────────────────────
REGIME = {
    "source": "SPY",              # instrument-agnostic; SPY daily closes
    "n_components": 3,            # Calm / Normal / Stress
    "hmm_fit_end": "2024-12-31",  # fit on diverse window incl. stress; never on vault
    "allowed_regimes": {"Normal", "Stress"},  # swing TF trades these (not Calm)
}

# ── portfolio risk (locked decisions) ─────────────────────────────────────────
RISK = {
    "max_drawdown_pct": 0.15,     # HARD cap on COMBINED portfolio (both engines)
    "target_drawdown_pct": 0.10,  # size to this; buffer for live overrun
    "account": 50_000,
    "risk_per_trade_pct": 0.01,   # 1% = $500 risk per entry (pre net-exposure cap)
}


def data_filename(c: Contract) -> str:
    """Parquet filename for a contract's continuous series."""
    return f"{c.data_symbol}_continuous_1m_8y.parquet"


def summary() -> str:
    lines = ["RỔ 4 basket (swing-TF engine):"]
    for k, c in BASKET.items():
        lines.append(f"  {k:<4} pv=${c.point_value:<4} tick={c.tick:<5} "
                     f"tick_val=${c.tick_value:<5} est_margin=${c.est_margin}")
    lines.append(f"  param: ema={SWING_TF_PARAM['ema_period']}, "
                 f"mult={SWING_TF_PARAM['chandelier_atr_mult']}, "
                 f"hold={SWING_TF_PARAM['max_hold_days']}d")
    lines.append(f"  total est margin (1 micro each): "
                 f"${sum(c.est_margin for c in BASKET.values()):,}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
