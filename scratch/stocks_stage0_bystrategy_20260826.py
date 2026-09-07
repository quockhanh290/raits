"""scratch/stocks_stage0_bystrategy_20260826.py — tách hệ cổ phiếu SẴN CÓ theo từng chiến
lược. CHỈ ĐỌC.

Đây là một hệ KHÁC với tuyến Track 1 mà Stage STOCKS-0 vừa dựng. Không trộn hai bên: tuyến
kia là MỘT luật chạy trên bar 5 phút RTH 2019-2022 với sổ riêng; hệ này là engine cổ phiếu cũ
với nhiều chiến lược cùng chạy trên một tài khoản $50k.

Nguồn: sổ lệnh 605 dòng trên đĩa (`baselines/is_baseline_cb_fixed_2026-07-08.csv`) và ảnh chụp
`raits/data/cache/snapshots/results_20260707_110323.pkl`.

Vì sao đo lại thay vì chép
--------------------------
Bản rà soát 2026-08-17 đã chỉ ra rằng ba con số vẫn được gọi chung là "nền in-sample" thật ra
do BA cấu hình khác nhau sinh ra, và mọi kết luận "chiến lược nào có edge" đều đo trên cột
giữa — cột duy nhất KHÔNG phải cấu hình sản xuất (bộ quét chọn mã TẮT, luật chặn day-trade
BẬT). Nên mỗi con số ở đây đi kèm cấu hình đã sinh ra nó, và không con số nào được chép lại từ
tài liệu: tổng cộng lại phải khớp với siêu dữ liệu của chính tệp, đó là phép tự kiểm đầu tiên.

Phép kiểm ý nghĩa
-----------------
Gom cụm theo NGÀY VÀO LỆNH, null căn giữa — cùng hàm với phần còn lại của tầng này. Với các
chiến lược n nhỏ (GF_SHORT 12 lệnh, STRESS_MID 28) thì bootstrap ngày gần như không nói được
gì, và điều đó được in ra chứ không bị giấu sau một p-value trông có vẻ chắc chắn.
"""
from __future__ import annotations

import json
import pickle
import sys
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

from scratch.stocks_stage0_bootstrap_20260826 import cluster_bootstrap   # noqa: E402

LEDGER = ROOT / "baselines" / "is_baseline_cb_fixed_2026-07-08.csv"
META = ROOT / "baselines" / "is_baseline_cb_fixed_2026-07-08_meta.json"
SNAP = ROOT / "raits" / "data" / "cache" / "snapshots" / "results_20260707_110323.pkl"
OUT = HERE / "_stocks_stage0_bystrategy.json"

#: n dưới ngưỡng này thì bootstrap ngày không được trình như một phép kiểm. Đặt trước.
MIN_DAYS_FOR_P = 20


def _boot(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"error": "rỗng"}
    d = df[["entry_day", "net_pnl"]].copy()
    n_days = d["entry_day"].nunique()
    if n_days < MIN_DAYS_FOR_P:
        return {"error": "chỉ {} ngày vào lệnh — dưới ngưỡng {} đã đặt trước".format(
            n_days, MIN_DAYS_FOR_P), "n_entry_days": int(n_days)}
    return cluster_bootstrap(d, n_boot=10000)


def main() -> int:
    rep: dict = {}

    # ── nền so sánh liên tục 6 năm ────────────────────────────────────────────────────
    meta = json.loads(META.read_text(encoding="utf-8"))
    d = pd.read_csv(LEDGER)
    d["entry_time"] = pd.to_datetime(d["entry_time"])
    d["entry_day"] = d["entry_time"].dt.normalize()
    d["year"] = d["entry_time"].dt.year

    # Tự kiểm 1: tổng đo lại phải khớp siêu dữ liệu của chính tệp.
    tot = float(d["net_pnl"].sum())
    sc1 = abs(tot - meta["total_pnl"]) < 0.01
    sc2 = len(d) == meta["trade_count"]
    print("=== NỀN SO SÁNH LIÊN TỤC 6 NĂM (2017-01-03 .. 2022-12-30, $50k) ===")
    print("cấu hình: bộ quét chọn mã TẮT (37 mã cố định) · luật chặn day-trade BẬT")
    print("           -> ĐÂY KHÔNG PHẢI cấu hình sản xuất (rà soát 2026-08-17)")
    print()
    print(("[PASS] " if sc1 else "[FAIL] ") +
          "SC1 tổng đo lại ${:,.2f} khớp siêu dữ liệu ${:,.2f}".format(tot, meta["total_pnl"]))
    print(("[PASS] " if sc2 else "[FAIL] ") +
          "SC2 số lệnh {} khớp siêu dữ liệu {}".format(len(d), meta["trade_count"]))
    print()

    rows = []
    for name, g in d.groupby("strategy"):
        bb = _boot(g)
        rows.append(dict(
            strategy=name, trades=int(len(g)),
            entry_days=int(g["entry_day"].nunique()),
            net=round(float(g["net_pnl"].sum()), 2),
            per_trade=round(float(g["net_pnl"].mean()), 2),
            win_rate=round(float((g["net_pnl"] > 0).mean() * 100), 1),
            gross=round(float(g["gross_pnl"].sum()), 2),
            costs=round(float(g["total_costs"].sum()), 2),
            share_of_total=round(float(g["net_pnl"].sum() / tot * 100), 1),
            bootstrap=bb))
    rows.sort(key=lambda r: -r["net"])
    rep["baseline_6y_continuous"] = dict(meta=meta, total=round(tot, 2),
                                         trades=len(d), by_strategy=rows,
                                         self_check=dict(SC1=sc1, SC2=sc2))

    print("{:14s} {:>6s} {:>6s} {:>11s} {:>8s} {:>7s} {:>7s} {:>19s} {:>8s}".format(
        "chiến lược", "lệnh", "ngày", "ròng", "$/lệnh", "thắng", "% tổng", "KTC 95%", "p"))
    for r in rows:
        bb = r["bootstrap"]
        ci = ("[{:,.0f}, {:,.0f}]".format(bb["boot_ci95_low"], bb["boot_ci95_high"])
              if "error" not in bb else "n quá nhỏ")
        p = bb.get("p_one_sided_vs_centred_null", "-")
        print("{:14s} {:>6d} {:>6d} {:>11,.0f} {:>8,.0f} {:>6.1f}% {:>6.1f}% {:>19s} {:>8}"
              .format(r["strategy"], r["trades"], r["entry_days"], r["net"], r["per_trade"],
                      r["win_rate"], r["share_of_total"], ci, p))
    print("{:14s} {:>6d} {:>6d} {:>11,.0f}".format("TỔNG", len(d),
                                                   d["entry_day"].nunique(), tot))
    print()

    # ── từng năm, từng chiến lược ─────────────────────────────────────────────────────
    piv = d.pivot_table(index="strategy", columns="year", values="net_pnl",
                        aggfunc="sum").fillna(0.0)
    cnt = d.pivot_table(index="strategy", columns="year", values="net_pnl",
                        aggfunc="count").fillna(0).astype(int)
    rep["by_strategy_year_net"] = {k: {int(c): round(float(v), 2) for c, v in r.items()}
                                   for k, r in piv.iterrows()}
    rep["by_strategy_year_trades"] = {k: {int(c): int(v) for c, v in r.items()}
                                      for k, r in cnt.iterrows()}
    print("=== ròng theo NĂM (số lệnh trong ngoặc) ===")
    hdr = "{:14s}".format("chiến lược") + "".join("{:>14d}".format(int(c))
                                                   for c in piv.columns)
    print(hdr)
    for k in piv.index:
        line = "{:14s}".format(k)
        for c in piv.columns:
            line += "{:>9,.0f}({:>3d})".format(piv.loc[k, c], cnt.loc[k, c])
        print(line)
    line = "{:14s}".format("TỔNG")
    for c in piv.columns:
        line += "{:>9,.0f}({:>3d})".format(piv[c].sum(), int(cnt[c].sum()))
    print(line)
    print()

    # số năm dương / âm — độ bền đơn giản, không cần mô hình
    print("=== số năm DƯƠNG trên 6 năm ===")
    for k in piv.index:
        pos = int((piv.loc[k] > 0).sum())
        nz = int((cnt.loc[k] > 0).sum())
        print("  {:14s} {}/{} năm dương  (có giao dịch {} năm)".format(k, pos, nz, nz))
    print()

    # ── các chiến lược KHÔNG dùng chung một rổ mã ─────────────────────────────────────
    # Điều này đổi cách đọc cả bảng bên trên: so PE_SHORT với TREND_FOLLOW là so một bộ lọc
    # quét 62 tên với một bộ lọc quét 37 tên, không phải hai chiến lược trên cùng một sân.
    EAR = ROOT / "raits" / "data" / "cache" / "earnings_dates_expanded.json"
    if EAR.exists():
        ear = json.loads(EAR.read_text(encoding="utf-8"))
        base = set(d[d["strategy"] == "TREND_FOLLOW"]["ticker"])
        pe = d[d["strategy"] == "PE_SHORT"]
        pe_out = pe[[t not in base for t in pe["ticker"]]]
        n_ev_win = sum(1 for t, ds in ear.items() for x in ds
                       if "2017-01-01" <= str(x)[:10] <= "2022-12-30")
        rep["universes"] = dict(
            base_universe_size=len(base),
            pe_short_calendar_size=len(ear),
            expanded_beyond_base=len(set(ear) - base),
            pe_short_tickers_traded=int(pe["ticker"].nunique()),
            pe_short_tickers_outside_base=sorted(set(pe["ticker"]) - base),
            pe_short_trades_outside_base=int(len(pe_out)),
            pe_short_pnl_outside_base=round(float(pe_out["net_pnl"].sum()), 2),
            pe_short_pnl_outside_base_pct=round(
                float(pe_out["net_pnl"].sum() / pe["net_pnl"].sum() * 100), 1),
            earnings_events_in_window=int(n_ev_win),
            pe_short_fire_rate_pct=round(100 * len(pe) / max(n_ev_win, 1), 2))
        u = rep["universes"]
        print("=== CÁC CHIẾN LƯỢC KHÔNG DÙNG CHUNG RỔ MÃ ===")
        print("  rổ cơ bản (TREND_FOLLOW, ORB, ...)      {} mã".format(u["base_universe_size"]))
        print("  lịch earnings của PE_SHORT              {} mã  ({} mã ngoài rổ cơ bản)".format(
            u["pe_short_calendar_size"], u["expanded_beyond_base"]))
        print("  PE_SHORT thực sự vào lệnh trên          {} mã".format(
            u["pe_short_tickers_traded"]))
        print("  trong đó NGOÀI rổ cơ bản                {} -> {}".format(
            len(u["pe_short_tickers_outside_base"]), u["pe_short_tickers_outside_base"]))
        print("  P&L đến từ ngoài rổ cơ bản              ${:,.0f}  = {}% của PE_SHORT".format(
            u["pe_short_pnl_outside_base"], u["pe_short_pnl_outside_base_pct"]))
        print("  sự kiện earnings trong cửa sổ           {:,}".format(
            u["earnings_events_in_window"]))
        print("  PE_SHORT nổ trên                        {}% số sự kiện".format(
            u["pe_short_fire_rate_pct"]))
        print()

    # ── ảnh chụp 07/07: từng năm đặt lại $50k, bộ quét BẬT, PDT TẮT ───────────────────
    # Cấu trúc đo được chứ không đoán: một `list` sáu phần tử, mỗi phần tử là một năm với
    # khoá `label` / `stats` / `trades`. Đọc pickle này cần `raits` trên sys.path vì các đối
    # tượng lệnh bên trong thuộc gói đó — đó là lý do nó không phải một artifact độc lập.
    if SNAP.exists():
        try:
            with open(SNAP, "rb") as f:
                snap = pickle.load(f)
            parts = []
            for e in snap:
                tr = e["trades"]
                sub = (tr if isinstance(tr, pd.DataFrame)
                       else pd.DataFrame([vars(t) if hasattr(t, "__dict__") else t
                                          for t in tr]))
                sub["_year"] = e["label"]
                parts.append(sub)
            sd = pd.concat(parts, ignore_index=True)
            stot = float(sd["net_pnl"].sum())
            g = sd.groupby("strategy")["net_pnl"].agg(["count", "sum"]).sort_values(
                "sum", ascending=False)
            spiv = sd.pivot_table(index="strategy", columns="_year", values="net_pnl",
                                  aggfunc="sum").fillna(0.0)
            scnt = sd.pivot_table(index="strategy", columns="_year", values="net_pnl",
                                  aggfunc="count").fillna(0).astype(int)
            rep["snapshot_20260707"] = dict(
                config="từng năm đặt lại $50k · bộ quét chọn mã BẬT · PDT TẮT",
                total=round(stot, 2), trades=int(len(sd)),
                by_strategy={k: dict(trades=int(v["count"]), net=round(float(v["sum"]), 2),
                                     per_trade=round(float(v["sum"] / v["count"]), 2),
                                     share_pct=round(float(v["sum"] / stot * 100), 1),
                                     positive_years=int((spiv.loc[k] > 0).sum()),
                                     active_years=int((scnt.loc[k] > 0).sum()))
                             for k, v in g.iterrows()},
                by_strategy_year={k: {str(c): round(float(spiv.loc[k, c]), 2)
                                      for c in spiv.columns} for k in spiv.index})
            print("=== ẢNH CHỤP 2026-07-07 (từng năm đặt lại $50k · bộ quét BẬT · PDT TẮT) ===")
            print("  {:14s} {:>6s} {:>12s} {:>9s} {:>8s} {:>10s}".format(
                "chiến lược", "lệnh", "ròng", "$/lệnh", "% tổng", "năm dương"))
            for k, v in rep["snapshot_20260707"]["by_strategy"].items():
                print("  {:14s} {:>6d} {:>12,.0f} {:>9,.0f} {:>7.1f}% {:>7d}/{:d}".format(
                    k, v["trades"], v["net"], v["per_trade"], v["share_pct"],
                    v["positive_years"], v["active_years"]))
            print("  {:14s} {:>6d} {:>12,.0f}".format("TỔNG", len(sd), stot))
            print()

            # ── đối chiếu hai cấu hình, cùng chiến lược ────────────────────────────────
            print("=== HAI CẤU HÌNH, CÙNG CHIẾN LƯỢC, CÙNG GIAI ĐOẠN 2017-2022 ===")
            print("  {:14s} {:>22s} {:>22s}".format(
                "", "ảnh chụp (quét BẬT)", "liên tục (quét TẮT)"))
            print("  {:14s} {:>8s}{:>8s}{:>6s} {:>8s}{:>8s}{:>6s}".format(
                "chiến lược", "lệnh", "ròng", "năm+", "lệnh", "ròng", "năm+"))
            cmp_rows = {}
            cont = {r["strategy"]: r for r in rows}
            for k, v in rep["snapshot_20260707"]["by_strategy"].items():
                c = cont.get(k)
                cy = int(sum(1 for y in rep["by_strategy_year_net"].get(k, {}).values()
                             if y > 0))
                ca = int(sum(1 for y in rep["by_strategy_year_trades"].get(k, {}).values()
                             if y > 0))
                cmp_rows[k] = dict(snapshot=v,
                                   continuous=(dict(trades=c["trades"], net=c["net"],
                                                    positive_years=cy, active_years=ca)
                                               if c else None))
                print("  {:14s} {:>8d}{:>8,.0f}{:>5d}/{:d} {:>8d}{:>8,.0f}{:>5d}/{:d}".format(
                    k, v["trades"], v["net"], v["positive_years"], v["active_years"],
                    c["trades"] if c else 0, c["net"] if c else 0, cy, ca))
            rep["config_comparison"] = cmp_rows
            print()
        except Exception as exc:
            print("  không đọc được ảnh chụp:", type(exc).__name__, exc)
            rep["snapshot_error"] = "{}: {}".format(type(exc).__name__, exc)
    print()

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print("đã ghi", OUT)
    return 0 if (sc1 and sc2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
