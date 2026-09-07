"""Duong gia CA HAI NGAY quanh mot lenh: ngay vao lenh va ngay engine ghi thoat. — CHI DOC.

    python scratch/verify_two_days.py --inst MNQ --date 2022-05-12
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
    ap.add_argument("--inst", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    a = ap.parse_args()

    from futures.basket import BASKET
    from futures.swing_tf import load_basket

    d = pd.read_csv("scratch/calm_probe_prod_backtest.csv",
                    parse_dates=["day", "exit_day"])
    row = d[(d.inst == a.inst) & (d.day == pd.Timestamp(a.date))]
    if row.empty:
        print("khong tim thay lenh")
        return 1
    r = row.iloc[0]
    et = pd.to_datetime(r["entry_time"], utc=True).tz_convert("America/New_York").tz_localize(None)
    xt = pd.to_datetime(r["exit_time"], utc=True).tz_convert("America/New_York").tz_localize(None)
    stop = float(r["exit"])
    entry = float(r["entry"])
    pv = BASKET[a.inst].point_value

    df = load_basket(a.data_dir)[a.inst]
    idx = df.index.tz_convert("America/New_York").tz_localize(None)
    F = pd.DataFrame({"o": df["open"].to_numpy(), "h": df["high"].to_numpy(),
                      "l": df["low"].to_numpy(), "c": df["close"].to_numpy()}, index=idx)
    F = F[~F.index.duplicated(keep="last")]

    d0 = pd.Timestamp(a.date).normalize()
    d1 = pd.Timestamp(r["exit_day"]).normalize()

    print("\n{} {} | vao {} @ {:.2f} | muc stop {:.2f} | engine ghi thoat {} @ {:.2f}"
          .format(a.inst, r["direction"], et, entry, stop, xt, stop))

    for dd, nhan in ((d0, "NGAY VAO LENH"), (d1, "NGAY ENGINE GHI THOAT")):
        seg = F[(F.index >= dd) & (F.index < dd + pd.Timedelta(days=1))]
        if seg.empty:
            continue
        print("\n=== {} — {} ===".format(nhan, dd.date()))
        print("   cao nhat {:.2f} | thap nhat {:.2f}".format(seg["h"].max(), seg["l"].min()))
        hh = seg.resample("60min").agg({"o": "first", "h": "max", "l": "min",
                                        "c": "last"}).dropna()
        for t, b in hh.iterrows():
            mark = ""
            if dd == d0 and t < et.floor("60min"):
                mark = "   (truoc khi vao lenh)"
            elif r["direction"] == "SHORT" and b["h"] >= stop:
                mark = "   <-- da VUOT muc stop"
            elif r["direction"] == "LONG" and b["l"] <= stop:
                mark = "   <-- da VUOT muc stop"
            print("     {}  O {:>10.2f} H {:>10.2f} L {:>10.2f} C {:>10.2f}{}"
                  .format(t.strftime("%H:%M"), b["o"], b["h"], b["l"], b["c"], mark))

    aft = F[F.index > et]
    if r["direction"] == "SHORT":
        cr = aft[aft["h"] >= stop]
    else:
        cr = aft[aft["l"] <= stop]
    print("\n=== MOC THOI GIAN ===")
    print("  vao lenh                        : {}  @ {:.2f}".format(et, entry))
    if len(cr):
        t0 = cr.index[0]
        print("  gia CHAM muc stop lan dau       : {}  ({:.0f} phut sau khi vao lenh)"
              .format(t0, (t0 - et).total_seconds() / 60.0))
        print("     -> nhung engine KHONG xet stop trong ngay vao lenh, nen bo qua")
    print("  engine bat dau xet stop         : {} (ranh gioi ngay ke tiep)".format(d1))
    b0 = F[(F.index >= d1)].iloc[0]
    print("  gia luc do                      : {:.2f}  (cach muc stop {:.2f} diem)"
          .format(float(b0["o"]), abs(float(b0["o"]) - stop)))
    print("\n=== HAI CACH TINH ===")
    loss_model = abs(stop - entry) * pv
    loss_real = abs(float(b0["o"]) - entry) * pv
    print("  engine ghi   : thoat @ {:.2f} -> lo {:.2f} diem = ${:,.0f}  (P&L so: ${})"
          .format(stop, abs(stop - entry), loss_model, r["pnl"]))
    print("  neu stop CO tren san tu luc khop: cung thoat @ {:.2f} -> lo ${:,.0f}  (GIONG HET)"
          .format(stop, loss_model))
    print("  neu KHONG co stop toi ranh gioi ngay (dung luat engine dang dung):")
    print("     thoat @ {:.2f} -> lo {:.2f} diem = ${:,.0f}"
          .format(float(b0["o"]), abs(float(b0["o"]) - entry), loss_real))
    print("\n  => engine lay LUAT THOI GIAN cua phuong an 3, nhung lay GIA KHOP cua phuong an 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
