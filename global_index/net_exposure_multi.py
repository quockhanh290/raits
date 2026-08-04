"""
global_index/net_exposure_multi.py — N-cluster net-exposure guard
==================================================================
Generalizes futures/net_exposure.py (which is 2 budgets: swing-TF + STRESS sleeve)
to N CORRELATION CLUSTERS, each with its own independent budget. Adding NKD to the
Rổ-4 net cap would be wrong twice over:

  1. Correlation: NKD ~0.6-0.85 with Rổ 4 (not the ~0.9 the Rổ-4 cap assumes as
     additive). Lumping it in over-penalizes.
  2. Timezone: NKD's power hour (JST) leads Rổ 4's (ET) by ~13h, so the two
     almost never hold fresh positions at the same instant — combined.py measured
     cross-stream corr +0.225 (low). They are sequential, not simultaneous.

So NKD gets its OWN cluster budget: it is never crowded out by Rổ 4, and never
crowds Rổ 4 out — exactly the pattern STRESS_MID already uses.

CRITICAL — this caps EXPOSURE, not DRAWDOWN. The 15% drawdown cap stays at the
ACCOUNT level (circuit_breaker), combined across all clusters, because it is ONE
account and a global risk-off still draws every equity cluster down the same day
(timezone lag does not save you in a crash). fit_C 3-engine baseline MaxDD = $2,789
(deploy_sim; pre-NKD context was $5,185→$5,232 — stale, superseded by fit_C) —
so the account DD cap is not threatened — but that is empirical, not structural. Keep DD combined.

Cluster caps: roska4_swing (5%/4.4%) is the swept optimum. roska4_stress (2.5%)
remains an ESTIMATE — calibrate during paper trading.

global_nkd was 2%, an estimate anchored in DECISIONS.md to "1 MNKD ATR risk ≈ $437".
That figure is the 22.6th percentile of 2018-2026 risk_sized and was drawn from the
quietest stretch of the sample; by 2026 the Nikkei had risen from ~21,000 to ~64,000
and NKD's daily ATR with it, so 94.1% of days exceeded the $1,000 sleeve and the
cluster stopped trading altogether. Swept 2026-08-04 (scratchpad/sweep_nkd_cap.py,
NKD cap only, roska4_swing held at 5%/4.4%, account $50,000):

    cap    net$     Calmar  Sharpe  MaxDD$   swing t/r    nkd t/r
    2%     46,683   1.99    1.90    3,390    1799/697     655/46
    4%     48,091   2.05    1.90    3,390    1799/697     695/6
    6%     48,453   2.07    1.90    3,390    1799/697     701/0
    12%    48,453   2.07    1.90    3,390    1799/697     701/0

MaxDD is invariant across the whole sweep — NKD never participates in the worst
drawdown, which is the timezone-lag / +0.225 cross-correlation argument above
holding empirically. The 2% cap was suppressing trades and buying no protection.

6% is where the constraint stops binding (701/0, identical at 8% and 12%), not a
tuned optimum — there is no maximum to overfit to and no risk/return curve to ride.
The alternative was measured and rejected: with NKD dead the system is Rổ-4-only at
Calmar 1.15, BELOW the 1.53 degradation floor, and MaxDD is worse ($3,732 vs $3,390)
because the diversifier is gone. Raising the account base instead was also rejected
— $150,000 loosens every cluster at once, swing rejections collapse 697→8 and Calmar
falls to 1.40.

Caveats on the record: the sweep saturates at 6% on 2018-2024 data where NKD
risk_sized ran $350-900. At 2026 volatility it is ~$2,850, so 6% ($3,000) clears by
only ~5% and a further vol rise re-blocks the cluster. And the sweep window covers
the sealed 2023-2024 vault period, so this cap has no clean OOS.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Position:
    instrument: str
    direction: str          # "LONG" | "SHORT"
    contracts: int
    risk_dollars: float     # contracts × stop_dist_points × point_value
    cluster: str            # "roska4_swing" | "roska4_stress" | "global_nkd" | ...


@dataclass
class ClusterBudget:
    """Per-cluster caps as % of account. net = |long$ − short$|, gross = heavier side."""
    name: str
    max_gross_pct: float
    max_net_pct: float | None = None     # None → only gross capped (sleeves)


# Default clusters. Rổ-4 swing keeps the validated 3.5% net / 4% gross.
# STRESS sleeve keeps its 2.5% gross. NKD is a NEW independent cluster.
# roska4_swing gross 5% / net 4.4%: chosen by cap_sweep (highest Calmar under the
# 10% DD target, robust across 1× & 2× slippage). The old 4%/3.5% was calibrated
# for a $500 risk stub and choked real-risk trading (rejected 64% of entries).
DEFAULT_CLUSTERS = {
    "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05,  max_net_pct=0.044),
    "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
    # 2% → 6% (2026-08-04): saturation point of the NKD-only sweep, see module
    # docstring. MaxDD unchanged at $3,390 across the whole sweep.
    "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.06,  max_net_pct=0.06),
}

# Entry priority when several same-cluster entries compete for budget on one day.
# risk-high-first (largest risk$ first) beat time-order and risk-low-first on
# Calmar at the SAME cap, robust across 1×/2× slippage (+0.15 Calmar, MaxDD flat).
# Rationale: high-ATR legs (MNQ-like) carry the fattest trend tails — keep them.
# A-priori (sorts by risk$, never by realized P&L) so it generalizes, not overfits.
def entry_priority_key(trade) -> float:
    """Sort key for same-day same-cluster entries before admission. Lower sorts
    first, so negate risk to put the largest-risk (highest-vol) leg first.
    `trade` may be a dict with 'risk'/'risk_sized'/'risk_dollars' or a Position."""
    r = (trade.get("risk_sized") or trade.get("risk") or trade.get("risk_dollars")
         if isinstance(trade, dict) else getattr(trade, "risk_dollars", 0.0))
    return -float(r or 0.0)


@dataclass
class MultiClusterGuard:
    clusters: dict = field(default_factory=lambda: dict(DEFAULT_CLUSTERS))
    account: float = 50_000.0

    def _cluster_of(self, p: Position) -> str:
        if p.cluster in self.clusters:
            return p.cluster
        raise KeyError(f"position cluster '{p.cluster}' has no budget. "
                       f"Known: {list(self.clusters)}")

    def state(self, positions) -> dict:
        """Per-cluster long/short/net/gross in % of account."""
        out = {}
        for cname, cb in self.clusters.items():
            ps = [p for p in positions if p.cluster == cname]
            long_r = sum(p.risk_dollars for p in ps if p.direction == "LONG")
            short_r = sum(p.risk_dollars for p in ps if p.direction == "SHORT")
            gross = max(long_r, short_r)
            net = abs(long_r - short_r)
            out[cname] = dict(long=long_r, short=short_r, gross=gross, net=net,
                              gross_pct=gross / self.account, net_pct=net / self.account,
                              cap_gross=cb.max_gross_pct, cap_net=cb.max_net_pct)
        return out

    def admits(self, proposed: Position, open_positions) -> tuple[bool, str]:
        """Check the proposed entry ONLY against its own cluster budget — clusters
        are independent (different correlation group / different session window)."""
        cb = self.clusters[self._cluster_of(proposed)]
        book = [p for p in open_positions if p.cluster == proposed.cluster] + [proposed]
        long_r = sum(p.risk_dollars for p in book if p.direction == "LONG")
        short_r = sum(p.risk_dollars for p in book if p.direction == "SHORT")
        gross_pct = max(long_r, short_r) / self.account
        if gross_pct > cb.max_gross_pct:
            return False, f"{cb.name} gross {gross_pct:.1%} > cap {cb.max_gross_pct:.1%}"
        if cb.max_net_pct is not None:
            net_pct = abs(long_r - short_r) / self.account
            if net_pct > cb.max_net_pct:
                return False, f"{cb.name} net {net_pct:.1%} > cap {cb.max_net_pct:.1%}"
        return True, "ok"

    def filter_entries(self, proposed_list, open_positions):
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
    # Rổ 4 long all 4 + STRESS short ES + NKD long — each checked vs its OWN cluster.
    g = MultiClusterGuard()
    proposed = (
        [Position(n, "LONG", 1, 500, "roska4_swing") for n in ("MES", "MNQ", "MYM", "M2K")]
        + [Position("MES", "SHORT", 1, 500, "roska4_stress")]
        + [Position("MNKD", "LONG", 1, 400, "global_nkd")]
    )
    adm, rej = g.filter_entries(proposed, [])
    print(f"admitted {len(adm)}:")
    for p in adm:
        print(f"  {p.instrument:<5} {p.direction:<5} [{p.cluster}]")
    for p, why in rej:
        print(f"  REJECT {p.instrument} {p.direction}: {why}")
    print("\nper-cluster state:")
    for c, s in g.state(adm).items():
        cap = f"net≤{s['cap_net']:.1%}" if s['cap_net'] else "gross-only"
        print(f"  {c:<14} gross {s['gross_pct']:.1%} (cap {s['cap_gross']:.1%}) "
              f"net {s['net_pct']:.1%} [{cap}]")
    print("\nNote: NKD long does NOT count against Rổ-4 budget — independent cluster. "
          "Account DD cap (15%) is enforced separately in circuit_breaker, combined.")
