"""Sau mot cu di nguoc ~23 tieng, 3-4 ngay sau gia o dau? — CHI DOC, tren TOAN BO lich su.

Tach khoi tap lenh: khong can he vao lenh moi co quan sat. Moi ngay x moi ma = mot quan sat,
nen mau lon hon nhieu lan so voi 642 lan he thua.

Dung mot khung thoi gian voi quyet dinh that:
  P0 = gia luc 15:00 ET ngay D            (quanh gio he vao lenh)
  P1 = gia luc 14:05 ET ngay D+1          (moc vu trang stop)
  P2 = gia mo ngay D+5                    (tran nam giu)
  r1 = chan DI NGUOC   (P1/P0 - 1), tinh bang ATR ngay
  r2 = chan SAU DO     (P2/P1 - 1), tinh bang ATR ngay

Cau hoi: voi r1 am manh (gia da di nguoc), r2 co duong khong?
   r2 > 0 -> dao chieu, GIU co ly
   r2 ~ 0 -> buoc ngau nhien, thoi diem thoat khong tao gia tri
   r2 < 0 -> tiep dien, CAT co ly
Doi xung cho ca hai chieu: chieu MUA doc r1<0 va E[r2]; chieu BAN doc r1>0 va E[-r2].

KHOI LUONG: tong khoi luong quang P0->P1 chia trung binh 20 phien cung quang.
Doc kinh dien: di nguoc kem khoi luong CAO = that (khong hoi); khoi luong THAP = nhieu (hoi).

NGUONG CAM KET TRUOC: hieu ung phai >= 0,10 ATR ngay (bang co khoang cach stop hien tai)
va KTC 95% bootstrap THEO NGAY khong chua 0.

    python scratch/revert_study.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

RNG = np.random.default_rng(11)


def boot_mean(df, col, n=4000):
    days = df["ngay"].unique()
    out = []
    for _ in range(n):
        pick = RNG.choice(days, size=len(days), replace=True)
        cnt = pd.Series(pick).value_counts()
        s = df[df["ngay"].isin(cnt.index)]
        w = s["ngay"].map(cnt).astype(float)
        if w.sum() < 30:
            continue
        out.append(float(np.average(s[col], weights=w)))
    return np.array(out)


def main() -> int:
    from futures.swing_tf import load_basket
    from futures._validated_core import daily_atr_series

    dfs = load_basket("data/cache/futures/frozen_sim")
    cut = pd.Timestamp("2024-12-31")
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]

    rows = []
    for k in dfs:
        df = dfs[k]
        datr = daily_atr_series(df)
        idx = df.index.tz_convert("America/New_York").tz_localize(None)
        C = pd.Series(df["close"].to_numpy(), index=idx)
        O = pd.Series(df["open"].to_numpy(), index=idx)
        V = pd.Series(df["volume"].to_numpy(), index=idx)
        C = C[~C.index.duplicated(keep="last")]
        O = O[~O.index.duplicated(keep="last")]
        V = V.groupby(V.index).sum()

        days = pd.DatetimeIndex(sorted({d.normalize() for d in idx}))
        recs = []
        for d in days:
            t0 = d + pd.Timedelta(hours=15)
            t1 = d + pd.Timedelta(days=1, hours=14, minutes=5)
            t2 = d + pd.Timedelta(days=5)
            try:
                p0 = float(C.asof(t0))
                p1 = float(C.asof(t1))
                da = float(datr.asof(d))
            except Exception:
                continue
            nx = O[O.index >= t2]
            if not len(nx):
                continue
            p2 = float(nx.iloc[0])
            if not all(np.isfinite([p0, p1, p2, da])) or da <= 0 or p0 <= 0:
                continue
            vol = float(V[(V.index > t0) & (V.index <= t1)].sum())
            recs.append(dict(ngay=str(d.date()), inst=k, da=da,
                             r1=(p1 - p0) / da, r2=(p2 - p1) / da, vol=vol))
        RR = pd.DataFrame(recs)
        if RR.empty:
            continue
        RR["vol_ma"] = RR["vol"].rolling(20).mean()
        RR = RR.dropna()
        RR["vr"] = RR["vol"] / RR["vol_ma"]
        rows.append(RR)
        print("  {} xong  ({} quan sat)".format(k, len(RR)), flush=True)

    R = pd.concat(rows, ignore_index=True)
    print("\n" + "=" * 96)
    print("MAU: {} quan sat tren {} ngay, {} ma".format(len(R), R.ngay.nunique(),
                                                        R.inst.nunique()))
    print("  (so voi 642 quan sat cua phep do tren tap lenh — gap {:.0f} lan)"
          .format(len(R) / 642))
    print("=" * 96)

    # doi xung: chieu MUA = r1 am; chieu BAN = r1 duong, doi dau r2
    L = R[R.r1 < 0].copy()
    L["adv"] = -L.r1
    L["fwd"] = L.r2
    S = R[R.r1 > 0].copy()
    S["adv"] = S.r1
    S["fwd"] = -S.r2
    A = pd.concat([L.assign(chieu="MUA"), S.assign(chieu="BAN")], ignore_index=True)

    print("\n=== 1. CHAN SAU (r2) THEO DO LON CU DI NGUOC — don vi ATR ngay ===")
    bins = [0, .1, .2, .35, .6, 1.0, 100]
    lbl = ["0-0.1", "0.1-0.2", "0.2-0.35", "0.35-0.6", "0.6-1.0", ">1.0"]
    A["b"] = pd.cut(A.adv, bins=bins, labels=lbl)
    print("  {:<10} {:>7} {:>12} {:>12} {:>10}".format("di nguoc", "n", "E[chan sau]",
                                                        "trung vi", "% duong"))
    for b in lbl:
        s = A[A.b == b]
        if len(s) < 50:
            continue
        print("  {:<10} {:>7} {:>12.4f} {:>12.4f} {:>9.1f}%"
              .format(b, len(s), s.fwd.mean(), s.fwd.median(), (s.fwd > 0).mean() * 100))

    print("\n=== 2. THEM KHOI LUONG (quang di nguoc / trung binh 20 phien) ===")
    q = A.vr.quantile([.33, .66]).to_list()
    A["vb"] = pd.cut(A.vr, [-1e9] + q + [1e9], labels=["KL thap", "KL vua", "KL cao"])
    print("  {:<10} {:<10} {:>7} {:>12} {:>10}".format("di nguoc", "khoi luong", "n",
                                                        "E[chan sau]", "% duong"))
    for b in lbl:
        for vb in ["KL thap", "KL vua", "KL cao"]:
            s = A[(A.b == b) & (A.vb == vb)]
            if len(s) < 50:
                continue
            print("  {:<10} {:<10} {:>7} {:>12.4f} {:>9.1f}%"
                  .format(b, vb, len(s), s.fwd.mean(), (s.fwd > 0).mean() * 100))

    print("\n=== 3. PHIEU QUYET DINH — bootstrap THEO NGAY, nguong 0.10 ATR ===")
    for b in ["0.2-0.35", "0.35-0.6", "0.6-1.0", ">1.0"]:
        s = A[A.b == b]
        if len(s) < 100:
            continue
        d = boot_mean(s, "fwd")
        if not len(d):
            continue
        lo, hi = np.percentile(d, [2.5, 97.5])
        ok = abs(np.mean(d)) >= 0.10 and (lo > 0 or hi < 0)
        print("  di nguoc {:<10} E[chan sau] {:+.4f} ATR | KTC [{:+.4f},{:+.4f}] | {}"
              .format(b, np.mean(d), lo, hi, "DAT" if ok else "khong dat"))

    print("\n  -- khoi luong CAO vs THAP, trong cac o di nguoc sau --")
    for b in ["0.2-0.35", "0.35-0.6", "0.6-1.0"]:
        hi_ = A[(A.b == b) & (A.vb == "KL cao")]
        lo_ = A[(A.b == b) & (A.vb == "KL thap")]
        if len(hi_) < 60 or len(lo_) < 60:
            continue
        dh = boot_mean(hi_, "fwd")
        dl = boot_mean(lo_, "fwd")
        if not len(dh) or not len(dl):
            continue
        diff = np.mean(dh) - np.mean(dl)
        print("    {:<10} KL cao {:+.4f} | KL thap {:+.4f} | chenh {:+.4f} ATR"
              .format(b, np.mean(dh), np.mean(dl), diff))

    print("\n=== 4. DOI CHUNG: toan bo mau, khong dieu kien gi ===")
    d = boot_mean(A, "fwd")
    print("  E[chan sau] tren tat ca {:+.4f} ATR | KTC [{:+.4f},{:+.4f}]"
          .format(np.mean(d), *np.percentile(d, [2.5, 97.5])))
    print("  (neu con so nay khac 0 dang ke thi do la XU HUONG CHUNG, khong phai dao chieu)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
