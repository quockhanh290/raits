"""scratch/stocks_stage0_peshort_yahoo_oos_20260828.py — PE_SHORT ngoài mẫu 2023-2024 bằng
bar NGÀY Yahoo. CHỈ ĐỌC (chỉ ghi vào scratch/).

Vì sao đường này đi được, còn Databento thì không
--------------------------------------------------
Bar ngày Databento có `open`/`close` gồm phiên ngoài giờ, nên gap ngày công bố bị nén hai lần
và bộ lọc −5% không nổ đúng. Bar ngày Yahoo là **phiên chính thức**.

Nhưng đó là một khẳng định, không phải phép đo — nên nó được KIỂM trước khi dùng, và kiểm
được vì Yahoo có lịch sử về tới 2002, tức **chồng lấn với 2017-2022** nơi đã có sự thật bar
5 phút Polygon. Databento không có một phiên nào chồng lấn, đó mới là lý do nó không cứu được.

Ba bước, và bước 3 chỉ chạy nếu bước 2 đạt
-------------------------------------------
1. Tải bar ngày Yahoo 2016-2025 cho 62 mã (auto_adjust: chia tách + cổ tức, cùng cơ sở với
   cache Polygon).
2. **Hiệu chuẩn**: so gap Yahoo với gap dựng từ bar 5 phút Polygon, trên đúng những ngày
   công bố 2017-2022. Ngưỡng đặt TRƯỚC: lệch trung vị < 0,15 điểm phần trăm VÀ số ngày qua
   ngưỡng −5% lệch dưới 15%. Không đạt thì dừng, không báo cáo số ngoài mẫu.
3. Chạy luật NGUYÊN VẸN trên 2023-01-01..2024-12-19 với lịch Yahoo sạch.

Cửa sổ ngoài mẫu này chưa từng được đo bằng lịch sạch. Bản chạy sản xuất trước đó dùng lịch
8-K và ra 22 lệnh, p=0,185 — mà chính phân tích sức mạnh khi đó nói cần ~49 lệnh mới đủ 80%
sức mạnh. Lịch sạch làm gấp ~3 lần số lần kích hoạt trong mẫu, nên đây là lần đầu phép kiểm
ngoài mẫu có cơ hội nói được điều gì.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scratch import stocks_stage0_data_20260826 as D                        # noqa: E402
from scratch.stocks_stage0_bootstrap_20260826 import cluster_bootstrap      # noqa: E402

OUT = HERE / "_stocks_stage0_peshort_yahoo_oos.json"
PRICES = HERE / "_stocks_stage0_yahoo_daily.parquet"
CAL = HERE / "_stocks_stage0_earnings_yahoo.json"

GAP_MIN, STOP_MULT, TARGET_RR, ATR_N = 0.05, 1.5, 2.0, 14
IS_A, IS_B = "2017-01-03", "2022-12-30"
OOS_A, OOS_B = "2023-01-01", "2024-12-19"

#: Cam kết TRƯỚC khi nhìn kết quả hiệu chuẩn.
CAL_MEDIAN_ABS_DIFF_MAX = 0.0015      # 0,15 điểm phần trăm
CAL_COUNT_REL_DIFF_MAX = 0.15         # số ngày qua ngưỡng lệch dưới 15%


def pull_daily(tickers, start="2016-06-01", end="2025-01-15") -> pd.DataFrame:
    import yfinance as yf
    frames = []
    B = 8
    for i in range(0, len(tickers), B):
        chunk = tickers[i:i + B]
        for attempt in range(3):
            try:
                d = yf.download(chunk, start=start, end=end, auto_adjust=True,
                                progress=False, group_by="ticker", threads=False)
                break
            except Exception:
                d = None
                time.sleep(4 * (attempt + 1))
        if d is None or d.empty:
            print("  lỗi lô", chunk, flush=True)
            continue
        for t in chunk:
            try:
                sub = d[t] if isinstance(d.columns, pd.MultiIndex) else d
                sub = sub.dropna(subset=["Open", "Close"])
                if sub.empty:
                    continue
                f = pd.DataFrame({"open": sub["Open"], "high": sub["High"],
                                  "low": sub["Low"], "close": sub["Close"],
                                  "volume": sub["Volume"]})
                f.index = pd.DatetimeIndex(f.index).tz_localize(None).normalize()
                f["symbol"] = t
                frames.append(f.reset_index().rename(columns={"index": "date",
                                                              "Date": "date"}))
            except Exception:
                continue
        print("  ...{}/{} mã ({} lô)".format(min(i + B, len(tickers)), len(tickers),
                                             i // B + 1), flush=True)
        time.sleep(1.5)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_events(px: pd.DataFrame, cal: dict, a: str, b: str) -> pd.DataFrame:
    rows = []
    for t, g in px.groupby("symbol"):
        gg = g.sort_values("date").reset_index(drop=True)
        days = cal.get(t, set())
        pc = gg["close"].shift(1)
        tr = pd.concat([gg["high"] - gg["low"], (gg["high"] - pc).abs(),
                        (gg["low"] - pc).abs()], axis=1).max(axis=1)
        atr = tr.shift(1).rolling(ATR_N).mean()
        for i in range(ATR_N + 2, len(gg) - 1):
            day = gg["date"].iloc[i]
            if not (pd.Timestamp(a) <= day <= pd.Timestamp(b)) or day not in days:
                continue
            o, p0, A = gg["open"].iloc[i], pc.iloc[i], atr.iloc[i]
            if not np.isfinite(A) or A <= 0 or not np.isfinite(p0) or p0 <= 0:
                continue
            gap = o / p0 - 1.0
            stop, target = round(o + STOP_MULT * A, 2), round(o - TARGET_RR * STOP_MULT * A, 2)
            ex, why = None, None
            for k in (i, i + 1):
                hi, lo = gg["high"].iloc[k], gg["low"].iloc[k]
                if hi >= stop:
                    ex, why = stop, "STOP_HIT"; break
                if lo <= target:
                    ex, why = target, "TARGET_HIT"; break
            if ex is None:
                ex, why = gg["close"].iloc[i + 1], "EOD"
            rows.append(dict(ticker=t, entry_day=str(day.date()), open=float(o), gap=gap,
                             atr=float(A), exit=float(ex), reason=why,
                             r_multiple=(o - ex) / (STOP_MULT * A),
                             pnl_pct=(o - ex) / o))
    return pd.DataFrame(rows)


def summ(df, label, boot=True):
    if df.empty:
        print("  {:36s} 0 lệnh".format(label)); return {"n": 0}
    o = dict(n=int(len(df)), days=int(df["entry_day"].nunique()),
             win=round(float((df["r_multiple"] > 0).mean() * 100), 1),
             mean_r=round(float(df["r_multiple"].mean()), 3),
             total_r=round(float(df["r_multiple"].sum()), 1),
             mean_bps=round(float(df["pnl_pct"].mean() * 1e4), 1))
    if boot and df["entry_day"].nunique() >= 15:
        b = cluster_bootstrap(pd.DataFrame({"entry_day": df["entry_day"],
                                            "net_pnl": df["r_multiple"]}), n_boot=20000)
        o["p"] = b.get("p_one_sided_vs_centred_null")
        o["ci95"] = [b.get("boot_ci95_low"), b.get("boot_ci95_high")]
    print("  {:36s} {:>4d} lệnh /{:>4d} ngày  thắng {:>5.1f}%  R {:>+6.3f}  tổng {:>+6.1f}"
          "  biên {:>+6.1f}bps  p={}".format(label, o["n"], o["days"], o["win"], o["mean_r"],
                                             o["total_r"], o["mean_bps"], o.get("p", "n nhỏ")))
    return o


def main() -> int:
    t0 = time.time()
    cal = {t: {pd.Timestamp(x) for x in ds}
           for t, ds in json.loads(CAL.read_text(encoding="utf-8")).items()}
    tickers = sorted(cal)
    rep: dict = {}

    if PRICES.exists():
        px = pd.read_parquet(PRICES)
        print("dùng lại bar ngày Yahoo đã tải:", len(px), "dòng")
    else:
        print("tải bar ngày Yahoo cho {} mã ...".format(len(tickers)), flush=True)
        px = pull_daily(tickers)
        if px.empty:
            print("không tải được"); return 2
        px.to_parquet(PRICES, index=False)
    px["date"] = pd.to_datetime(px["date"])
    print("  {:,} dòng, {} mã, {} .. {}".format(len(px), px["symbol"].nunique(),
                                                px["date"].min().date(),
                                                px["date"].max().date()))

    # ═══════════════════ 2. HIỆU CHUẨN trên 2017-2022, đối chiếu bar 5 phút Polygon
    print()
    print("=== HIỆU CHUẨN · gap Yahoo(ngày) vs gap Polygon(5 phút), ngày công bố 2017-2022 ===")
    pcal = [d for d in D.calendar("SPY")
            if pd.Timestamp(IS_A) <= d <= pd.Timestamp(IS_B)]
    pset = set(pd.DatetimeIndex(pcal))
    pairs = []
    for t in tickers:
        days = sorted(d for d in cal[t] if d in pset)
        if not days:
            continue
        df5 = D.load_symbol(t, pcal)
        if df5.empty:
            continue
        dd = D.daily_from_5m(df5)
        pgap = dd["open"] / dd["close"].shift(1) - 1.0
        y = px[px["symbol"] == t].set_index("date")
        ygap = y["open"] / y["close"].shift(1) - 1.0
        for d in days:
            a_, b_ = pgap.get(d, np.nan), ygap.get(d, np.nan)
            if np.isfinite(a_) and np.isfinite(b_):
                pairs.append((t, d, float(a_), float(b_)))
    cmp = pd.DataFrame(pairs, columns=["ticker", "day", "polygon", "yahoo"])
    diff = (cmp["yahoo"] - cmp["polygon"]).abs()
    n_p = int((cmp["polygon"] < -GAP_MIN).sum())
    n_y = int((cmp["yahoo"] < -GAP_MIN).sum())
    rel = abs(n_y - n_p) / max(n_p, 1)
    rep["calibration"] = dict(n_pairs=int(len(cmp)),
                              median_abs_diff=round(float(diff.median()), 6),
                              p90_abs_diff=round(float(diff.quantile(0.9)), 6),
                              n_below_threshold_polygon=n_p, n_below_threshold_yahoo=n_y,
                              rel_count_diff=round(rel, 4),
                              gate_median=CAL_MEDIAN_ABS_DIFF_MAX,
                              gate_count=CAL_COUNT_REL_DIFF_MAX)
    print("  cặp so được            : {:,}".format(len(cmp)))
    print("  lệch |gap| trung vị    : {:.4f} điểm %   (ngưỡng {:.2f})".format(
        diff.median() * 100, CAL_MEDIAN_ABS_DIFF_MAX * 100))
    print("  lệch p90               : {:.4f} điểm %".format(diff.quantile(0.9) * 100))
    print("  số ngày qua −5%        : Polygon {}  ·  Yahoo {}  (lệch {:.1%}, ngưỡng {:.0%})"
          .format(n_p, n_y, rel, CAL_COUNT_REL_DIFF_MAX))
    ok = (diff.median() < CAL_MEDIAN_ABS_DIFF_MAX) and (rel < CAL_COUNT_REL_DIFF_MAX)
    rep["calibration_passed"] = bool(ok)
    print()
    print(("  [ĐẠT] " if ok else "  [TRƯỢT] ") + "cổng hiệu chuẩn (cam kết trước khi nhìn)")
    if not ok:
        print("  -> KHÔNG báo cáo số ngoài mẫu. Bar ngày Yahoo không tái tạo được gap "
              "phiên chính thức ở mức cần thiết.")
        OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
        return 1

    # ═══════════════════ 3. trong mẫu (đối chứng) và NGOÀI MẪU
    print()
    print("=== KẾT QUẢ · luật nguyên vẹn, lịch Yahoo sạch ===")
    ins = build_events(px, cal, IS_A, IS_B)
    ins5 = ins[ins["gap"] < -GAP_MIN]
    rep["in_sample"] = summ(ins5, "TRONG MẪU 2017-2022 (đối chứng)")
    print("     (cùng luật trên bar 5 phút: 126 lệnh, thắng 68,3%, R +0,240)")
    oos = build_events(px, cal, OOS_A, OOS_B)
    oos5 = oos[oos["gap"] < -GAP_MIN]
    rep["oos"] = summ(oos5, "NGOÀI MẪU {}..{}".format(OOS_A, OOS_B))
    if not oos5.empty:
        oos5 = oos5.copy()
        oos5["yr"] = pd.to_datetime(oos5["entry_day"]).dt.year
        print()
        print("  từng năm:")
        for y, g in oos5.groupby("yr"):
            print("    {}  {:>3d} lệnh  thắng {:>5.1f}%  R {:>+6.3f}  tổng {:>+5.1f}".format(
                y, len(g), 100 * (g["r_multiple"] > 0).mean(), g["r_multiple"].mean(),
                g["r_multiple"].sum()))
        rep["oos_by_year"] = {int(y): dict(n=int(len(g)),
                                           mean_r=round(float(g["r_multiple"].mean()), 3))
                              for y, g in oos5.groupby("yr")}
        print()
        top3 = oos5.nlargest(3, "r_multiple")["r_multiple"].sum()
        print("  tập trung: 3 lệnh lớn nhất {:+.1f} R / {:+.1f} R tổng = {:.0f}%".format(
            top3, oos5["r_multiple"].sum(), 100 * top3 / oos5["r_multiple"].sum()))
        print("  lý do thoát:", oos5["reason"].value_counts().to_dict())
        oos5.to_csv(HERE / "_stocks_stage0_peshort_yahoo_oos_events.csv", index=False)

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print()
    print("đã ghi", OUT, "({:.0f}s)".format(time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
