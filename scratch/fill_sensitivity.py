"""Con so phu thuoc bao nhieu vao lua chon "khop tai gia mo"? — CHI DOC.

Phep sua dang dung: khi den luc vu trang ma gia da o ben kia muc stop, khop tai GIA MO
cua bar vu trang. Do la quy uoc engine dung cho GAP exit, nhung van la mot LUA CHON.

Quet bon gia dinh, tu nhe tay nhat den nang tay nhat:
  1 MUC STOP        — nhu mo phong dang lam (khong sua gi) = can tren
  2 GIUA            — giua muc stop va gia mo (coi nhu bat duoc nua duong)
  3 GIA MO          — dang dung
  4 CUC XAU CUA BAR — low (LONG) / high (SHORT) cua chinh bar vu trang = can duoi

Neu ket luan chi dung o gia dinh 3 thi no yeu. Neu no dung tu 2 den 4 thi lua chon
khong quyet dinh ket luan.
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
    print("da nap {} ma".format(len(dfs)))

    for tag, H in (("prod_backtest (quy uoc engine)", 0.0),
                   ("prod_live14h (luat live)", 14.0)):
        f = "scratch/calm_probe_" + ("prod_backtest" if H == 0.0 else "prod_live14h") + ".csv"
        d = pd.read_csv(f, parse_dates=["day", "exit_day"])
        et = pd.to_datetime(d["exit_time"], utc=True, errors="coerce")
        d["et"] = et.dt.tz_convert("America/New_York").dt.tz_localize(None)
        d["arm"] = d["day"] + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
        d["dmin"] = (d["et"] - d["arm"]).dt.total_seconds() / 60.0
        grp = d[(d.reason == "CHANDELIER")
                & (d.exit_day == d.day + pd.Timedelta(days=1))
                & (d.dmin >= 0) & (d.dmin < 1)].copy()

        tot = {k: 0.0 for k in ("stop", "giua", "mo", "xau")}
        n = 0
        for inst, g in grp.groupby("inst"):
            df = dfs[inst]
            idx = df.index.tz_convert("America/New_York").tz_localize(None)
            F = pd.DataFrame({"o": df["open"].to_numpy(), "h": df["high"].to_numpy(),
                              "l": df["low"].to_numpy()}, index=idx)
            F = F[~F.index.duplicated(keep="last")]
            pv = BASKET[inst].point_value
            for _, r in g.iterrows():
                try:
                    b = F.loc[r["et"]]
                except KeyError:
                    continue
                stp = float(r["exit"])
                op = float(b["o"])
                ext = float(b["l"]) if r["direction"] == "LONG" else float(b["h"])
                w_mo = (stp - op) if r["direction"] == "LONG" else (op - stp)
                if w_mo <= 0:
                    continue
                w_xau = (stp - ext) if r["direction"] == "LONG" else (ext - stp)
                n += 1
                tot["stop"] += 0.0
                tot["giua"] += 0.5 * w_mo * pv
                tot["mo"] += w_mo * pv
                tot["xau"] += max(w_xau, w_mo) * pv

        base = d["pnl"].sum()
        print("\n=== {} ===".format(tag))
        print("  tong {} lenh, P&L mo phong ${:,.0f} | so lenh bi anh huong {}"
              .format(len(d), base, n))
        for k, nm in (("stop", "1 khop tai MUC STOP (nhu hien nay)"),
                      ("giua", "2 khop GIUA stop va gia mo"),
                      ("mo", "3 khop tai GIA MO  (dang dung)"),
                      ("xau", "4 khop tai CUC XAU cua bar")):
            print("  {:<36} tru ${:>9,.0f}  ->  P&L ${:>10,.0f}"
                  .format(nm, tot[k], base - tot[k]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
