"""Trai mot lenh qua cuoi tuan ra tung nen: mo hinh vu trang luc nao, live luc nao,
va thoat o dau. Kem thong ke tren ca 84 lenh: bao nhieu lenh mo hinh thoat TRUOC
moc live 14:00, tuc live van con dang cam.
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
bas = load_basket("data/cache/futures/frozen_sim"); COSTS = costs_for_basket(2.0)
cut = pd.Timestamp("2024-12-31")

vidu = None
T = {"n": 0, "truoc_moc": 0, "pnl_truoc": 0.0, "sau_moc": 0}
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
    for t in tr:
        if t["reason"] != "CHANDELIER":
            continue
        d0 = pd.Timestamp(t["day"]).normalize(); d1 = pd.Timestamp(t["exit_day"]).normalize()
        i0 = pos.get(d0)
        if i0 is None or i0 + 1 >= len(days) or days[i0 + 1] != d1:
            continue
        if d1 == d0 + pd.Timedelta(days=1):
            continue                                   # khong phai nhom cuoi tuan
        T["n"] += 1
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        moc_live = d1 + pd.Timedelta(hours=H.ARM_LIVE)  # 14:05 ET ngay giao dich ke tiep
        if et < moc_live:
            T["truoc_moc"] += 1; T["pnl_truoc"] += float(t["pnl"])
            if vidu is None and t["pnl"] < 0:
                dts = ts.get(d1); nv = dts.tz_localize(None) if dts.tz is not None else dts
                jl = int(np.searchsorted(np.asarray(nv), np.datetime64(moc_live)))
                vidu = dict(sym=sym, t=t, d0=d0, d1=d1, et=et, moc=moc_live,
                            op0=float(hl[d1][2][0]), hi=float(hl[d1][0].max()),
                            lo=float(hl[d1][1].min()),
                            px_moc=float(hl[d1][2][jl]) if jl < len(nv) else None,
                            pv=cost.point_value)
        else:
            T["sau_moc"] += 1
    H._CACHE.clear()

v = vidu
print("=" * 78)
print("MOT LENH CU THE — {} vao {} ({}), thoat {} ({})".format(
    v["sym"], v["d0"].date(), v["d0"].day_name(), v["d1"].date(), v["d1"].day_name()))
print("=" * 78)
print("  chieu {} | vao {:.2f} | stop dat o {:.2f}".format(
    v["t"]["direction"], float(v["t"]["entry"]), float(v["t"]["exit"])))
print()
print("  MO HINH  : moc vu trang = ngay vao + 1 NGAY LICH + 14,08h = {} 14:05".format(
    (v["d0"] + pd.Timedelta(days=1)).strftime("%a %d/%m")))
print("             -> khong ton tai nen nao. Moi nen {} deu da qua moc".format(
    v["d1"].strftime("%a")))
print("             -> stop song tu NEN MO CUA {}, thoat luc {} o {:.2f}, P&L ${:,.0f}".format(
    v["d1"].strftime("%a"), v["et"].strftime("%H:%M"), float(v["t"]["exit"]), float(v["t"]["pnl"])))
print()
print("  LIVE     : cron dat STP luc {} 14:00 ET".format(v["d1"].strftime("%a")))
print("             -> tu mo cua den 14:00 KHONG co lenh stop nao tren san")
print("             -> luc 14:05 gia dang o {:.2f}".format(v["px_moc"]) if v["px_moc"]
      else "             -> khong co nen 14:05")
print()
print("  ngay {}: mo {:.2f} | cao nhat {:.2f} | thap nhat {:.2f}".format(
    v["d1"].strftime("%a"), v["op0"], v["hi"], v["lo"]))
print("  -> mo hinh dong lenh luc {}, som hon moc live {} tieng".format(
    v["et"].strftime("%H:%M"), round((v["moc"] - v["et"]).total_seconds() / 3600, 1)))

print("\n" + "=" * 78)
print("TREN CA NHOM (Ro 4, 1 hop dong, IS 2018-2024)")
print("=" * 78)
print("  lenh qua cuoi tuan/le thoat CHANDELIER ngay ke tiep : {}".format(T["n"]))
print("  mo hinh thoat TRUOC moc live 14:05                  : {} ({:.0%})"
      .format(T["truoc_moc"], T["truoc_moc"] / max(T["n"], 1)))
print("     -> live van con dang cam o thoi diem do. Tong P&L mo hinh ghi: ${:,.0f}"
      .format(T["pnl_truoc"]))
print("  mo hinh thoat SAU moc live (hai ben trung nhau)      : {}".format(T["sau_moc"]))
