"""Neu momentum khong an trong Calm thi mean-reversion co khong? — CHI DOC.

mean_reversion_explore.py da hoi dung cau hoi nay nhung goi label_regimes KHONG truyen
hmm_fit_end, nen no fit HMM toi 2019-06-30 — KHAC khung production (fit_end 2024-12-31).
Nhan khac thi ngay nao la Calm cung khac. Ban nay do lai bang dung khung he thong dung.

Phep do (Lo & MacKinlay variance ratio tren loi nhuan 5 phut RTH, tach theo regime):
    VR(k) < 1  -> dao chieu (MR co cua)
    VR(k) > 1  -> xu huong (momentum — da co TF)
    VR(k) ~ 1  -> buoc ngau nhien (khong ai an duoc)

KIEM CONG CU: tron ngau nhien chuoi loi nhuan pha het tu tuong quan -> VR PHAI ~ 1.
Neu chuoi da tron van cho VR lech xa 1 thi uoc luong hong, khong doc bang chinh.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def variance_ratio(rets, k):
    r = np.asarray(rets); r = r[np.isfinite(r)]
    if len(r) < k * 5:
        return np.nan
    var1 = np.var(r, ddof=1)
    if var1 <= 0:
        return np.nan
    cs = np.cumsum(r)
    kret = cs[k:] - cs[:-k]
    return float(np.var(kret, ddof=1) / (k * var1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--end", default="2024-12-31")
    a = ap.parse_args()

    import gate2_edge_harness as G
    from futures.basket import BASKET, REGIME
    from futures.swing_tf import load_basket

    print("=== CO SO DO ===")
    print(f"  data-dir {a.data_dir} | regime-csv {a.regime_csv}")
    print(f"  nhan: train_end=2018-01-01  n=3  fit_end={REGIME['hmm_fit_end']}  (KHUNG PRODUCTION)")

    daily = G.benchmark_daily(a.regime_csv)
    daily = daily[~daily.index.duplicated(keep="last")]
    labels = G.label_regimes(daily, "2018-01-01", 3, REGIME["hmm_fit_end"])
    labels = {pd.Timestamp(k).tz_localize(None).normalize(): v for k, v in labels.items()}
    ncalm = sum(1 for v in labels.values() if v == "Calm")
    print(f"  nhan: {len(labels)} ngay, Calm {ncalm} ({ncalm/len(labels)*100:.1f}%)")

    dfs = load_basket(a.data_dir)
    cut = pd.Timestamp(a.end)

    rng = np.random.default_rng(42)
    rows = []
    for inst, df in dfs.items():
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        df = df[df.index <= c]
        rec = {r: {"rets": [], "gap": [], "rth": [], "am": [], "pm": []}
               for r in ("Calm", "Normal", "Stress")}
        prev_close = None
        for day, g in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day).tz_localize(None).normalize()
            reg = labels.get(key)
            b5 = G.resample_5m(g).between_time("09:30", "16:00")
            if len(b5) < 20:
                if len(b5):
                    prev_close = float(b5["close"].iloc[-1])
                continue
            cl_s = b5["close"]
            op, cl = float(cl_s.iloc[0]), float(cl_s.iloc[-1])
            am = b5.between_time("09:30", "11:00")["close"]
            pm = b5.between_time("11:00", "16:00")["close"]
            if reg in rec:
                rec[reg]["rets"].append(cl_s.pct_change().dropna().to_numpy())
                rec[reg]["rth"].append(cl / op - 1)
                rec[reg]["gap"].append(op / prev_close - 1 if prev_close else np.nan)
                rec[reg]["am"].append(float(am.iloc[-1] / am.iloc[0] - 1) if len(am) > 1 else np.nan)
                rec[reg]["pm"].append(float(pm.iloc[-1] / pm.iloc[0] - 1) if len(pm) > 1 else np.nan)
            prev_close = cl

        for reg in ("Calm", "Normal", "Stress"):
            if not rec[reg]["rets"]:
                continue
            allr = np.concatenate(rec[reg]["rets"])
            sh = rng.permutation(allr)
            gp = pd.DataFrame({"g": rec[reg]["gap"], "r": rec[reg]["rth"]}).dropna()
            ap_ = pd.DataFrame({"a": rec[reg]["am"], "p": rec[reg]["pm"]}).dropna()
            rows.append(dict(inst=inst, reg=reg, days=len(rec[reg]["rets"]), bars=len(allr),
                             vr6=variance_ratio(allr, 6), vr12=variance_ratio(allr, 12),
                             vr6_shuf=variance_ratio(sh, 6),
                             gap_corr=gp["g"].corr(gp["r"]) if len(gp) > 30 else np.nan,
                             gap_n=len(gp),
                             ampm_corr=ap_["a"].corr(ap_["p"]) if len(ap_) > 30 else np.nan))
        print(f"  {inst} xong")

    R = pd.DataFrame(rows)

    print("\n=== KIEM CONG CU (chuoi da tron phai cho VR ~ 1) ===")
    bad = R[(R.vr6_shuf < 0.93) | (R.vr6_shuf > 1.07)]
    print(f"  VR6 tren chuoi tron: min {R.vr6_shuf.min():.3f} max {R.vr6_shuf.max():.3f}")
    print(f"  [{'PASS' if bad.empty else 'FAIL'}] moi VR6-tron nam trong [0.93, 1.07]")
    if not bad.empty:
        print("!! uoc luong hong — dung"); return 1
    if not (R.days > 100).all():
        print(f"  [WARN] co nhom < 100 ngay: {R[R.days<=100][['inst','reg','days']].to_dict('records')}")

    print("\n=== VARIANCE RATIO theo regime (VR<1 dao chieu | >1 xu huong) ===")
    print(f"  {'inst':<5} {'regime':<7} {'days':>5} {'VR(30m)':>9} {'VR(60m)':>9}  doc")
    for _, r in R.sort_values(["reg", "inst"]).iterrows():
        read = "DAO CHIEU" if r.vr6 < 0.9 else "XU HUONG" if r.vr6 > 1.1 else "ngau nhien"
        print(f"  {r.inst:<5} {r.reg:<7} {r.days:>5} {r.vr6:>9.3f} {r.vr12:>9.3f}  {read}")

    print("\n=== TRUNG BINH 4 MA ===")
    for reg in ("Calm", "Normal", "Stress"):
        s = R[R.reg == reg]
        if s.empty:
            continue
        print(f"  {reg:<7} VR30m {s.vr6.mean():.3f}  VR60m {s.vr12.mean():.3f}  "
              f"corr(gap,RTH) {s.gap_corr.mean():+.3f}  corr(sang,chieu) {s.ampm_corr.mean():+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
