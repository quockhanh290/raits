"""scratch/stocks_stage0_decompose_20260826.py — tách tuyến thành từng nhánh. CHỈ ĐỌC.

Một con số gộp che mất nhánh nào đang gánh và nhánh nào đang kéo xuống. Ở đây tuyến được cắt
theo bốn trục, và mỗi trục cắt được cắt theo HAI nghĩa khác nhau — vì hai nghĩa đó ra hai con
số khác nhau và rất dễ bị lẫn:

    QUY KẾT      lấy đúng các dòng của nhánh đó TRONG sổ gộp. Trả lời: "trong cuốn sổ đã
                 chạy, nhánh này đóng góp bao nhiêu?" Các nhánh cộng lại đúng bằng tổng.

    PHẢN THỰC    ghi sổ lại chỉ với ứng viên của nhánh đó, cho nó TOÀN BỘ sức chứa của sổ.
                 Trả lời: "nếu chỉ chạy nhánh này thì sao?" Các nhánh KHÔNG cộng lại thành
                 tổng, vì mỗi nhánh được dùng lại cùng số vốn.

Lẫn hai cái này là cách dễ nhất để kết luận sai. Sổ bị chặn bởi vốn — khoảng chín vị thế cùng
lúc cho 6.268 ứng viên — nên bỏ một nhánh đi thì nhánh còn lại KHÔNG giữ nguyên số lệnh của
nó: nó được thêm suất, và những suất thêm đó có thể đáng giá hoặc không.

Bootstrap gom cụm theo ngày, null căn giữa, dùng lại đúng hàm ở phép đo trước.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scratch import stocks_stage0_engine_20260826 as E                      # noqa: E402
from scratch import stocks_stage0_data_20260826 as D                        # noqa: E402
from scratch.stocks_stage0_run_20260826 import metrics                      # noqa: E402
from scratch.stocks_stage0_bootstrap_20260826 import cluster_bootstrap      # noqa: E402

OUT = HERE / "_stocks_stage0_decompose.json"
STREAM = HERE / "_stocks_stage0_candidates_B_causal_lag1_ema50.pkl"
LEDGER = HERE / "_stocks_stage0_ledger_B_causal_lag1_ema50.csv"

#: Trục cắt. Mỗi cái là một vị từ trên MỘT ứng viên — không có vị từ nào đọc kết quả của lệnh,
#: nên không có trục nào ở đây là chọn sau khi nhìn.
AXES = {
    "LONG": lambda c: c["direction"] == "LONG",
    "SHORT": lambda c: c["direction"] == "SHORT",
    "mã đơn lẻ": lambda c: c["symbol"] not in D.ETFS,
    "ETF": lambda c: c["symbol"] in D.ETFS,
    "LONG · mã đơn lẻ": lambda c: c["direction"] == "LONG" and c["symbol"] not in D.ETFS,
    "LONG · ETF": lambda c: c["direction"] == "LONG" and c["symbol"] in D.ETFS,
    "SHORT · mã đơn lẻ": lambda c: c["direction"] == "SHORT" and c["symbol"] not in D.ETFS,
    "SHORT · ETF": lambda c: c["direction"] == "SHORT" and c["symbol"] in D.ETFS,
}


def _boot(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"error": "rỗng"}
    return cluster_bootstrap(df[["entry_day", "net_pnl"]].copy(), n_boot=10000)


def main() -> int:
    if not STREAM.exists() or not LEDGER.exists():
        print("thiếu dòng ứng viên hoặc sổ; chạy lượt chính trước")
        return 2
    cands = pd.read_pickle(STREAM)
    led = pd.read_csv(LEDGER)
    taken = led[led["status"] == "TAKEN"].copy()
    sizing, cost = E.SizingModel(), E.StockCostModel()
    rep: dict = {"n_candidates": len(cands), "n_taken_combined": len(taken)}

    base = metrics([r for r in E.build_book(cands, sizing, cost)[0]], sizing.initial_capital)
    rep["gộp"] = base
    rep["gộp_bootstrap"] = _boot(taken)
    print("=== SỔ GỘP (nền so sánh) ===")
    print("  {} lệnh   ròng ${:,.0f}   PF {}   sụt ${:,.0f}".format(
        base.get("trades"), base.get("net", 0), base.get("profit_factor"),
        base.get("max_dd", 0)))
    b = rep["gộp_bootstrap"]
    if "error" not in b:
        print("  {} ngày vào lệnh   KTC95 [${:,.0f}, ${:,.0f}]   p={}".format(
            b["n_entry_days"], b["boot_ci95_low"], b["boot_ci95_high"],
            b["p_one_sided_vs_centred_null"]))
    print()

    # ── QUY KẾT: các dòng của nhánh trong chính sổ gộp ────────────────────────────────
    print("=== QUY KẾT — nhánh này đóng góp gì TRONG sổ đã chạy (cộng lại = tổng) ===")
    print("  {:20s} {:>6s} {:>11s} {:>8s} {:>10s} {:>8s} {:>7s}".format(
        "nhánh", "lệnh", "ròng", "$/lệnh", "KTC95 thấp", "KTC95 cao", "p"))
    attr = {}
    for name, pred in AXES.items():
        sub = taken[[bool(pred(dict(direction=d, symbol=s)))
                     for d, s in zip(taken["direction"], taken["symbol"])]]
        m = dict(trades=int(len(sub)), net=round(float(sub["net_pnl"].sum()), 2),
                 per_trade=round(float(sub["net_pnl"].mean()), 2) if len(sub) else None,
                 win_rate=round(float((sub["net_pnl"] > 0).mean() * 100), 1) if len(sub)
                 else None)
        bb = _boot(sub)
        m["bootstrap"] = bb
        attr[name] = m
        print("  {:20s} {:>6d} {:>11,.0f} {:>8} {:>10} {:>8} {:>7}".format(
            name, m["trades"], m["net"], m["per_trade"],
            "{:,.0f}".format(bb["boot_ci95_low"]) if "error" not in bb else "-",
            "{:,.0f}".format(bb["boot_ci95_high"]) if "error" not in bb else "-",
            bb.get("p_one_sided_vs_centred_null", "-")))
    rep["quy_kết"] = attr
    chk = attr["LONG"]["net"] + attr["SHORT"]["net"]
    print("  ----")
    print("  LONG + SHORT = {:,.2f}   vs tổng sổ {:,.2f}   lệch {:,.2f}".format(
        chk, base.get("net", 0), chk - base.get("net", 0)))
    print()

    # ── PHẢN THỰC: chỉ chạy nhánh này, sổ đầy đủ sức chứa ─────────────────────────────
    print("=== PHẢN THỰC — nếu CHỈ chạy nhánh này, với nguyên vốn (KHÔNG cộng lại được) ===")
    print("  {:20s} {:>7s} {:>6s} {:>11s} {:>8s} {:>10s} {:>7s}".format(
        "nhánh", "ứng viên", "lệnh", "ròng", "PF", "sụt", "p"))
    cf = {}
    for name, pred in AXES.items():
        sub = [c for c in cands if pred(c)]
        if not sub:
            continue
        rows, _ = E.build_book(sub, sizing, cost)
        m = metrics(rows, sizing.initial_capital)
        tk = pd.DataFrame([dict(entry_day=r.entry_day, net_pnl=r.net_pnl)
                           for r in rows if r.status == "TAKEN"])
        bb = _boot(tk) if len(tk) else {"error": "rỗng"}
        m["bootstrap"] = bb
        cf[name] = m
        print("  {:20s} {:>7d} {:>6d} {:>11,.0f} {:>8} {:>10,.0f} {:>7}".format(
            name, len(sub), m.get("trades", 0), m.get("net", 0),
            str(m.get("profit_factor")), m.get("max_dd", 0),
            bb.get("p_one_sided_vs_centred_null", "-")))
    rep["phản_thực"] = cf

    # ── Nhánh nào đáng bỏ? So PHẢN THỰC của phần còn lại với sổ gộp ───────────────────
    print()
    print("=== BỎ MỘT NHÁNH — sổ còn lại so với sổ gộp ===")
    drop = {}
    for name in ("SHORT", "ETF", "SHORT · mã đơn lẻ", "SHORT · ETF"):
        pred = AXES[name]
        sub = [c for c in cands if not pred(c)]
        rows, _ = E.build_book(sub, sizing, cost)
        m = metrics(rows, sizing.initial_capital)
        tk = pd.DataFrame([dict(entry_day=r.entry_day, net_pnl=r.net_pnl)
                           for r in rows if r.status == "TAKEN"])
        bb = _boot(tk) if len(tk) else {"error": "rỗng"}
        m["bootstrap"] = bb
        drop["bỏ " + name] = m
        print("  bỏ {:18s} lệnh {:>5}  ròng {:>11,.0f}  ({:+,.0f} so với gộp)  PF {}  p {}"
              .format(name, m.get("trades", 0), m.get("net", 0),
                      m.get("net", 0) - base.get("net", 0), str(m.get("profit_factor")),
                      bb.get("p_one_sided_vs_centred_null", "-")))
    rep["bỏ_nhánh"] = drop

    # ── Tự kiểm: quy kết phải cộng lại đúng tổng ──────────────────────────────────────
    ok1 = abs(chk - base.get("net", 0)) < 0.05
    ok2 = abs(attr["mã đơn lẻ"]["net"] + attr["ETF"]["net"] - base.get("net", 0)) < 0.05
    ok3 = attr["LONG"]["trades"] + attr["SHORT"]["trades"] == base.get("trades")
    print()
    for nm, ok in (("SC1_quy_kết_LONG+SHORT_bằng_tổng", ok1),
                   ("SC2_quy_kết_đơn_lẻ+ETF_bằng_tổng", ok2),
                   ("SC3_số_lệnh_cộng_đúng", ok3)):
        print(("[PASS] " if ok else "[FAIL] ") + nm)
    rep["self_check"] = dict(SC1=ok1, SC2=ok2, SC3=ok3)

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print("\nđã ghi", OUT)
    return 0 if all((ok1, ok2, ok3)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
