"""scratch/stocks_stage0_peshort_clean_cal_20260826.py — PE_SHORT trên LỊCH SẠCH. CHỈ ĐỌC.

Hai phép đo, phép thứ nhất rẻ và sắc hơn phép thứ hai.

1. **Tách 43 lệnh cũ theo việc ngày của chúng có phải ngày phản ứng thật không.**
   Không cần chạy lại gì: lấy đúng tập lệnh đã đo, gắn nhãn "ngày trong lịch cũ TRÙNG ngày
   phản ứng Yahoo" hay không, rồi so hai nhóm. Nếu giả thuyết "lịch bẩn kéo xuống" đúng thì
   nhóm trùng phải tốt hơn nhóm không trùng. Đây là phép kiểm trực tiếp và nó dùng đúng dữ
   liệu đã có.

2. **Chạy lại toàn bộ luật trên lịch Yahoo**, trên bar 5 phút 2017-2022. Lịch Yahoo có ngày
   khác, nên đây là một tập lệnh khác, không phải cùng tập được gắn nhãn lại.

Cả hai đo trên bar 5 phút Polygon — cùng nguồn, cùng khung, cùng giai đoạn với con số nền
(43 lệnh, thắng 74,4%, R +0,320). Chỉ LỊCH đổi.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scratch import stocks_stage0_data_20260826 as D                        # noqa: E402
from scratch.stocks_stage0_bootstrap_20260826 import cluster_bootstrap      # noqa: E402
from scratch.stocks_stage0_peshort_20260826 import load_full, simulate      # noqa: E402

OUT = HERE / "_stocks_stage0_peshort_clean_cal.json"
OLD = ROOT / "raits" / "data" / "cache" / "earnings_dates_expanded.json"
NEW = HERE / "_stocks_stage0_earnings_yahoo.json"
EVENTS = HERE / "_stocks_stage0_peshort_events.csv"
GAP_MIN = 0.05


def summ(df, label, col="r_multiple", boot=True):
    if df.empty:
        print("  {:38s} 0 lệnh".format(label))
        return {"n": 0}
    o = dict(n=int(len(df)), days=int(df["entry_day"].nunique()),
             win=round(float((df[col] > 0).mean() * 100), 1),
             mean_r=round(float(df[col].mean()), 3),
             total_r=round(float(df[col].sum()), 1))
    if boot and df["entry_day"].nunique() >= 15:
        b = cluster_bootstrap(pd.DataFrame({"entry_day": df["entry_day"],
                                            "net_pnl": df[col]}), n_boot=20000)
        o["p"] = b.get("p_one_sided_vs_centred_null")
        o["ci95"] = [b.get("boot_ci95_low"), b.get("boot_ci95_high")]
    print("  {:38s} {:>4d} lệnh /{:>4d} ngày  thắng {:>5.1f}%  R {:>+6.3f}  tổng {:>+6.1f}"
          "  p={}".format(label, o["n"], o["days"], o["win"], o["mean_r"], o["total_r"],
                          o.get("p", "n nhỏ")))
    return o


def main() -> int:
    t0 = time.time()
    if not NEW.exists():
        print("chưa có lịch Yahoo:", NEW)
        return 2
    newcal = {t: {pd.Timestamp(x).normalize() for x in ds}
              for t, ds in json.loads(NEW.read_text(encoding="utf-8")).items()}
    rep: dict = {}

    # ══════════════════════════════ 1. gắn nhãn tập lệnh cũ ══════════════════════════
    ev = pd.read_csv(EVENTS)
    s = ev[ev["gap_rth"] < -GAP_MIN].copy()
    s["clean"] = [pd.Timestamp(d) in newcal.get(t, set())
                  for t, d in zip(s["ticker"], s["entry_day"])]
    print("=== 1 · TÁCH {} LỆNH CŨ THEO ĐỘ SẠCH CỦA NGÀY ===".format(len(s)))
    rep["old_all"] = summ(s, "tất cả (lịch 8-K đang dùng)")
    rep["old_clean"] = summ(s[s["clean"]], "ngày TRÙNG ngày phản ứng Yahoo")
    rep["old_dirty"] = summ(s[~s["clean"]], "ngày KHÔNG trùng")
    print()
    print("  tỉ lệ ngày sạch trong 43 lệnh: {}/{} = {:.0f}%".format(
        int(s["clean"].sum()), len(s), 100 * s["clean"].mean()))

    # ══════════════════════════════ 2. chạy lại trên lịch Yahoo ══════════════════════
    print()
    print("=== 2 · CHẠY LẠI TOÀN BỘ LUẬT TRÊN LỊCH YAHOO (bar 5 phút 2017-2022) ===")
    cal = [d for d in D.calendar("SPY")
           if pd.Timestamp("2017-01-03") <= d <= pd.Timestamp("2022-12-30")]
    cal_idx = pd.DatetimeIndex(cal)
    calset = set(cal_idx)
    rows = []
    for i, (tk, dates) in enumerate(sorted(newcal.items()), 1):
        evs = sorted(d for d in dates if d in calset)
        if not evs:
            continue
        need = set()
        for e in evs:
            pos = int(cal_idx.searchsorted(e))
            for k in range(max(0, pos - 40), min(len(cal_idx), pos + 3)):
                need.add(cal_idx[k])
        full = load_full(tk, sorted(need))
        if full.empty:
            continue
        for e in evs:
            r = simulate(full, e)
            if r:
                r["ticker"] = tk
                rows.append(r)
        if i % 10 == 0:
            print("  ...{}/{} mã ({:.0f}s)".format(i, len(newcal), time.time() - t0),
                  flush=True)
    yv = pd.DataFrame(rows)
    rep["yahoo_events_simulated"] = int(len(yv))
    print()
    print("  sự kiện dựng được trên lịch Yahoo: {}".format(len(yv)))
    if not yv.empty:
        ys = yv[yv["gap_rth"] < -GAP_MIN].copy()
        rep["yahoo_at_5pct"] = summ(ys, "lịch Yahoo · ngưỡng −5%")
        ys["yr"] = pd.to_datetime(ys["entry_day"]).dt.year
        print()
        print("  từng năm:")
        for y, g in ys.groupby("yr"):
            print("    {}  {:>3d} lệnh  thắng {:>5.1f}%  R {:>+6.3f}  tổng {:>+5.1f}".format(
                y, len(g), 100 * (g["r_multiple"] > 0).mean(), g["r_multiple"].mean(),
                g["r_multiple"].sum()))
        rep["yahoo_by_year"] = {int(y): dict(n=int(len(g)),
                                             mean_r=round(float(g["r_multiple"].mean()), 3),
                                             total_r=round(float(g["r_multiple"].sum()), 2))
                                for y, g in ys.groupby("yr")}
        print()
        print("  tách đôi giai đoạn:")
        for nm, sub in (("2017-2019", ys[ys["yr"] <= 2019]), ("2020-2022", ys[ys["yr"] >= 2020])):
            rep["yahoo_" + nm] = summ(sub, "  " + nm, boot=False)
        ys.to_csv(HERE / "_stocks_stage0_peshort_yahoo_events.csv", index=False)

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print()
    print("đã ghi", OUT, "({:.0f}s)".format(time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
