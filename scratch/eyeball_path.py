"""Soi bang mat: gia co THAT SU da o ben kia muc stop truoc gio vu trang khong? — CHI DOC.

Khong tin bo phat hien cua toi thi doc thang duong gia. Voi vai lenh trong nhom bi sua,
in bar 1 phut quanh moc vu trang D+1 14:00 ET, kem muc stop ma mo phong dung de khop.

Neu gia da o ben kia muc stop tu lau truoc 14:00 thi co che la that, doc lap voi gia dinh
"khop tai gia mo". Neu khong, bo phat hien cua toi hong.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    from futures.basket import BASKET
    from futures.swing_tf import load_basket

    dfs = load_basket("data/cache/futures/frozen_sim")
    d = pd.read_csv("scratch/calm_probe_prod_live14h.csv",
                    parse_dates=["day", "exit_day"])
    et = pd.to_datetime(d["exit_time"], utc=True, errors="coerce")
    d["et"] = et.dt.tz_convert("America/New_York").dt.tz_localize(None)
    d["arm"] = d["day"] + pd.Timedelta(days=1) + pd.Timedelta(hours=14)
    d["dmin"] = (d["et"] - d["arm"]).dt.total_seconds() / 60.0
    cand = d[(d.reason == "CHANDELIER") & (d.exit_day == d.day + pd.Timedelta(days=1))
             & (d.dmin >= 0) & (d.dmin < 1)].copy()
    print("nhom thoat ngay tai bar vu trang: {} lenh".format(len(cand)))

    # chon 4 lenh: 2 lech lon nhat, 2 ngau nhien co dinh
    rows = []
    for _, r in cand.iterrows():
        inst = r["inst"]
        df = dfs[inst]
        idx = df.index.tz_convert("America/New_York").tz_localize(None)
        ser_o = pd.Series(df["open"].to_numpy(), index=idx)
        ser_o = ser_o[~ser_o.index.duplicated(keep="last")]
        try:
            op = float(ser_o.loc[r["et"]])
        except KeyError:
            continue
        stp = float(r["exit"])
        w = (stp - op) if r["direction"] == "LONG" else (op - stp)
        rows.append((w * BASKET[inst].point_value, r, op))
    rows.sort(key=lambda x: -x[0])
    pick = rows[:2] + rows[len(rows) // 2: len(rows) // 2 + 1] + rows[-1:]

    for lech, r, op in pick:
        inst = r["inst"]
        df = dfs[inst]
        idx = df.index.tz_convert("America/New_York").tz_localize(None)
        f = pd.DataFrame({"open": df["open"].to_numpy(), "high": df["high"].to_numpy(),
                          "low": df["low"].to_numpy(), "close": df["close"].to_numpy()},
                         index=idx)
        f = f[~f.index.duplicated(keep="last")]
        stp = float(r["exit"])
        arm = r["arm"]
        day1 = arm.normalize()
        seg = f[(f.index >= day1) & (f.index <= arm + pd.Timedelta(minutes=5))]
        if seg.empty:
            continue
        # lan dau tien gia xuyen qua muc stop trong ngay D+1
        if r["direction"] == "LONG":
            crossed = seg[seg["low"] <= stp]
        else:
            crossed = seg[seg["high"] >= stp]
        print("\n" + "=" * 88)
        print("{} {}  vao {} @ {}  | muc stop mo phong dung de khop = {}"
              .format(inst, r["direction"], r["day"].date(), r["entry"], stp))
        print("  gio vu trang (D+1 14:00 ET) = {}   | gia MO cua bar do = {}   | lech ${:,.2f}"
              .format(arm, op, lech))
        if len(crossed):
            first = crossed.index[0]
            print("  gia XUYEN QUA muc stop lan dau luc {}  -> truoc gio vu trang {:.0f} phut"
                  .format(first, (arm - first).total_seconds() / 60.0))
        else:
            print("  KHONG thay gia xuyen qua muc stop truoc gio vu trang (!!)")
        print("  duong gia ngay D+1 (lay mau moi 60 phut, va 3 bar quanh moc vu trang):")
        show = seg.resample("60min").agg({"open": "first", "high": "max",
                                          "low": "min", "close": "last"}).dropna()
        for t, b in show.iterrows():
            mark = ""
            if r["direction"] == "LONG" and b["low"] <= stp:
                mark = "  <-- da duoi muc stop"
            if r["direction"] == "SHORT" and b["high"] >= stp:
                mark = "  <-- da tren muc stop"
            print("     {}  O {:>9.2f} H {:>9.2f} L {:>9.2f} C {:>9.2f}{}"
                  .format(t.strftime("%H:%M"), b["open"], b["high"], b["low"],
                          b["close"], mark))
        near = seg[(seg.index >= arm - pd.Timedelta(minutes=2))
                   & (seg.index <= arm + pd.Timedelta(minutes=2))]
        print("  bar 1 phut quanh moc vu trang:")
        for t, b in near.iterrows():
            print("     {}  O {:>9.2f} H {:>9.2f} L {:>9.2f} C {:>9.2f}{}"
                  .format(t.strftime("%H:%M"), b["open"], b["high"], b["low"], b["close"],
                          "   <== BAR VU TRANG" if t == arm else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
