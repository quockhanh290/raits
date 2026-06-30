"""
nonequity/specs.py — non-equity contract specs (the ONE source of pv/tick)
==========================================================================
The `Contract` SCHEMA is copied from futures/basket.py (NOT imported) so an
equity index pv/tick can never leak in (that mistake = the M2K tick bug).

point_value / tick are EXCHANGE specs (stable) — verified against CME contract
spec pages. est_margin and commission are ESTIMATES — CONFIRM with IBKR before
sizing (they move with volatility and vary by tier).

Data note: fetch the standard front-month (GC.c.0 / CL.c.0) for liquid, clean
continuous data. For DEPLOY sizing on a $50k account use the MICRO (MGC/MCL) —
same underlying price series, smaller point_value. Backtest with whichever
point_value matches the instrument you will actually trade.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    name: str            # exchange symbol (full or micro)
    data_symbol: str     # root for the continuous front-month (parquet / Databento)
    point_value: float   # $ per 1.00 price move
    tick: float          # price units per tick
    est_margin: float    # ESTIMATE overnight margin $ — CONFIRM with IBKR
    commission_rt: float # ESTIMATE all-in round-turn $ — CONFIRM with IBKR
    note: str = ""

    @property
    def tick_value(self) -> float:
        return self.tick * self.point_value


# ── verified CME specs ──────────────────────────────────────────────────────
# Gold (COMEX). 1.00 = $1/oz move. GC tick 0.10 = $10; MGC tick 0.10 = $1.
GC  = Contract("GC",  "GC", point_value=100.0, tick=0.10, est_margin=11000, commission_rt=3.00,
               note="COMEX 100oz. Full contract — clean liquid data for backtest.")
MGC = Contract("MGC", "GC", point_value=10.0,  tick=0.10, est_margin=1100,  commission_rt=1.24,
               note="COMEX 10oz micro. DEPLOY instrument; same price series as GC.")

# Crude WTI (NYMEX). 1.00 = $1/bbl move. CL tick 0.01 = $10; MCL tick 0.01 = $1.
# WARNING: CL settled NEGATIVE on 2020-04-20 (-$37). See fetch.py negative-price
# guard; consider --start 2020-05-01 for CL until that boundary is handled.
CL  = Contract("CL",  "CL", point_value=1000.0, tick=0.01, est_margin=6000, commission_rt=3.00,
               note="NYMEX 1000bbl. 2020-04-20 negative settle — handle before trusting.")
MCL = Contract("MCL", "CL", point_value=100.0,  tick=0.01, est_margin=600,  commission_rt=1.24,
               note="NYMEX 100bbl micro. DEPLOY instrument; same price series as CL.")

# Registry for the first discovery round (metals + energy = two real factors).
SPECS = {"GC": GC, "MGC": MGC, "CL": CL, "MCL": MCL}


def summary() -> str:
    lines = ["non-equity specs (verify margin/commission with IBKR):"]
    for k, c in SPECS.items():
        lines.append(f"  {k:<4} pv=${c.point_value:<7} tick={c.tick:<5} "
                     f"tick_val=${c.tick_value:<6} est_margin=${c.est_margin}  {c.note}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
