"""
futures/sizer.py — position sizing for the futures basket (combined-portfolio)
=============================================================================
Self-contained (imports only futures.basket / futures.cost). Answers: how many
micro contracts per instrument on a $50k account, capped so the COMBINED
portfolio's expected drawdown stays ~10% (buffer under the hard 15% cap).

Locked decisions (basket.RISK): account $50k, DD hard cap 15%, target DD 10%,
risk/trade 1%. Sizing is the MIN of three constraints:
  1. Drawdown-scaled: scale 1-micro sizing by (target_DD$ / backtest_basket_DD$).
  2. Margin: total margin ≤ a fraction of account (leave most in T-bill).
  3. Per-trade risk: 1% ($500) per entry via ATR-based stop distance (live guard).

Because the 4 indices are correlated and BOTH engines may fire together, the
drawdown constraint is applied to the COMBINED basket equity curve, not per
instrument — that is the binding, honest cap.
"""
from __future__ import annotations
from dataclasses import dataclass

from futures.basket import BASKET, RISK


@dataclass
class SizingResult:
    contracts: dict          # instrument -> int micros
    scale: float             # multiplier applied to 1-micro baseline
    total_margin: float
    margin_pct: float        # of account
    expected_dd_pct: float   # projected, at chosen size
    binding: str             # which constraint bound the size


def size_basket(backtest_basket_maxdd: float,
                account: float | None = None,
                target_dd_pct: float | None = None,
                hard_dd_pct: float | None = None,
                margin_budget_pct: float = 0.40) -> SizingResult:
    """backtest_basket_maxdd: $ MaxDD of the pooled basket at 1-micro-each
    (e.g. ~$2,789 fit_C 3-engine baseline, or use the WFO MaxDD for a through-cycle view —
    prefer the LARGER for safety). Returns integer micro contracts per instrument.

    margin_budget_pct: cap on total margin as a fraction of the account (default
    40% → leaves ~60% in T-bill; conservative for a $50k account)."""
    account = account or RISK["account"]
    target_dd_pct = target_dd_pct or RISK["target_drawdown_pct"]
    hard_dd_pct = hard_dd_pct or RISK["max_drawdown_pct"]

    # 1) drawdown-scaled multiplier (vs 1-micro baseline)
    target_dd = account * target_dd_pct
    dd_scale = target_dd / backtest_basket_maxdd if backtest_basket_maxdd > 0 else 1.0

    # 2) margin cap multiplier
    base_margin = sum(c.est_margin for c in BASKET.values())   # 1 micro each
    margin_scale = (account * margin_budget_pct) / base_margin if base_margin > 0 else 1.0

    scale = min(dd_scale, margin_scale)
    binding = "drawdown" if dd_scale <= margin_scale else "margin"

    n = max(1, int(scale))   # integer micros, floor (≥1)
    contracts = {name: n for name in BASKET}
    total_margin = n * base_margin
    expected_dd = n * backtest_basket_maxdd
    # safety: never let projected DD exceed the hard cap
    while n > 1 and expected_dd > account * hard_dd_pct:
        n -= 1
        contracts = {name: n for name in BASKET}
        total_margin = n * base_margin
        expected_dd = n * backtest_basket_maxdd
        binding = "drawdown (hard-cap clamp)"

    return SizingResult(
        contracts=contracts, scale=scale, total_margin=total_margin,
        margin_pct=total_margin / account,
        expected_dd_pct=expected_dd / account, binding=binding)


def report(maxdd_1micro: float, **kw) -> str:
    r = size_basket(maxdd_1micro, **kw)
    acct = kw.get("account") or RISK["account"]
    lines = [
        f"Basket sizing on ${acct:,.0f}  (1-micro basket MaxDD = ${maxdd_1micro:,.0f})",
        f"  contracts per instrument : {r.contracts[next(iter(r.contracts))]} micro each "
        f"({', '.join(f'{k} x{v}' for k,v in r.contracts.items())})",
        f"  binding constraint       : {r.binding}",
        f"  total margin             : ${r.total_margin:,.0f}  ({r.margin_pct:.0%} of account)",
        f"  cash idle → T-bill       : ${acct - r.total_margin:,.0f}  ({1-r.margin_pct:.0%})",
        f"  projected expected DD    : {r.expected_dd_pct:.1%}  (hard cap {RISK['max_drawdown_pct']:.0%})",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    # illustrative: baseline MaxDD ~$2,789 (fit_C 3-engine); WFO MaxDD is larger/safer
    print(report(2789))
    print()
    print("Through-cycle (use a more conservative MaxDD, e.g. $4,500 from WFO):")
    print(report(4500))
