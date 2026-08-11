"""Cai ho -$1.091 tai moc 18h: la co che that hay hien vat cua cach mo hinh hoa?

Gia thuyet: 18:00 ET la gio Globex mo lai sau nghi 17:00-18:00. Vu trang stop dung
luc do => bar dau tien sau khi kich hoat la bar MO PHIEN, mang co `isg` (khoang nghi
thoi gian > 15 phut) => logic gap-fill khop tai GIA MO, co the rat xa muc stop.

Neu dung, ty le thoat GAP phai tang vot o 18h so voi 16h/20h.
"""
from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import SWING_TF_PARAM
from futures.swing_tf import basket_labels, costs_for_basket, load_basket
from futures._validated_core import _swing_cache, daily_atr_series
from raits.strategies.trend_follow import TrendFollowStrategy
from model_sameday_stop import build_sig_cache, run_loop

ema = SWING_TF_PARAM["ema_period"]
mult = SWING_TF_PARAM["chandelier_atr_mult"]
hold = SWING_TF_PARAM["max_hold_days"]
strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                             "ema_period": ema, "chandelier_atr_mult": mult})
allowed = set(strat.config["allowed_regimes"])
dfs = load_basket("data/cache/futures")
labels = basket_labels("spy_daily_live.csv")
costs = costs_for_basket()
caches, sigs = {}, {}
for k, df in dfs.items():
    caches[k] = _swing_cache(df, daily_atr_series(df))
    sigs[k] = build_sig_cache(caches[k], labels, strat, ema, allowed)

print()
print("=" * 78)
print("CHAN DOAN HO 18h — ty le thoat theo ly do, va P&L trung binh moi loai")
print("=" * 78)
print(f"  {'moc':>6} | {'lenh':>6} | {'P&L':>11} | ty le thoat | P&L tb GAP")
print("  " + "-" * 74)
for h in (14, 16, 17, 18, 19, 20):
    allt = []
    for k, df in dfs.items():
        m, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                        max_hold_days=hold, cache=caches[k], same_day_stop=False,
                        stop_slip_ticks=0.0, stop_active_hour=float(h), sig_cache=sigs[k])
        allt.extend(m)
    c = Counter(t["reason"] for t in allt)
    n = len(allt)
    gaps = [t["pnl"] for t in allt if t["reason"] == "GAP"]
    mix = "  ".join(f"{k}={100*v/n:.0f}%" for k, v in sorted(c.items()))
    gp = f"${sum(gaps)/len(gaps):>+8,.0f} (n={len(gaps)})" if gaps else "-"
    print(f"  {h:>5}h | {n:>6} | ${sum(t['pnl'] for t in allt):>+10,.0f} | {mix} | {gp}")
print()
