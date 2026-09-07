"""Gia thoat ma mo hinh ghi co PHAI la gia tung giao dich khong? — CHI DOC.

Khong tranh luan gia dinh khop lenh nua. Hoi mot cau khong can gia dinh nao:
  - gia thoat co nam trong bien do [thap, cao] cua CHINH BAR thoat khong?
  - va co nam trong bien do [thap nhat, cao nhat] cua CA NGAY hom do khong?

Cau thu hai la lop bao ve chong loi lech mot bar: neu gia thoat nam ngoai bien do CA NGAY
thi khong the do map sai thoi diem — do la mot muc gia chua he ton tai hom do.

Doc bar 1 phut thang tu parquet.

    python scratch/impossible_fill.py --data-dir data/cache/futures/frozen_sim
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    a = ap.parse_args()

    from futures.basket import BASKET
    from futures.swing_tf import load_basket

    dfs = load_basket(a.data_dir)
    print("da nap {} ma".format(len(dfs)))

    for tag in ("prod_backtest", "prod_live14h"):
        f = Path("scratch") / ("calm_probe_" + tag + ".csv")
        if not f.exists():
            print("thieu " + str(f))
            continue
        d = pd.read_csv(f, parse_dates=["day", "exit_day"])
        et = pd.to_datetime(d["exit_time"], utc=True, errors="coerce")
        d["et"] = et.dt.tz_convert("America/New_York").dt.tz_localize(None)

        n_bar = n_day = n_tot = 0
        worst = []
        for inst, g in d.groupby("inst"):
            df = dfs[inst]
            idx = df.index.tz_convert("America/New_York").tz_localize(None)
            F = pd.DataFrame({"h": df["high"].to_numpy(), "l": df["low"].to_numpy()},
                             index=idx)
            F = F[~F.index.duplicated(keep="last")]
            day_hi = F["h"].groupby(F.index.normalize()).max()
            day_lo = F["l"].groupby(F.index.normalize()).min()
            pv = BASKET[inst].point_value
            for _, r in g.iterrows():
                if pd.isna(r["et"]):
                    continue
                try:
                    b = F.loc[r["et"]]
                except KeyError:
                    continue
                n_tot += 1
                px = float(r["exit"])
                lo, hi = float(b["l"]), float(b["h"])
                out_bar = px < lo - 1e-9 or px > hi + 1e-9
                if out_bar:
                    n_bar += 1
                dnorm = pd.Timestamp(r["et"]).normalize()
                dl, dh = float(day_lo.get(dnorm, np.nan)), float(day_hi.get(dnorm, np.nan))
                if np.isfinite(dl) and np.isfinite(dh):
                    out_day = px < dl - 1e-9 or px > dh + 1e-9
                    if out_day:
                        n_day += 1
                        gap = (px - dh) if px > dh else (dl - px)
                        worst.append((gap * pv, inst, str(r["day"].date()),
                                      r["direction"], px, dl, dh))

        print("\n=== {} ===".format(tag))
        print("  kiem duoc {} lenh".format(n_tot))
        print("  gia thoat NAM NGOAI bien do cua chinh bar thoat : {} ({:.1f}%)"
              .format(n_bar, n_bar / max(n_tot, 1) * 100))
        print("  gia thoat NAM NGOAI bien do CA NGAY hom do      : {} ({:.1f}%)"
              .format(n_day, n_day / max(n_tot, 1) * 100))
        worst.sort(key=lambda x: -x[0])
        if worst:
            print("  10 ca xa nhat (gia ghi so vs bien do ca ngay):")
            for gp, inst, day, dr, px, dl, dh in worst[:10]:
                print("    {} {} {}  ghi thoat @ {:.2f}  | ca ngay chi chay {:.2f}-{:.2f}"
                      "  | cach {:.2f} diem = ${:,.0f}"
                      .format(inst, day, dr, px, dl, dh,
                              (px - dh) if px > dh else (dl - px), gp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
