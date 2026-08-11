"""Lenh chim sau trong cua so tran co thuc su hoi lai khong?

Tien de cua ca hai lap luan: "lo tam roi van loi => lo chi la tam thoi". Chua ai kiem.

Neu lenh MAE cao van ket thuc co lai  -> hoi lai la that, guard se cat nham
Neu lenh MAE cao ket thuc lo nang     -> "tam thoi" la cach goi sai, guard cat DUNG

mae_full va trades duoc ghi cung cho trong _close nen khop 1:1.
"""
from __future__ import annotations
import statistics as st, sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import SWING_TF_PARAM
from futures.swing_tf import basket_labels, costs_for_basket, load_basket
from futures._validated_core import _swing_cache, daily_atr_series
from raits.strategies.trend_follow import TrendFollowStrategy
from model_sameday_stop import build_sig_cache, run_loop

ema = SWING_TF_PARAM["ema_period"]; mult = SWING_TF_PARAM["chandelier_atr_mult"]
hold = SWING_TF_PARAM["max_hold_days"]
strat = TrendFollowStrategy({**TrendFollowStrategy().config,
                             "ema_period": ema, "chandelier_atr_mult": mult})
allowed = set(strat.config["allowed_regimes"])
dfs = load_basket("data/cache/futures"); labels = basket_labels("spy_daily_live.csv")
costs = costs_for_basket()

for ACT in (1.17, 14.08):
    rows = []
    for k, df in dfs.items():
        cache = _swing_cache(df, daily_atr_series(df))
        sig = build_sig_cache(cache, labels, strat, ema, allowed)
        mae = []
        m, _ = run_loop(df, labels, costs[k], strat=strat, ema_period=ema, mult=mult,
                        max_hold_days=hold, cache=cache, same_day_stop=False,
                        stop_slip_ticks=0.0, stop_active_hour=ACT, sig_cache=sig,
                        mae_full=mae)
        assert len(mae) == len(m), f"lech {len(mae)} vs {len(m)}"
        rows += list(zip(mae, (t["pnl"] for t in m)))

    rows.sort(key=lambda x: x[0])
    n = len(rows)
    print()
    print("=" * 84)
    print(f"MAE trong cua so tran  vs  KET QUA CUOI CUNG  (kich hoat sau {ACT}h)")
    print("=" * 84)
    print(f"  {'nhom theo MAE':>22} | {'lenh':>5} | {'MAE tb':>9} | "
          f"{'P&L tb':>9} | {'P&L tong':>11} | thang")
    print("  " + "-" * 78)
    # thap phan vi
    for i in range(10):
        lo, hi = int(n * i / 10), int(n * (i + 1) / 10)
        blk = rows[lo:hi]
        if not blk:
            continue
        maes = [x[0] for x in blk]; pnls = [x[1] for x in blk]
        w = 100 * sum(1 for p in pnls if p > 0) / len(pnls)
        print(f"  {f'thap phan vi {i+1}':>22} | {len(blk):>5} | ${st.mean(maes):>8,.0f} | "
              f"${st.mean(pnls):>+8,.0f} | ${sum(pnls):>+10,.0f} | {w:>4.0f}%")
    # duoi 5% sau nhat
    tail = rows[int(n * 0.95):]
    tp = [x[1] for x in tail]
    print("  " + "-" * 78)
    print(f"  5% MAE SAU NHAT       | {len(tail):>5} | "
          f"${st.mean([x[0] for x in tail]):>8,.0f} | ${st.mean(tp):>+8,.0f} | "
          f"${sum(tp):>+10,.0f} | {100*sum(1 for p in tp if p>0)/len(tp):>4.0f}%")
print()
