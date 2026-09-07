"""scratch/stocks_stage0_yahoo_earnings_20260826.py — dựng lịch earnings sạch từ Yahoo và
đối chiếu với lịch đang dùng. CHỈ ĐỌC (chỉ ghi vào scratch/).

Gọi mạng ra ngoài: có. Chỉ hỏi ngày công bố kết quả của các mã niêm yết Mỹ từ Yahoo Finance —
dữ liệu công khai, không gửi đi bất cứ thứ gì của người dùng.

Vì sao cần
----------
Lịch đang dùng (`earnings_dates_expanded.json`) được dựng từ **ngày nộp hồ sơ 8-K qua Polygon**.
Đối chiếu ba mã cho thấy nó là hỗn hợp ba loại ngày khác nhau:

    AAPL   ngày công bố + 1  = ngày PHẢN ỨNG      -> đúng cho luật này
    MSFT   ngày công bố       = SỚM một ngày       -> luật xem gap TRƯỚC khi có tin
    JPM    ngày công bố + ~20 = ngày nộp 10-Q      -> không liên quan earnings

Luật PE_SHORT hỏi "sáng nay mở cửa có gap xuống >5% không" trên NGÀY TRONG LỊCH. Một ngày sai
không tạo ra lệnh sai — nó chỉ khiến lệnh hầu như không bao giờ nổ, hoặc nổ vào một cú sụt
ngẫu nhiên không liên quan tin. Mà phần C đã đo: gap xuống >5% ở ngày THƯỜNG lỗ −250 bps.
Nên lịch bẩn kéo kết quả XUỐNG chứ không tâng lên, và con số +0,389 R là một cận dưới.

Ngày phản ứng, suy ra chứ không đoán
-------------------------------------
Yahoo trả về thời điểm công bố kèm GIỜ, nên phân được trước/sau phiên:

    công bố >= 16:00 ET  -> thị trường phản ứng ở phiên KẾ TIẾP   (D+1)
    công bố <  09:30 ET  -> thị trường phản ứng NGAY phiên đó      (D)
    ở giữa               -> trong phiên; không có gap qua đêm, bỏ

Đây chính là thông tin mà lịch 8-K không có, và là lý do lịch cũ không thể tự sửa được.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_JSON = HERE / "_stocks_stage0_earnings_yahoo.json"
OUT_CMP = HERE / "_stocks_stage0_earnings_compare.json"
EAR = ROOT / "raits" / "data" / "cache" / "earnings_dates_expanded.json"

SLEEP = 1.5
RETRIES = 3


def reaction_date(ts: pd.Timestamp) -> "pd.Timestamp | None":
    et = ts.tz_convert("America/New_York")
    d0 = et.normalize().tz_localize(None)
    t = et.time()
    if t >= pd.Timestamp("16:00").time():
        return d0 + pd.Timedelta(days=1)
    if t < pd.Timestamp("09:30").time():
        return d0
    return None                      # công bố trong phiên: không có gap qua đêm để đo


def fetch(tk: str):
    import yfinance as yf
    for k in range(RETRIES):
        try:
            d = yf.Ticker(tk).get_earnings_dates(limit=100)
            if d is not None and not d.empty:
                return d
        except Exception as exc:
            if k == RETRIES - 1:
                return exc
            time.sleep(3 * (k + 1))
    return None


def main() -> int:
    t0 = time.time()
    old = json.loads(EAR.read_text(encoding="utf-8"))
    tickers = sorted(old)
    print("lấy lịch earnings Yahoo cho {} mã ...".format(len(tickers)), flush=True)

    new: dict = {}
    intraday: dict = {}
    failed: list = []
    for i, tk in enumerate(tickers, 1):
        d = fetch(tk)
        if d is None or isinstance(d, Exception):
            failed.append(tk)
            print("  [{:2d}/{}] {:6s} HỎNG {}".format(i, len(tickers), tk,
                                                       type(d).__name__ if d else "rỗng"),
                  flush=True)
            time.sleep(SLEEP)
            continue
        idx = pd.to_datetime(d.index)
        react, mid = [], 0
        for x in idx:
            r = reaction_date(x)
            if r is None:
                mid += 1
            else:
                react.append(str(r.date()))
        new[tk] = sorted(set(react))
        intraday[tk] = mid
        if i % 10 == 0 or i == len(tickers):
            print("  [{:2d}/{}] {:6s} {:3d} ngày phản ứng ({:.0f}s)".format(
                i, len(tickers), tk, len(new[tk]), time.time() - t0), flush=True)
        time.sleep(SLEEP)

    OUT_JSON.write_text(json.dumps(new, indent=1, sort_keys=True), encoding="utf-8")

    # ── đối chiếu ─────────────────────────────────────────────────────────────────────
    rows, agree_tot, old_tot = [], 0, 0
    for tk in tickers:
        if tk not in new:
            continue
        o = {pd.Timestamp(str(x)[:10]).normalize() for x in old[tk]}
        n = {pd.Timestamp(x) for x in new[tk]}
        o_win = {x for x in o if pd.Timestamp("2017-01-01") <= x <= pd.Timestamp("2022-12-30")}
        n_win = {x for x in n if pd.Timestamp("2017-01-01") <= x <= pd.Timestamp("2022-12-30")}
        inter = len(o_win & n_win)
        agree_tot += inter
        old_tot += len(o_win)
        # lệch trung vị: mỗi ngày cũ cách ngày phản ứng gần nhất bao xa
        offs = ([min(((x - y).days for y in n_win), key=abs) for x in sorted(o_win)]
                if n_win else [])
        rows.append(dict(ticker=tk, old_2017_2022=len(o_win), yahoo_2017_2022=len(n_win),
                         exact_match=inter,
                         median_offset_days=(float(pd.Series(offs).median())
                                             if offs else None)))

    cmp = dict(n_tickers=len(new), failed=failed,
               old_events_2017_2022=old_tot, exact_match=agree_tot,
               match_pct=round(100 * agree_tot / max(old_tot, 1), 1),
               per_ticker=rows,
               intraday_announcements_dropped=sum(intraday.values()))
    OUT_CMP.write_text(json.dumps(cmp, indent=2, default=str), encoding="utf-8")

    print()
    print("=== ĐỐI CHIẾU 2017-2022 ===")
    print("  sự kiện trong lịch CŨ            : {}".format(old_tot))
    print("  trùng khớp ngày phản ứng Yahoo   : {}  ({}%)".format(agree_tot,
                                                                   cmp["match_pct"]))
    print("  mã lấy được / hỏng               : {} / {}".format(len(new), len(failed)))
    print("  công bố trong phiên (đã bỏ)      : {}".format(cmp["intraday_announcements_dropped"]))
    df = pd.DataFrame(rows)
    if len(df):
        df["ok_pct"] = 100 * df.exact_match / df.old_2017_2022.clip(lower=1)
        print()
        print("  10 mã lệch NHIỀU nhất (lịch cũ sai nhiều nhất):")
        for _, r in df.nsmallest(10, "ok_pct").iterrows():
            print("    {:6s} cũ {:2d} sự kiện, khớp {:2d} ({:4.0f}%), lệch trung vị {} ngày"
                  .format(r.ticker, int(r.old_2017_2022), int(r.exact_match), r.ok_pct,
                          r.median_offset_days))
        print()
        print("  số mã khớp >=80%: {} / {}".format(int((df.ok_pct >= 80).sum()), len(df)))
        print("  số mã khớp <=20%: {} / {}".format(int((df.ok_pct <= 20).sum()), len(df)))
    print()
    print("đã ghi", OUT_JSON, "và", OUT_CMP, "({:.0f}s)".format(time.time() - t0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
