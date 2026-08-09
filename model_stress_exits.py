"""STRESS_MID: luật thoát đã kiểm định vs luật live sẽ thật sự chạy.

Adapter (đã kiểm định) có BA đường thoát: chạm stop, chạm target 2R, hoặc đóng 14:00.
Live hiện thực được một:
  - stop   : STP đặt ngay lúc khớp — khớp luật, vì adapter cũng xét stop từ bar vào lệnh
  - target : `to_candidate` chỉ giữ entry+stop, VỨT BỎ target → không có lệnh nào
  - 14:00  : `_mark_held_unchanged` không gọi cho cluster stress, nên
             `diff_desired_vs_held` đưa vị thế vào `exits` ở lần chạy kế tiếp

Nhánh C phải quét N phút chứ không đặt một con số: "đóng ở slot kế tiếp" phụ thuộc nhịp
cron 10:20 ET CHƯA TỒN TẠI, chưa ai quyết là 5 hay 15 phút.

Vào lệnh giữ nguyên ở cả ba nhánh — `reconcile_stress.py` đã chứng minh entry/stop/target
của đường live khớp adapter (112 ngày Stress, 0 lệch), nên chỉ đường thoát là biến.

CỔNG: nhánh A phải tái tạo StressMidEngine().backtest() từng lệnh. Không khớp thì dừng.

    python model_stress_exits.py --data-dir data\\cache\\futures --regime-csv spy_daily_live.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CWD = Path.cwd()
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

import pandas as pd


def run_arm(df, labels, cost, adapter, *, use_target: bool, hold_minutes=None,
            entry_delay_min: float = 0.0, exit_extra_min: float = 0.0):
    """Vòng lặp thoát của adapter, chép lại, với hai công tắc.

    use_target=True + hold_minutes=None  ==  đúng adapter (nhánh A, dùng làm cổng).
    """
    from futures._validated_core import resample_5m

    out = []
    for day, g in df.groupby(df.index.normalize()):
        key = pd.Timestamp(day).tz_localize(None).normalize()
        if labels.get(key) not in adapter.allowed:
            continue
        bars = resample_5m(g)
        # Cat rong hon 14:00 de exit_extra_min co the nhin qua moc do. Ban dau cat
        # dung 14:00 nen tham so nay khong lam gi — lo ra vi cot 14:00 va 14:10 trung
        # khit tung dong. Moi thu khac (open_px, vwap, swing) deu <= 10:15 nen khong doi;
        # nhanh cong doi chieu co _exit_cap = 14:00 nen van tai tao dung adapter.
        d = bars.between_time("09:30", "15:00")
        if len(d) < 5:
            continue
        open_px = float(d.iloc[0]["open"])
        at_entry = d[d.index.time == adapter.ENTRY]
        if at_entry.empty:
            continue
        entry = float(at_entry.iloc[-1]["close"])
        pre = d[d.index.time <= adapter.ENTRY]
        vwap = adapter._vwap(pre)
        if entry >= vwap or entry >= open_px:
            continue
        swing = d[(d.index.time >= adapter.SWING_START) & (d.index.time <= adapter.ENTRY)]
        ref = float(swing["high"].max()) if not swing.empty else entry * 1.005
        stop = ref * (1 + adapter.STOP_PAD)
        stop_dist = stop - entry
        if stop_dist <= 0 or stop_dist / entry > adapter.MAX_STOP_PCT:
            continue
        target = entry - adapter.TARGET_RR * stop_dist

        # Gia vao troi theo do tre; muc stop KHONG tinh lai — he thong tinh no tu bar
        # tin hieu 10:15 roi gui nguyen vay. Dung loai sai lech da lam hong vu swing.
        entry_ts = at_entry.index[-1]
        if entry_delay_min > 0:
            _after = d[d.index > entry_ts + pd.Timedelta(minutes=entry_delay_min - 5)]
            if _after.empty:
                continue
            entry_ts = _after.index[0]
            entry = float(_after.iloc[0]["close"])

        # Gio thoat: slot 14:05 chay xong ~14:10, khong phai 14:00 chan
        _exit_cap = (pd.Timestamp.combine(d.index[0].date(), adapter.EXIT)
                     + pd.Timedelta(minutes=exit_extra_min)).time()
        fwd = d[(d.index > entry_ts) & (d.index.time <= _exit_cap)]
        if fwd.empty:
            continue
        # cửa sổ giữ lệnh: live đóng sau N phút thay vì tới 14:00
        if hold_minutes is not None:
            cut = entry_ts + pd.Timedelta(minutes=hold_minutes)
            fwd = fwd[fwd.index <= cut]
            if fwd.empty:
                continue

        ex, reason = float(fwd.iloc[-1]["close"]), "eod"
        for ts, bar in fwd.iterrows():
            if float(bar["high"]) >= stop:                      # stop trước target
                ex, reason = stop, "stop"
                break
            if use_target and float(bar["low"]) <= target:
                ex, reason = target, "target"
                break
        pts = entry - ex                                        # SHORT
        out.append(dict(day=pd.Timestamp(day).date(), entry=round(entry, 2),
                        exit=round(ex, 2), points=round(pts, 2),
                        pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                        reason=reason))
    return out


def _tot(rows_by_inst):
    n = sum(len(v) for v in rows_by_inst.values())
    p = sum(t["pnl"] for v in rows_by_inst.values() for t in v)
    w = sum(1 for v in rows_by_inst.values() for t in v if t["pnl"] > 0)
    rs = {}
    for v in rows_by_inst.values():
        for t in v:
            rs[t["reason"]] = rs.get(t["reason"], 0) + 1
    return n, p, w, rs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--hold", type=float, nargs="*", default=[5, 10, 15, 30, 60, 120])
    a = ap.parse_args()

    from futures._validated_core import StressMidAdapter
    from futures.basket import BASKET
    from futures.stress_mid import StressMidEngine
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket

    eng = StressMidEngine()
    adapter = StressMidAdapter({"target_rr": eng.target_rr,
                                "max_stop_pct": eng.max_stop_pct,
                                "stop_pad": eng.stop_pad})
    dfs = load_basket(a.data_dir)
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket()

    print()
    print("=" * 84)
    print("CONG DOI CHIEU — nhanh A (stop/target/14:00) phai trung adapter tung lenh")
    print("=" * 84)
    base = {}
    ok = True
    for name in BASKET:
        ref = eng.backtest(dfs[name], labels, costs[name])
        mine = run_arm(dfs[name], labels, costs[name], adapter, use_target=True)
        bad = (len(ref) != len(mine)) or any(
            r["day"] != m["day"] or abs(r["pnl"] - m["pnl"]) > 0.005
            or abs(r["entry"] - m["entry"]) > 0.005 or abs(r["exit"] - m["exit"]) > 0.005
            or (r.get("exit_reason") or "") != m["reason"]
            for r, m in zip(ref, mine))
        print(f"  {name}: adapter {len(ref)} lenh | ban chep {len(mine)} | "
              f"{'KHOP' if not bad else 'LECH'}")
        base[name] = mine
        ok &= not bad
    if not ok:
        print()
        print("*** CONG KHONG DAT — dung, so sau do khong dung duoc ***")
        return 1

    n, p, w, rs = _tot(base)
    print()
    print(f"  -> dat. Nen: {n} lenh, ${p:+,.0f}, thang {100 * w / n if n else 0:.0f}%")
    print("     ly do thoat: " + "  ".join(
        f"{k}={v} ({100 * v / n:.0f}%)" for k, v in sorted(rs.items())))

    print()
    print("=" * 84)
    print("LUAT THOAT — A: da kiem dinh | B: mat target | C: mat target + dong sau N phut")
    print("=" * 84)
    print(f"  {'nhanh':<34} | {'lenh':>6} | {'P&L':>11} | {'thang':>6} | ly do thoat")
    print("  " + "-" * 96)

    def _row(label, rows):
        n, p, w, rs = _tot(rows)
        rtxt = "  ".join(f"{k}={v}" for k, v in sorted(rs.items()))
        print(f"  {label:<34} | {n:>6} | ${p:>+10,.0f} | "
              f"{100 * w / n if n else 0:>5.0f}% | {rtxt}")

    _row("A  da kiem dinh (stop/target/14:00)", base)
    b = {nm: run_arm(dfs[nm], labels, costs[nm], adapter, use_target=False)
         for nm in BASKET}
    _row("B  mat target, van giu toi 14:00", b)
    for h in a.hold:
        c = {nm: run_arm(dfs[nm], labels, costs[nm], adapter,
                         use_target=False, hold_minutes=h)
             for nm in BASKET}
        _row(f"C  live that: dong sau {int(h)} phut", c)

    print("  " + "-" * 96)
    print("  D = noi code hien tai, 1 slot sang 10:20, khong co slot xen giua")
    print("      (mat target + gia vao tre + thoat muon hon 14:00)")
    for ed in (5.0, 10.0, 15.0):
        for xx in (0.0, 10.0):
            dd = {nm: run_arm(dfs[nm], labels, costs[nm], adapter, use_target=False,
                              entry_delay_min=ed, exit_extra_min=xx)
                  for nm in BASKET}
            _row(f"D  vao tre {int(ed)}p, thoat 14:{int(xx):02d}", dd)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
