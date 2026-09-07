"""Ham hieu chinh co bo sot lenh vao thu Sau / truoc ngay nghi khong? — CHI DOC.

Dieu kien trong _correct la d1 == d0 + 1 NGAY LICH. Neu ngay giao dich ke tiep khong phai
ngay lich ke tiep (thu Sau -> thu Hai, truoc le), lenh do bi bo qua.

Phep do nay PHAI co the do: neu so lenh "ngay giao dich ke tiep nhung khong phai ngay lich
ke tiep" = 0 thi khong co bo sot va toi da lo lang thua.
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, r"d:\raits"); sys.path.insert(0, r"d:\raits\scratch")
import harness as H
from futures.basket import SWING_TF_PARAM
from futures.swing_tf import basket_labels, load_basket, costs_for_basket
from raits.strategies.trend_follow import TrendFollowStrategy
from model_sameday_stop import run_loop

ema = SWING_TF_PARAM["ema_period"]
c = dict(TrendFollowStrategy().config)
c["ema_period"] = ema; c["chandelier_atr_mult"] = SWING_TF_PARAM["chandelier_atr_mult"]
strat = TrendFollowStrategy(c)
labels = basket_labels("spy_daily_live.csv")
bas = load_basket("data/cache/futures/frozen_sim")
COSTS = costs_for_basket(2.0)
cut = pd.Timestamp("2024-12-31")

TONG = {"n_ke": 0, "n_lich": 0, "n_bosot": 0, "tien_bosot": 0.0, "n_doichung": 0}
for sym, df in bas.items():
    df = df[df.index <= cut.tz_localize(df.index.tz)]
    cost = COSTS[sym]
    cache, datr = H._cache(df)
    sig = H._make_sig(cache, datr, labels, strat, ema, set(c["allowed_regimes"]), H.Cfg(), True)
    tr, _ = run_loop(df, labels, cost, strat=strat, ema_period=ema,
                     mult=SWING_TF_PARAM["chandelier_atr_mult"], max_hold_days=5,
                     cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                     activate_after_h=0.0, sig_cache=sig,
                     stop_active_hour=H.ARM_LIVE, ratchet=False, disaster_mult=None)
    days = list(cache["days"]); pos = {d: i for i, d in enumerate(days)}
    ts, hl = cache.get("ts", {}), cache["hl"]
    nke = nlich = nbs = 0; tien = 0.0
    for t in tr:
        if t["reason"] != "CHANDELIER":
            continue
        d0 = pd.Timestamp(t["day"]).normalize(); d1 = pd.Timestamp(t["exit_day"]).normalize()
        i0 = pos.get(d0)
        if i0 is None or i0 + 1 >= len(days) or days[i0 + 1] != d1:
            continue                       # khong phai ngay giao dich ke tiep
        nke += 1
        cuoituan = d1 != d0 + pd.Timedelta(days=1)
        if not cuoituan:
            nlich += 1
        # ham hien tai BO SOT -> tinh xem le ra sua bao nhieu
        dts = ts.get(d1)
        if dts is None or not len(dts):
            continue
        nv = dts.tz_localize(None) if dts.tz is not None else dts
        arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H.ARM_LIVE)
        j = int(np.searchsorted(np.asarray(nv), np.datetime64(arm)))
        et = t.get("exit_time")
        if j >= len(nv) or et is None:
            continue
        et = pd.Timestamp(et)
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        if et != pd.Timestamp(nv[j]):
            continue
        op = float(hl[d1][2][j]); stp = float(t["exit"])
        w = (stp - op) if t["direction"] == "LONG" else (op - stp)
        if w > 0:
            if cuoituan:
                nbs += 1; tien += w * cost.point_value
            else:
                TONG["n_doichung"] += 1     # PHAI khac 0, neu khong logic dò hỏng
    print("{:<5} CHANDELIER sang ngay giao dich ke tiep {:>4} | ham BAT {:>4} | BO SOT {:>3} = ${:,.0f}"
          .format(sym, nke, nlich, nbs, tien))
    TONG["n_ke"] += nke; TONG["n_lich"] += nlich; TONG["n_bosot"] += nbs; TONG["tien_bosot"] += tien
    H._CACHE.clear()

print("\n=== TONG (Ro 4, 1 hop dong, IS 2018-2024) ===")
print("  lenh thoat sang ngay giao dich ke tiep : {}".format(TONG["n_ke"]))
print("  ham hieu chinh bat duoc                : {} ({:.0%})".format(
    TONG["n_lich"], TONG["n_lich"] / max(TONG["n_ke"], 1)))
print("  BO SOT (dung moc run_loop dung, mo te hon stop): {} = ${:,.0f}".format(
    TONG["n_bosot"], TONG["tien_bosot"]))
print("\n  -> {}".format("CO BO SOT, phai sua ham" if TONG["n_bosot"] else
                         "KHONG bo sot"))
print("\n  DOI CHUNG — cung logic do, chay tren nhom ham VAN bat: {} lenh".format(
    TONG["n_doichung"]))
print("  -> {}".format("khac 0: phep do CO THE do, so bo sot 0 la that"
                       if TONG["n_doichung"] else
                       "= 0: LOGIC DO HONG, KHONG duoc tin con so ben tren"))
