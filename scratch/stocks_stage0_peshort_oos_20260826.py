"""scratch/stocks_stage0_peshort_oos_20260826.py — PE_SHORT ngoài mẫu 2023-2024, và câu hỏi
điều kiện earnings có gánh việc không. CHỈ ĐỌC.

Ba phần, theo đúng thứ tự bắt buộc
-----------------------------------
A. **HIỆU CHUẨN PROXY.** Ngoài mẫu chỉ có bar NGÀY (Databento), trong mẫu có bar 5 phút
   (Polygon). Nếu đem thẳng kết quả bar ngày so với kết quả bar 5 phút thì hai thứ đổi cùng
   lúc: khung bar VÀ giai đoạn. Nên trước hết chạy CÙNG luật bằng bar ngày dựng từ chính dữ
   liệu 5 phút của 2017-2022, rồi so với sự thật 5 phút. Sai số đó là sai số của phép xấp xỉ,
   đo được, và nó phải nhỏ thì phần B mới đáng đọc.

B. **NGOÀI MẪU.** 2023-03-28 (ngày đầu của dữ liệu ngày) tới 2024-12-19 (ngày cuối của lịch
   earnings), 62 mã, ngưỡng −5% GIỮ NGUYÊN. Không tinh chỉnh gì.

C. **ĐIỀU KIỆN EARNINGS CÓ GÁNH VIỆC KHÔNG.** Trên 2017-2022, so gap < −5% RƠI VÀO ngày
   earnings với gap < −5% ở ngày thường. Nếu ngày thường cũng ăn thì rổ mở rộng được ngay mà
   không cần lịch earnings cho mã mới — đó là điều kiện để trả lời câu "mở rộng sàn thì sao".

Một giới hạn không xoá được, nói trước
---------------------------------------
Trong mẫu là Polygon bar 5 phút; ngoài mẫu là Databento bar ngày. **Hai nhà cung cấp và hai
khung bar cùng đổi**, và hai tập dữ liệu KHÔNG chồng nhau một phiên nào (Polygon hết
2022-12-30, Databento bắt đầu 2023-03-28) nên không thể đối chiếu chéo nhà cung cấp. Phần A
cô lập được khung bar; phần nhà cung cấp thì không, và kết quả phải đọc kèm điều đó.
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

OUT = HERE / "_stocks_stage0_peshort_oos.json"
EAR = ROOT / "raits" / "data" / "cache" / "earnings_dates_expanded.json"
DAILY = ROOT / "raits" / "data" / "cache" / "research_daily" / "databento_ohlcv1d.parquet"

GAP_MIN, STOP_MULT, TARGET_RR = 0.05, 1.5, 2.0
OOS_START, OOS_END = "2023-03-28", "2024-12-19"


def atr14(daily: pd.DataFrame, upto_pos: int, period: int = 14) -> float:
    """ATR trên `period` phiên KẾT THÚC TRƯỚC `upto_pos` — nhân quả theo cấu tạo."""
    if upto_pos < period + 1:
        return float("nan")
    d = daily.iloc[max(0, upto_pos - period - 1):upto_pos]
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def sim_daily(daily: pd.DataFrame, pos: int) -> "dict | None":
    """Một sự kiện, mô phỏng bằng bar NGÀY.

    Xấp xỉ duy nhất so với bản 5 phút: trong một ngày không biết stop hay target chạm trước.
    Khi cả hai cùng nằm trong biên độ ngày thì tính là STOP — hướng bảo thủ cho một lệnh bán
    khống — và số lần mập mờ được đếm riêng để biết phép xấp xỉ nặng tay tới đâu.
    """
    if pos < 20 or pos + 1 >= len(daily):
        return None
    row, prev = daily.iloc[pos], daily.iloc[pos - 1]
    opx, pc = float(row["open"]), float(prev["close"])
    if opx <= 0 or pc <= 0:
        return None
    gap = opx / pc - 1.0
    atr = atr14(daily, pos)
    if not np.isfinite(atr) or atr <= 0:
        return None
    stop = round(opx + STOP_MULT * atr, 2)
    target = round(opx - TARGET_RR * STOP_MULT * atr, 2)

    ambiguous = 0
    exit_px, reason = None, None
    for k in (pos, pos + 1):
        b = daily.iloc[k]
        hi, lo = float(b["high"]), float(b["low"])
        hit_stop, hit_tgt = hi >= stop, lo <= target
        if hit_stop and hit_tgt:
            ambiguous += 1
            exit_px, reason = stop, "STOP_HIT"
            break
        if hit_stop:
            exit_px, reason = stop, "STOP_HIT"
            break
        if hit_tgt:
            exit_px, reason = target, "TARGET_HIT"
            break
    if exit_px is None:
        exit_px, reason = float(daily.iloc[pos + 1]["close"]), "EOD"

    return dict(entry_day=str(pd.Timestamp(daily.index[pos]).date()), open=opx, atr=atr,
                gap=gap, stop=stop, target=target, exit=exit_px, reason=reason,
                ambiguous=ambiguous,
                r_multiple=(opx - exit_px) / (STOP_MULT * atr),
                pnl_pct=(opx - exit_px) / opx)


def summarise(df: pd.DataFrame, label: str, boot: bool = True) -> dict:
    if df.empty:
        print("  {:34s} 0 lệnh".format(label))
        return {"n": 0}
    out = dict(n=int(len(df)), entry_days=int(df["entry_day"].nunique()),
               win_pct=round(float((df["r_multiple"] > 0).mean() * 100), 1),
               mean_r=round(float(df["r_multiple"].mean()), 3),
               total_r=round(float(df["r_multiple"].sum()), 1),
               mean_pnl_bps=round(float(df["pnl_pct"].mean() * 1e4), 1))
    if boot and df["entry_day"].nunique() >= 15:
        b = cluster_bootstrap(pd.DataFrame({"entry_day": df["entry_day"],
                                            "net_pnl": df["r_multiple"]}), n_boot=20000)
        out["p"] = b.get("p_one_sided_vs_centred_null")
        out["ci95"] = [b.get("boot_ci95_low"), b.get("boot_ci95_high")]
    print("  {:34s} {:>4d} lệnh /{:>4d} ngày  thắng {:>5.1f}%  R {:>+6.3f}  tổng R {:>+6.1f}"
          "  biên {:>+6.1f}bps  p={}".format(
              label, out["n"], out["entry_days"], out["win_pct"], out["mean_r"],
              out["total_r"], out["mean_pnl_bps"], out.get("p", "n nhỏ")))
    return out


def main() -> int:
    t0 = time.time()
    rep: dict = {"note": "trong mẫu = Polygon 5 phút; ngoài mẫu = Databento bar ngày. "
                         "Hai nhà cung cấp và hai khung bar cùng đổi; không có phiên nào "
                         "chồng nhau để đối chiếu chéo."}
    ear = json.loads(EAR.read_text(encoding="utf-8"))
    ear_days = {t: {pd.Timestamp(str(x)[:10]).normalize() for x in ds}
                for t, ds in ear.items()}

    # ══════════════════════════════════════════════ A + C : trong mẫu, từ bar 5 phút
    cal = [d for d in D.calendar("SPY")
           if pd.Timestamp("2017-01-03") <= d <= pd.Timestamp("2022-12-30")]
    print("=== A/C · TRONG MẪU 2017-2022 (dựng bar ngày từ chính dữ liệu 5 phút) ===")
    rows = []
    for i, t in enumerate(D.universe(), 1):
        df5 = D.load_symbol(t, cal)
        if df5.empty:
            continue
        dd = D.daily_from_5m(df5)
        if len(dd) < 40:
            continue
        eset = ear_days.get(t, set())
        for pos in range(len(dd)):
            r = sim_daily(dd, pos)
            if r is None or r["gap"] >= -GAP_MIN:
                continue
            r["ticker"] = t
            r["is_earnings"] = pd.Timestamp(r["entry_day"]) in eset
            r["in_pe_universe"] = t in ear_days
            rows.append(r)
        if i % 15 == 0:
            print("  ...{} / {} mã ({:.0f}s)".format(i, len(D.universe()), time.time() - t0),
                  flush=True)
    ins = pd.DataFrame(rows)
    rep["in_sample_events"] = int(len(ins))

    print()
    pe_uni = ins[ins["in_pe_universe"]]
    a = summarise(pe_uni[pe_uni["is_earnings"]], "A· proxy ngày, 62 mã, earnings")
    rep["A_daily_proxy_earnings_62"] = a
    print("     (sự thật bar 5 phút cùng luật: 43 lệnh, thắng 74,4%, R +0,320, tổng R +13,7)")
    print()
    print("=== C · ĐIỀU KIỆN EARNINGS CÓ GÁNH VIỆC KHÔNG (cùng ngưỡng −5%) ===")
    rep["C_earnings_62"] = summarise(pe_uni[pe_uni["is_earnings"]], "62 mã · NGÀY earnings")
    rep["C_nonearnings_62"] = summarise(pe_uni[~pe_uni["is_earnings"]],
                                        "62 mã · ngày THƯỜNG")
    rep["C_nonearnings_all75"] = summarise(ins[~ins["is_earnings"]],
                                           "cả 75 mã · ngày THƯỜNG")
    rep["C_all_gaps_75"] = summarise(ins, "cả 75 mã · MỌI gap < −5%")
    print()
    print("  số lần mập mờ trong ngày (stop và target cùng nằm trong biên độ): {} / {}".format(
        int(ins["ambiguous"].sum()), len(ins)))

    # ══════════════════════════════════════════════ B : ngoài mẫu, bar ngày Databento
    print()
    print("=== B · NGOÀI MẪU {} .. {} (Databento bar ngày, 62 mã, ngưỡng GIỮ NGUYÊN) ==="
          .format(OOS_START, OOS_END))
    db = pd.read_parquet(DAILY, columns=["open", "high", "low", "close", "volume",
                                         "symbol", "date"])
    db["date"] = pd.to_datetime(db["date"])
    db = db[db["symbol"].isin(ear_days.keys())]
    orows = []
    for t, g in db.groupby("symbol"):
        gg = g.sort_values("date").drop_duplicates("date").set_index("date")
        eset = ear_days.get(t, set())
        for pos in range(len(gg)):
            day = pd.Timestamp(gg.index[pos]).normalize()
            if not (pd.Timestamp(OOS_START) <= day <= pd.Timestamp(OOS_END)):
                continue
            if day not in eset:
                continue
            r = sim_daily(gg, pos)
            if r is None or r["gap"] >= -GAP_MIN:
                continue
            r["ticker"] = t
            orows.append(r)
    oos = pd.DataFrame(orows)
    rep["oos_window"] = [OOS_START, OOS_END]
    n_ev = sum(1 for t, s in ear_days.items() for x in s
               if pd.Timestamp(OOS_START) <= x <= pd.Timestamp(OOS_END))
    rep["oos_earnings_events_available"] = int(n_ev)
    print("  sự kiện earnings trong cửa sổ ngoài mẫu: {}".format(n_ev))
    rep["B_oos"] = summarise(oos, "NGOÀI MẪU 62 mã · earnings")
    if not oos.empty:
        oos.to_csv(HERE / "_stocks_stage0_peshort_oos_events.csv", index=False)
        print()
        print("  từng năm:")
        oos["yr"] = pd.to_datetime(oos["entry_day"]).dt.year
        for y, g in oos.groupby("yr"):
            print("    {}  {:>3d} lệnh  thắng {:>5.1f}%  R {:>+6.3f}  tổng R {:>+5.1f}".format(
                y, len(g), 100 * (g["r_multiple"] > 0).mean(), g["r_multiple"].mean(),
                g["r_multiple"].sum()))

    ins.to_csv(HERE / "_stocks_stage0_peshort_insample_daily.csv", index=False)
    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print()
    print("đã ghi", OUT, "({:.0f}s)".format(time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
