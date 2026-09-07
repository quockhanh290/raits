"""Fill lac quan bao nhieu khi stop len san vao thi truong DA xuyen qua muc? — CHI DOC.

36% so lenh thoat ngay trong 5 phut dau sau moc vu trang 14:00 cua D+1. Voi nhung lenh do,
thi truong da o ben kia muc stop TRUOC khi lenh STP duoc dat. Live: STP dat vao thi truong
da xuyen qua = tro thanh lenh thi truong, khop o gia hien hanh. Mo phong: khop o MUC STOP.

Do do lech bang chinh quy uoc engine dang dung cho GAP exit: gia khop thuc te ~ GIA MO cua
thanh bar tai moc vu trang. Chi tinh nhung lenh ma gia mo DA o ben kia muc stop.

    python scratch/act_fill_gap.py --data-dir data/cache/futures/frozen_sim
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

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

    S = Path("scratch")
    for tag in ("prod_live14h", "calm_live14h"):
        d = pd.read_csv(S / ("calm_probe_" + tag + ".csv"), parse_dates=["day", "exit_day"])
        et = pd.to_datetime(d["exit_time"], utc=True, errors="coerce")
        d["et"] = et.dt.tz_convert("America/New_York").dt.tz_localize(None)
        d["act"] = d["day"] + pd.Timedelta(days=1) + pd.Timedelta(hours=14)
        d["dmin"] = (d["et"] - d["act"]).dt.total_seconds() / 60.0
        grp = d[(d["reason"] == "CHANDELIER")
                & (d["exit_day"] == d["day"] + pd.Timedelta(days=1))
                & (d["dmin"] >= 0) & (d["dmin"] <= 5)].copy()

        rows = []
        for inst, g in grp.groupby("inst"):
            df = dfs[inst]
            idx = df.index.tz_convert("America/New_York").tz_localize(None)
            look = pd.Series(df["open"].to_numpy(), index=idx)
            look = look[~look.index.duplicated(keep="last")]
            pv = BASKET[inst].point_value
            for _, r in g.iterrows():
                try:
                    op = float(look.loc[r["et"]])
                except KeyError:
                    continue
                stp = float(r["exit"])
                # LONG thoat = ban: khop thap hon muc stop la te hon
                worse = (stp - op) if r["direction"] == "LONG" else (op - stp)
                if worse <= 0:
                    continue          # gia mo chua xuyen qua -> fill tai stop la hop ly
                rows.append(dict(inst=inst, pv=pv, pts=worse, usd=worse * pv,
                                 pnl=r["pnl"], year=r["day"].year))

        R = pd.DataFrame(rows)
        tot = d["pnl"].sum()
        print("\n=== {} ===".format(tag))
        print("  tong lenh {}  | P&L mo phong ${:,.0f}".format(len(d), tot))
        print("  nhom thoat sat moc vu trang: {} lenh".format(len(grp)))
        if R.empty:
            print("  KHONG lenh nao co gia mo xuyen qua muc stop -> fill khong lac quan")
            continue
        print("  trong do gia MO da o ben kia muc stop: {} lenh ({:.1f}% tong lenh)".format(
            len(R), len(R) / max(len(d), 1) * 100))
        print("  do lech fill: trung vi ${:,.2f} | tb ${:,.2f} | p95 ${:,.2f} | max ${:,.2f}".format(
            R["usd"].median(), R["usd"].mean(), R["usd"].quantile(0.95), R["usd"].max()))
        print("  TONG lac quan = ${:,.0f}  = {:.1f}% cua P&L mo phong".format(
            R["usd"].sum(), R["usd"].sum() / abs(tot) * 100))
        print("  P&L sau khi tru = ${:,.0f}".format(tot - R["usd"].sum()))
        print("  -- theo ma --")
        for inst, s in R.groupby("inst"):
            print("     {:<5} {:>4} lenh  ${:>9,.0f}".format(inst, len(s), s["usd"].sum()))
        print("  -- theo nam --")
        for y, s in R.groupby("year"):
            print("     {}  {:>4} lenh  ${:>9,.0f}".format(y, len(s), s["usd"].sum()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
