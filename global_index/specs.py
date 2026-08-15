"""
global_index/specs.py — foreign equity-index contract specs (the ONE source of pv/tick)
========================================================================================
Equity indices listed abroad. point_value/tick are exchange specs (verified CME);
est_margin/commission are ESTIMATES — CONFIRM with IBKR. `session_tz` is the local
exchange timezone so the validated 14:00-15:55 power-hour window lands on the local
cash power hour after tz-convert.

Schema copied from futures/basket.py (NOT imported) — never leak Rổ-4 pv/tick here.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Contract:
    """One instrument, carrying all three names it is known by.

    A contract has three identities and they are not the same string:

      name         what this system calls it, everywhere internally
      data_symbol  what the historical data is filed under
      ibkr_symbol  what IBKR must be asked for to get this contract

    They used to be two. MNKD carried name="MNKD" and data_symbol="NKD" (correct --
    the backtest legitimately uses full-size NKD history, which starts in 2018 while
    micro data starts in 2024 Q4), and the broker layer was left to guess the third.
    It guessed data_symbol, so live orders for the $0.50 micro were routed to the $5
    full-size contract and ran at ten times the intended size for four days before
    anyone noticed. Making the third identity a required field is what stops the
    broker layer from ever having to infer it again.
    """
    name: str
    data_symbol: str
    ibkr_symbol: str
    point_value: float
    tick: float
    est_margin: float
    commission_rt: float
    session_tz: str            # local exchange tz for the power-hour window
    note: str = ""

    @property
    def tick_value(self) -> float:
        return self.tick * self.point_value

    @property
    def ibkr(self) -> str:
        """The symbol to put on an IBKR order. Never guess between the other two."""
        return self.ibkr_symbol or self.name


# ── Nikkei 225 (CME, GLBX) — verified CME specs ─────────────────────────────
# Min fluctuation 5 index points. NKD pv $5/pt → tick $25; Micro USD pv $0.50 → $2.50.
NKD  = Contract("NKD",  "NKD", "NKD", point_value=5.0, tick=5.0, est_margin=9000, commission_rt=2.50,
                session_tz="Asia/Tokyo",
                note="CME Nikkei USD. Full — liquid backtest data. tick=$25. Not deployed.")
MNKD = Contract("MNKD", "NKD", "MNK", point_value=0.5, tick=5.0, est_margin=900, commission_rt=1.40,
                session_tz="Asia/Tokyo",
                note="CME Micro Nikkei USD. DEPLOY; same series as NKD, data_symbol NKD on "
                     "purpose. IBKR ticker MNK confirmed via reqContractDetails 2026-08-14: "
                     "conId 811230944, MNKU6, multiplier 0.5. NKD returns multiplier 5.")

# ── DAX (Eurex, XEUR) — placeholder; Databento history only from 2025-03-10 ──
# Not usable for Rổ-4-style WFO yet (too short). pv FDAX €25/pt (tick 1.0 → €25),
# FDXM mini €5/pt. session_tz Europe/Berlin. Add when a long-history source exists.

SPECS = {"NKD": NKD, "MNKD": MNKD}


def summary() -> str:
    lines = ["global-index specs (verify margin/commission with IBKR):"]
    for k, c in SPECS.items():
        lines.append(f"  {k:<4} ibkr={c.ibkr_symbol:<4} data={c.data_symbol:<4} "
                     f"pv=${c.point_value:<5} tick={c.tick:<4} tick_val=${c.tick_value:<5} "
                     f"tz={c.session_tz:<12} {c.note}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
