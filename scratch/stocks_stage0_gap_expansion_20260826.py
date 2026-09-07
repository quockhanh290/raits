"""scratch/stocks_stage0_gap_expansion_20260826.py — luật gap xuống trên TOÀN thị trường Mỹ,
2023-2026. CHỈ ĐỌC.

Chạy phép đo này CHỈ KHI phần C của `stocks_stage0_peshort_oos_20260826.py` cho thấy điều kiện
earnings không gánh hết việc. Nếu edge chỉ sống ở ngày earnings thì mở rộng theo hướng này là
đo một luật khác và gọi nó bằng tên cũ.

Vì sao đây mới là "mở rộng", chứ không phải thêm sàn
-----------------------------------------------------
Dữ liệu ngày Databento trên đĩa có **17.861 mã**, 2023-03-28 → 2026-07-31 — gần như toàn bộ
thị trường Mỹ đã nằm sẵn đây. Cái thiếu chưa bao giờ là sàn; cái thiếu là **lịch earnings**,
chỉ có cho 62 mã và dừng ở 2024-12-19. Bỏ điều kiện earnings ra thì rổ nhảy từ 62 lên hàng
nghìn ngay lập tức, không tốn một đồng dữ liệu nào.

Cái giá của việc bỏ điều kiện đó là nó thành một luật khác, nên nó được đo như một luật khác:
đường cong ngưỡng riêng, thanh khoản riêng, và không mượn p-value của bản earnings.

Bộ lọc thanh khoản là bắt buộc ở đây, không phải tuỳ chọn
----------------------------------------------------------
17.861 mã gồm rất nhiều thứ không giao dịch được ở quy mô nào: giá dưới $5, khối lượng vài
nghìn cổ, mã vừa niêm yết. Một luật "gap xuống 5%" quét toàn bộ danh sách đó sẽ chủ yếu bắt
được rác, và rác thì có đủ mọi kiểu lợi suất trông hấp dẫn. Sàn giá và sàn giá trị giao dịch
được áp TRƯỚC khi đếm bất cứ thứ gì.
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

from scratch.stocks_stage0_bootstrap_20260826 import cluster_bootstrap      # noqa: E402

OUT = HERE / "_stocks_stage0_gap_expansion.json"
DAILY = ROOT / "raits" / "data" / "cache" / "research_daily" / "databento_ohlcv1d.parquet"

STOP_MULT, TARGET_RR = 1.5, 2.0
MIN_PRICE = 5.0
MIN_ADV_USD = 20_000_000.0
ATR_N = 14


def main() -> int:
    t0 = time.time()
    print("nạp bar ngày ...", flush=True)
    db = pd.read_parquet(DAILY, columns=["open", "high", "low", "close", "volume",
                                         "symbol", "date"])
    db["date"] = pd.to_datetime(db["date"])
    db = db.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"])
    print("  {:,} dòng, {:,} mã, {} .. {}  ({:.0f}s)".format(
        len(db), db["symbol"].nunique(), db["date"].min().date(), db["date"].max().date(),
        time.time() - t0), flush=True)

    g = db.groupby("symbol", sort=False)
    db["prev_close"] = g["close"].shift(1)
    db["gap"] = db["open"] / db["prev_close"] - 1.0

    # ATR(14) nhân quả: True Range của các phiên TRƯỚC phiên đang xét.
    pc = db["prev_close"]
    tr = pd.concat([db["high"] - db["low"], (db["high"] - pc).abs(),
                    (db["low"] - pc).abs()], axis=1).max(axis=1)
    db["atr"] = g.apply(lambda x: pd.Series(index=x.index, dtype=float)) \
        if False else tr.groupby(db["symbol"]).transform(
            lambda s: s.shift(1).rolling(ATR_N).mean())

    # Thanh khoản, cũng nhân quả: trung vị 20 phiên trước, dịch một phiên.
    dv = db["close"] * db["volume"]
    db["adv"] = dv.groupby(db["symbol"]).transform(
        lambda s: s.shift(1).rolling(20, min_periods=10).median())

    # Ngày sau, để tính lối thoát hai phiên.
    for c in ("high", "low", "close"):
        db["n_" + c] = g[c].shift(-1)

    print("  đã dựng đặc trưng ({:.0f}s)".format(time.time() - t0), flush=True)

    ok = (db["gap"].notna() & db["atr"].notna() & (db["atr"] > 0) & db["adv"].notna()
          & (db["open"] >= MIN_PRICE) & (db["adv"] >= MIN_ADV_USD) & db["n_close"].notna())
    ev = db[ok & (db["gap"] < 0)].copy()
    print("  sự kiện gap xuống qua sàn thanh khoản: {:,}".format(len(ev)), flush=True)

    risk = STOP_MULT * ev["atr"]
    stop = (ev["open"] + risk).round(2)
    target = (ev["open"] - TARGET_RR * risk).round(2)

    d0_stop = ev["high"] >= stop
    d0_tgt = ev["low"] <= target
    d1_stop = ev["n_high"] >= stop
    d1_tgt = ev["n_low"] <= target

    exit_px = ev["n_close"].astype(float).copy()
    reason = pd.Series("EOD", index=ev.index)
    # Ngày D+1 trước, rồi ghi đè bằng ngày D — để ngày D thắng khi cả hai cùng chạm.
    m = d1_tgt & ~d1_stop
    exit_px[m], reason[m] = target[m], "TARGET_HIT"
    m = d1_stop
    exit_px[m], reason[m] = stop[m], "STOP_HIT"
    m = d0_tgt & ~d0_stop
    exit_px[m], reason[m] = target[m], "TARGET_HIT"
    m = d0_stop                       # mập mờ trong ngày -> tính STOP (bảo thủ cho lệnh bán)
    exit_px[m], reason[m] = stop[m], "STOP_HIT"

    ev["exit"] = exit_px
    ev["reason"] = reason
    ev["r_multiple"] = (ev["open"] - ev["exit"]) / risk
    ev["pnl_pct"] = (ev["open"] - ev["exit"]) / ev["open"]
    ev["entry_day"] = ev["date"].dt.strftime("%Y-%m-%d")
    ev["ambiguous"] = (d0_stop & d0_tgt) | (d1_stop & d1_tgt)

    rep: dict = {"window": [str(db["date"].min().date()), str(db["date"].max().date())],
                 "symbols_total": int(db["symbol"].nunique()),
                 "min_price": MIN_PRICE, "min_adv_usd": MIN_ADV_USD,
                 "down_gap_events_liquid": int(len(ev)),
                 "ambiguous_pct": round(float(ev["ambiguous"].mean() * 100), 1),
                 "note": "luật gap KHÔNG điều kiện earnings — một luật khác với PE_SHORT, "
                         "đo riêng, không mượn p-value của bản earnings"}

    print()
    print("=== ĐƯỜNG CONG NGƯỠNG · TOÀN THỊ TRƯỜNG, KHÔNG ĐIỀU KIỆN EARNINGS ===")
    print("  {:>7s} {:>9s} {:>7s} {:>7s} {:>9s} {:>10s} {:>9s} {:>8s}".format(
        "ngưỡng", "lệnh", "ngày", "mã", "thắng%", "R tr.bình", "biên bps", "p"))
    curve = []
    for thr in (0.03, 0.05, 0.07, 0.10, 0.15, 0.20):
        s = ev[ev["gap"] < -thr]
        if len(s) < 10:
            continue
        b = cluster_bootstrap(pd.DataFrame({"entry_day": s["entry_day"],
                                            "net_pnl": s["r_multiple"]}), n_boot=5000)
        row = dict(threshold=thr, n=int(len(s)), days=int(s["entry_day"].nunique()),
                   symbols=int(s["symbol"].nunique()),
                   win_pct=round(float((s["r_multiple"] > 0).mean() * 100), 1),
                   mean_r=round(float(s["r_multiple"].mean()), 4),
                   mean_bps=round(float(s["pnl_pct"].mean() * 1e4), 1),
                   p=b.get("p_one_sided_vs_centred_null"))
        curve.append(row)
        print("  {:>6.0f}% {:>9,} {:>7,} {:>7,} {:>8.1f}% {:>9.4f} {:>9.1f} {:>8}".format(
            thr * 100, row["n"], row["days"], row["symbols"], row["win_pct"],
            row["mean_r"], row["mean_bps"], str(row["p"])))
    rep["threshold_curve"] = curve

    # Từng năm ở ngưỡng −5%, để thấy nó có sống qua từng giai đoạn không.
    s5 = ev[ev["gap"] < -0.05].copy()
    s5["yr"] = pd.to_datetime(s5["entry_day"]).dt.year
    rep["by_year_at_5pct"] = {}
    print()
    print("=== NGƯỠNG −5% THEO NĂM ===")
    for y, gg in s5.groupby("yr"):
        rep["by_year_at_5pct"][int(y)] = dict(
            n=int(len(gg)), win_pct=round(float((gg["r_multiple"] > 0).mean() * 100), 1),
            mean_r=round(float(gg["r_multiple"].mean()), 4),
            mean_bps=round(float(gg["pnl_pct"].mean() * 1e4), 1))
        v = rep["by_year_at_5pct"][int(y)]
        print("  {}  {:>6,} lệnh  thắng {:>5.1f}%  R {:>+7.4f}  biên {:>+7.1f} bps".format(
            y, v["n"], v["win_pct"], v["mean_r"], v["mean_bps"]))

    s5.sample(min(len(s5), 50000), random_state=1).to_csv(
        HERE / "_stocks_stage0_gap_expansion_events.csv", index=False)
    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print()
    print("đã ghi", OUT, "({:.0f}s)".format(time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
