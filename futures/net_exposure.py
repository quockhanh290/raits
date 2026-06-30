"""
futures/net_exposure.py — combined net-exposure cap (both engines, 4 indices)
=============================================================================
Self-contained (imports only futures.basket). The 4 indices are ~0.9 correlated
and BOTH engines (swing TF + STRESS_MID) can fire the same day. If swing TF is
long all 4 AND STRESS_MID is short ES, naive per-trade sizing understates the
true concentrated bet. This guard treats correlated same-direction risk as
ADDITIVE and caps total net directional dollar-risk.

Why additive (not diversified): at corr ~0.9, four long index positions move
together → they are ~one big bet, not four independent ones. So we sum the
dollar-risk on each side and cap the NET (long − short) and the GROSS one-side.

Risk unit = $ at risk per position = contracts × stop_distance_points × point_value
(falls back to 1% account if stop distance unknown at check time).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from futures.basket import BASKET, RISK


@dataclass
class Position:
    instrument: str
    direction: str        # "LONG" | "SHORT"
    contracts: int
    risk_dollars: float   # $ at risk (contracts × stop_dist × point_value)
    engine: str           # "swing_tf" | "stress_mid"


@dataclass
class NetExposureGuard:
    # swing TF budget (4 correlated indices) — net + gross caps
    max_gross_one_side_pct: float = 0.04   # total $-risk on the heavier side (swing TF)
    max_net_pct: float = 0.035             # |long$ − short$| net directional (swing TF)
    # STRESS_MID sleeve has its OWN budget (small, tight stops, intentional bear hedge)
    # — NOT counted against swing TF, so it is never crowded out when both go short.
    max_stress_gross_pct: float = 0.025    # ~5 micro stress positions at 1% each
    account: float = field(default_factory=lambda: RISK["account"])

    def _sums(self, positions):
        long_r = sum(p.risk_dollars for p in positions if p.direction == "LONG")
        short_r = sum(p.risk_dollars for p in positions if p.direction == "SHORT")
        return long_r, short_r

    def state(self, positions):
        swing = [p for p in positions if p.engine != "stress_mid"]
        stress = [p for p in positions if p.engine == "stress_mid"]
        long_r, short_r = self._sums(swing)
        gross_one_side = max(long_r, short_r)
        net = abs(long_r - short_r)
        stress_gross = sum(p.risk_dollars for p in stress)
        return dict(long=long_r, short=short_r,
                    gross_one_side=gross_one_side, net=net,
                    gross_pct=gross_one_side / self.account,
                    net_pct=net / self.account,
                    stress_gross=stress_gross,
                    stress_gross_pct=stress_gross / self.account)

    def admits(self, proposed: Position, open_positions) -> tuple[bool, str]:
        """Engine-aware: STRESS_MID checked against its own sleeve budget; swing TF
        against the net/gross caps. The two budgets are independent."""
        book = list(open_positions) + [proposed]
        if proposed.engine == "stress_mid":
            stress_gross = sum(p.risk_dollars for p in book if p.engine == "stress_mid")
            if stress_gross / self.account > self.max_stress_gross_pct:
                return False, (f"stress sleeve gross {stress_gross/self.account:.1%} > "
                               f"cap {self.max_stress_gross_pct:.1%}")
            return True, "ok"
        # swing TF
        s = self.state(book)
        if s["gross_pct"] > self.max_gross_one_side_pct:
            return False, (f"swing gross one-side {s['gross_pct']:.1%} > "
                           f"cap {self.max_gross_one_side_pct:.1%}")
        if s["net_pct"] > self.max_net_pct:
            return False, f"swing net {s['net_pct']:.1%} > cap {self.max_net_pct:.1%}"
        return True, "ok"

    def filter_entries(self, proposed_list, open_positions):
        """Greedily admit proposed entries in order; reject those that breach caps.
        Returns (admitted, rejected_with_reason)."""
        book = list(open_positions)
        admitted, rejected = [], []
        for p in proposed_list:
            ok, why = self.admits(p, book)
            if ok:
                admitted.append(p); book.append(p)
            else:
                rejected.append((p, why))
        return admitted, rejected


if __name__ == "__main__":
    # illustration: 1% risk = $500/position on $50k. swing TF long all 4 + stress short ES.
    g = NetExposureGuard()
    book = []
    proposed = [Position(n, "LONG", 1, 500, "swing_tf") for n in BASKET] + \
               [Position("MES", "SHORT", 1, 500, "stress_mid")]
    adm, rej = g.filter_entries(proposed, book)
    print(f"admitted {len(adm)}: {[(p.instrument,p.direction) for p in adm]}")
    for p, why in rej:
        print(f"  rejected {p.instrument} {p.direction} ({p.engine}): {why}")
    print(g.state(adm))
