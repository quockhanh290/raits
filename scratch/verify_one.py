"""Kiem MOT lenh bang tay: mo hinh ghi thoat o gia nao, va hom do thi truong chay tu dau
toi dau. Doc thang parquet, khong qua bat ky phep tinh nao cua toi.

    python scratch/verify_one.py --inst MNQ --date 2022-05-12
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True, help="MES / MNQ / MYM / M2K")
    ap.add_argument("--date", required=True, help="ngay VAO LENH, vd 2022-05-12")
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    a = ap.parse_args()

    from futures.swing_tf import load_basket

    d = pd.read_csv("scratch/calm_probe_prod_backtest.csv",
                    parse_dates=["day", "exit_day"])
    row = d[(d.inst == a.inst) & (d.day == pd.Timestamp(a.date))]
    if row.empty:
        print("khong tim thay lenh {} vao ngay {} trong so lenh".format(a.inst, a.date))
        print("cac ngay co lenh cua {}: {}".format(
            a.inst, ", ".join(str(x.date()) for x in
                              d[d.inst == a.inst].day.head(20))))
        return 1
    r = row.iloc[0]

    df = load_basket(a.data_dir)[a.inst]
    idx = df.index.tz_convert("America/New_York").tz_localize(None)
    F = pd.DataFrame({"o": df["open"].to_numpy(), "h": df["high"].to_numpy(),
                      "l": df["low"].to_numpy(), "c": df["close"].to_numpy()},
                     index=idx)
    xd = pd.Timestamp(r["exit_day"]).normalize()
    day = F[(F.index >= xd) & (F.index < xd + pd.Timedelta(days=1))]

    print("\n=== LENH MO HINH GHI ===")
    print("  {} {}  vao ngay {} @ {}".format(a.inst, r["direction"], r["day"].date(),
                                             r["entry"]))
    print("  ghi THOAT ngay {} luc {}  @ GIA {}   ly do {}"
          .format(r["exit_day"].date(), r["exit_time"], r["exit"], r["reason"]))
    print("  P&L mo hinh ghi: ${}".format(r["pnl"]))

    print("\n=== THI TRUONG NGAY THOAT ({}) — doc thang tu parquet ===".format(xd.date()))
    if day.empty:
        print("  khong co bar nao")
        return 1
    print("  so bar 1 phut: {}".format(len(day)))
    print("  CAO NHAT ca ngay : {:.2f}".format(day["h"].max()))
    print("  THAP NHAT ca ngay: {:.2f}".format(day["l"].min()))
    px = float(r["exit"])
    if px > day["h"].max():
        print("\n  >>> GIA GHI SO ({:.2f}) CAO HON MUC CAO NHAT CA NGAY {:.2f} — cach {:.2f} diem"
              .format(px, day["h"].max(), px - day["h"].max()))
        print("  >>> muc gia nay KHONG HE GIAO DICH trong ngay hom do.")
    elif px < day["l"].min():
        print("\n  >>> GIA GHI SO ({:.2f}) THAP HON MUC THAP NHAT CA NGAY {:.2f} — cach {:.2f} diem"
              .format(px, day["l"].min(), day["l"].min() - px))
        print("  >>> muc gia nay KHONG HE GIAO DICH trong ngay hom do.")
    else:
        print("\n  gia ghi so nam trong bien do ca ngay (nhung van co the sai thoi diem)")

    print("\n  duong gia theo gio:")
    hh = day.resample("60min").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    for t, b in hh.iterrows():
        print("    {}  O {:>10.2f}  H {:>10.2f}  L {:>10.2f}  C {:>10.2f}"
              .format(t.strftime("%H:%M"), b["o"], b["h"], b["l"], b["c"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
