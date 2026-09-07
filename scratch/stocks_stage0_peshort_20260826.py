"""scratch/stocks_stage0_peshort_20260826.py — PE_SHORT: ngưỡng gap là cơ chế hay là một
con số đã được chọn? CHỈ ĐỌC.

Câu hỏi
-------
PE_SHORT nổ trên **2,6%** số sự kiện earnings của chính nó (29 trên 1.098) và mang 47,5% kết
quả của cả hệ. Nếu edge chỉ tồn tại ở đúng cái đuôi 2,6% ấy thì đó là dấu hiệu của một NGƯỠNG
ĐÃ ĐƯỢC CHỌN. Nếu nó tăng dần khi gap sâu dần thì đó là một CƠ CHẾ. Hai thứ đó đòi hai quyết
định khác hẳn nhau, và phân biệt chúng chỉ cần mở ngưỡng ra thành một đường cong.

Luật, đọc từ `raits/decision/decision_unit.py` chứ không từ tài liệu
--------------------------------------------------------------------
    09:30 ngày D, D nằm trong lịch earnings của mã
    gap = (open_0930 - prev_close) / prev_close      phải < -0.05     (PE_SHORT_GAP_MIN)
    atr = trung bình 14 phiên True Range, tính trên bar TRƯỚC ngày D   (nhân quả)
    BÁN KHỐNG tại open_0930
    stop   = open + 1.5 x atr                        (PE_SHORT_STOP_MULT)
    target = open - 3.0 x atr                        (PE_SHORT_TARGET_RR = 2.0, tức 2R)
    thoát  chạm stop hoặc target trong phiên; giữ QUA ngày vào lệnh;
           đóng tại giá đóng 15:55 của phiên KẾ TIẾP nếu chưa chạm gì (EOD_HARD_EXIT)

`_REGIME_STRATEGIES` cho PE_SHORT chạy ở **cả bốn** chế độ (Calm/Normal/Stress/Crisis), nên ở
đây KHÔNG có cổng chế độ nào bị bỏ sót.

Cái này KHÔNG phải một cuốn sổ
------------------------------
Đây là phép đo HÌNH DẠNG TÍN HIỆU theo bội số R, không phải P&L. Vắng mặt: trần 2 vị thế cùng
lúc, vốn và định cỡ, luật chặn day-trade, các cầu dao. Nói ra vì kho này đã có luật: mọi sim
phải replicate đủ điều kiện engine, hoặc phải khai rõ cái gì thiếu. Trần 2 vị thế hiếm khi
ràng buộc ở đây — luật nổ khoảng 5 lần một năm — nhưng "hiếm khi" không phải "không bao giờ".

Một chi tiết có thể đổi ý nghĩa của ngưỡng
-------------------------------------------
Engine lấy `prev_close` là giá đóng của **bar bất kỳ** trước ngày D. Cache mang 04:00-19:55,
nên đó là bar 19:55 NGOÀI GIỜ của D-1 — mà tin earnings thường ra SAU giờ đóng cửa, tức bar
đó đã phản ánh tin. Vậy "gap 5%" của engine đo từ giá đã hấp thụ tin, không phải từ giá đóng
16:00. Cả hai cách đo đều được tính ra ở đây để xem chúng có thật sự khác nhau không.
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

OUT = HERE / "_stocks_stage0_peshort.json"
EAR = ROOT / "raits" / "data" / "cache" / "earnings_dates_expanded.json"

GAP_MIN = 0.05          # PE_SHORT_GAP_MIN
STOP_MULT = 1.5         # PE_SHORT_STOP_MULT
TARGET_RR = 2.0         # PE_SHORT_TARGET_RR
EOD = pd.Timestamp("15:55").time()
OPEN_T = pd.Timestamp("09:30").time()
WIN_START, WIN_END = "2017-01-03", "2022-12-30"


def load_full(ticker: str, days) -> pd.DataFrame:
    """Frame ĐẦY ĐỦ 04:00-19:55, không cắt về RTH — vì engine đọc `prev_close` từ bar bất kỳ."""
    frames = []
    for d in days:
        p = D.session_path(ticker, d)
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p, columns=["open", "high", "low", "close", "volume"])
        except Exception:
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="first")].astype(float)


def daily_atr_before(full: pd.DataFrame, as_of, period: int = 14) -> float:
    """Bản sao đúng của `_compute_daily_atr`: resample 'B' trên bar TRƯỚC `as_of`."""
    df = full.loc[full.index < as_of]
    if df.empty:
        return 0.0
    daily = df.resample("B").agg({"open": "first", "high": "max",
                                  "low": "min", "close": "last"}).dropna()
    if len(daily) < period + 1:
        return float(df["close"].iloc[-1]) * 0.01
    pc = daily["close"].shift(1)
    tr = pd.concat([daily["high"] - daily["low"], (daily["high"] - pc).abs(),
                    (daily["low"] - pc).abs()], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def simulate(full: pd.DataFrame, day: pd.Timestamp) -> "dict | None":
    """Một sự kiện. Trả về mọi thứ cần để quét ngưỡng, hoặc None nếu không dựng được."""
    d0 = pd.Timestamp(day).normalize()
    today = full[full.index.normalize() == d0]
    if today.empty:
        return None
    first = today[today.index.time >= OPEN_T]
    if first.empty:
        return None
    opx = float(first.iloc[0]["open"])
    prev = full[full.index < d0]
    if prev.empty or opx <= 0:
        return None

    prev_close_ext = float(prev["close"].iloc[-1])                 # engine: bar bất kỳ
    prev_rth = prev[prev.index.time <= EOD]
    if prev_rth.empty:
        return None
    last_rth_day = prev_rth.index.normalize()[-1]
    prev_close_rth = float(prev_rth[prev_rth.index.normalize() == last_rth_day]
                           ["close"].iloc[-1])
    if prev_close_ext <= 0 or prev_close_rth <= 0:
        return None

    atr = daily_atr_before(full, d0)
    if atr <= 0:
        return None
    stop = round(opx + STOP_MULT * atr, 2)
    target = round(opx - TARGET_RR * STOP_MULT * atr, 2)

    # Đi bộ qua bar RTH: ngày vào lệnh (từ 09:30) rồi phiên kế tiếp, đóng tại 15:55 phiên đó.
    fwd_days = sorted(set(full.index[full.index.normalize() >= d0].normalize()))[:2]
    exit_px, reason = None, None
    for i, dd in enumerate(fwd_days):
        bars = full[(full.index.normalize() == dd)
                    & (full.index.time >= OPEN_T) & (full.index.time <= EOD)]
        if i == 0:
            bars = bars[bars.index >= first.index[0]]
        if bars.empty:
            continue
        for _, b in bars.iterrows():
            if float(b["high"]) >= stop:
                exit_px, reason = stop, "STOP_HIT"
                break
            if float(b["low"]) <= target:
                exit_px, reason = target, "TARGET_HIT"
                break
        if exit_px is not None:
            break
        if i == len(fwd_days) - 1:
            exit_px, reason = float(bars.iloc[-1]["close"]), "EOD"
    if exit_px is None:
        return None

    risk = STOP_MULT * atr
    return dict(entry_day=str(d0.date()), open=opx, atr=round(atr, 4),
                gap_ext=(opx - prev_close_ext) / prev_close_ext,
                gap_rth=(opx - prev_close_rth) / prev_close_rth,
                stop=stop, target=target, exit=round(exit_px, 4), reason=reason,
                r_multiple=(opx - exit_px) / risk)


def main() -> int:
    t0 = time.time()
    ear = json.loads(EAR.read_text(encoding="utf-8"))
    cal = [d for d in D.calendar("SPY")
           if pd.Timestamp(WIN_START) <= d <= pd.Timestamp(WIN_END)]
    calset = {pd.Timestamp(d).normalize() for d in cal}

    rows = []
    for i, (tkr, dates) in enumerate(sorted(ear.items()), 1):
        evs = [pd.Timestamp(str(x)[:10]).normalize() for x in dates]
        evs = [e for e in evs if e in calset]
        if not evs:
            continue
        # Chỉ nạp những phiên thật sự cần: 40 phiên trước mỗi sự kiện (ATR cần ~15 phiên
        # ngày, cộng đệm cho ngày nghỉ) và 2 phiên sau (ngày vào lệnh + phiên kế tiếp).
        # Nạp cả 1.510 phiên cho mỗi mã tốn 35 giây/mã và 96% số tệp đó không bao giờ
        # được đọc tới.
        cal_idx = pd.DatetimeIndex(cal)
        need = set()
        for e in evs:
            pos = int(cal_idx.searchsorted(e))
            for k in range(max(0, pos - 40), min(len(cal_idx), pos + 3)):
                need.add(cal_idx[k])
        full = load_full(tkr, sorted(need))
        if full.empty:
            continue
        for e in evs:
            r = simulate(full, e)
            if r:
                r["ticker"] = tkr
                rows.append(r)
        print("  [{:2d}/{}] {:6s} {:3d} sự kiện dựng được ({:.0f}s)".format(
            i, len(ear), tkr, sum(1 for x in rows if x["ticker"] == tkr),
            time.time() - t0), flush=True)

    df = pd.DataFrame(rows)
    rep: dict = {"n_events_simulated": len(df),
                 "window": [WIN_START, WIN_END],
                 "note": "hình dạng tín hiệu theo bội số R; KHÔNG phải sổ — thiếu trần 2 vị "
                         "thế, vốn/định cỡ, PDT, cầu dao"}
    if df.empty:
        print("không dựng được sự kiện nào")
        return 2

    # ── hai cách đo gap có khác nhau không? ───────────────────────────────────────────
    dd = (df["gap_rth"] - df["gap_ext"]).abs()
    rep["gap_definition"] = dict(
        median_abs_diff_pct=round(float(dd.median() * 100), 4),
        p90_abs_diff_pct=round(float(dd.quantile(0.9) * 100), 4),
        n_where_ext_passes_rth_fails=int(((df["gap_ext"] < -GAP_MIN)
                                          & (df["gap_rth"] >= -GAP_MIN)).sum()),
        n_where_rth_passes_ext_fails=int(((df["gap_rth"] < -GAP_MIN)
                                          & (df["gap_ext"] >= -GAP_MIN)).sum()),
        n_ext_passes=int((df["gap_ext"] < -GAP_MIN).sum()),
        n_rth_passes=int((df["gap_rth"] < -GAP_MIN).sum()))
    g = rep["gap_definition"]
    print()
    print("=== HAI CÁCH ĐO GAP ===")
    print("  lệch trung vị {:.4f}%   p90 {:.4f}%".format(g["median_abs_diff_pct"],
                                                          g["p90_abs_diff_pct"]))
    print("  qua ngưỡng theo cách ENGINE (bar bất kỳ, gồm ngoài giờ): {}".format(
        g["n_ext_passes"]))
    print("  qua ngưỡng theo giá đóng 15:55                         : {}".format(
        g["n_rth_passes"]))
    print("  chỉ engine qua: {}   chỉ RTH qua: {}".format(
        g["n_where_ext_passes_rth_fails"], g["n_where_rth_passes_ext_fails"]))
    print()

    # ── đường cong ngưỡng ─────────────────────────────────────────────────────────────
    print("=== ĐƯỜNG CONG NGƯỠNG (gap theo cách engine) ===")
    print("  {:>7s} {:>6s} {:>6s} {:>7s} {:>8s} {:>9s} {:>7s} {:>7s} {:>8s}".format(
        "ngưỡng", "lệnh", "ngày", "thắng%", "R tr.bình", "tổng R", "stop%", "target%", "p"))
    curve = []
    for thr in [0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15]:
        sub = df[df["gap_ext"] < -thr] if thr > 0 else df[df["gap_ext"] < 0]
        if sub.empty:
            continue
        bb = ({"error": "n nhỏ"} if sub["entry_day"].nunique() < 20 else
              cluster_bootstrap(pd.DataFrame({"entry_day": sub["entry_day"],
                                              "net_pnl": sub["r_multiple"]}), n_boot=10000))
        row = dict(threshold=thr, n=int(len(sub)),
                   entry_days=int(sub["entry_day"].nunique()),
                   win_pct=round(float((sub["r_multiple"] > 0).mean() * 100), 1),
                   mean_r=round(float(sub["r_multiple"].mean()), 3),
                   total_r=round(float(sub["r_multiple"].sum()), 1),
                   stop_pct=round(float((sub["reason"] == "STOP_HIT").mean() * 100), 1),
                   target_pct=round(float((sub["reason"] == "TARGET_HIT").mean() * 100), 1),
                   p=bb.get("p_one_sided_vs_centred_null"))
        curve.append(row)
        print("  {:>6.0f}% {:>6d} {:>6d} {:>6.1f}% {:>8.3f} {:>9.1f} {:>6.1f}% {:>6.1f}% "
              "{:>8}".format(thr * 100, row["n"], row["entry_days"], row["win_pct"],
                             row["mean_r"], row["total_r"], row["stop_pct"],
                             row["target_pct"], str(row["p"])))
    rep["threshold_curve"] = curve

    # ── mặt còn lại: gap LÊN có gì không (luật chỉ nhìn gap xuống) ────────────────────
    up = df[df["gap_ext"] > 0.05]
    if len(up) > 5:
        rep["gap_up_mirror"] = dict(n=int(len(up)),
                                    mean_r_if_shorted=round(float(up["r_multiple"].mean()), 3),
                                    win_pct=round(float((up["r_multiple"] > 0).mean() * 100), 1))
        print()
        print("  đối chứng — gap LÊN > 5%, nếu áp CÙNG luật bán khống: {} sự kiện, "
              "R trung bình {:.3f}, thắng {:.1f}%".format(
                  rep["gap_up_mirror"]["n"], rep["gap_up_mirror"]["mean_r_if_shorted"],
                  rep["gap_up_mirror"]["win_pct"]))

    df.to_csv(HERE / "_stocks_stage0_peshort_events.csv", index=False)
    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print()
    print("đã ghi", OUT, "và _stocks_stage0_peshort_events.csv ({:.0f}s)".format(
        time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
