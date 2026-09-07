"""Dung lai SAN CALMAR va HAI VAULT tren thuoc do da sua khop lenh — CHI DOC.

Ba moc dang ghim trong INVARIANTS, moi moc chay ba bien the:
  GOC        — deploy_sim nguyen ban. PHAI tai tao dung so ghim (mo neo bat buoc).
  ENGINE+SUA — cung quy uoc engine (stop xet tu ranh gioi ngay), nhung khop lenh dung
               o lan xet stop dau tien. Day la CONG duoc dung lai dung co so.
  LIVE+SUA   — luat live that (vu trang D+1 14:05 dong ho sleeve, stop co dinh khong
               ratchet), khop lenh dung. Day la thu live thuc su bi do.

Khong sua file production — thay thuoc tinh backtest_swing_tf tren module luc chay.
STRESS_MID di duong rieng, khong bi dung toi (no khong hoan stop).

    python scratch/rederive_gates.py
"""
from __future__ import annotations
import io, sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ARM = 14 + 5 / 60

ARTIFACTS = [
    ("SAN fit_A (floor)", ["--data-dir", "data/cache/futures/frozen_sim",
                           "--nkd-parquet", "global_index/data/NKD_frozen_2024.parquet",
                           "--regime-csv", "spy_daily_live.csv",
                           "--end", "2024-12-31", "--hmm-fit-end", "2022-12-31",
                           "--n-contracts", "1", "--slippage-ticks", "2"],
     "Calmar 1.65 / net $42,565"),
    ("VAULT 2023-2024", ["--data-dir", "data/cache/futures/frozen_sim",
                         "--nkd-parquet", "global_index/data/NKD_frozen_2024.parquet",
                         "--regime-csv", "spy_daily_live.csv",
                         "--start", "2023-01-01", "--end", "2024-12-31",
                         "--hmm-fit-end", "2022-12-31",
                         "--n-contracts", "1", "--slippage-ticks", "2"],
     "Calmar 2.86 / net $10,757"),
    ("VAULT 2025", ["--data-dir", "data/cache/futures/frozen_2025_sim",
                    "--nkd-parquet", "global_index/data/NKD_frozen_2025.parquet",
                    "--regime-csv", "spy_daily_live.csv",
                    "--start", "2025-01-01", "--end", "2025-12-31",
                    "--hmm-fit-end", "2024-12-31",
                    "--n-contracts", "1", "--slippage-ticks", "2", "--include-stress"],
     "Calmar 2.54 / net $7,404"),
]

_C, _D = {}, {}


def cache_for(df):
    from futures._validated_core import _swing_cache, daily_atr_series
    k = id(df)
    if k not in _C:
        _D[k] = daily_atr_series(df)
        _C[k] = _swing_cache(df, _D[k])
    return _C[k]


def correct(trades, df, pv, H):
    cache = cache_for(df)
    ts, hl = cache.get("ts", {}), cache["hl"]
    out, n, tot = [], 0, 0.0
    for t in trades:
        t = dict(t)
        if t["reason"] == "CHANDELIER":
            d0 = pd.Timestamp(t["day"]).normalize()
            d1 = pd.Timestamp(t["exit_day"]).normalize()
            if d1 == d0 + pd.Timedelta(days=1):
                dts = ts.get(d1)
                if dts is not None and len(dts):
                    naive = dts.tz_localize(None) if dts.tz is not None else dts
                    arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
                    j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
                    et = t.get("exit_time")
                    if j < len(naive) and et is not None:
                        et = pd.Timestamp(et)
                        if et.tzinfo is not None:
                            et = et.tz_localize(None)
                        if et == pd.Timestamp(naive[j]):
                            op = float(hl[d1][2][j])
                            stp = float(t["exit"])
                            w = (stp - op) if t["direction"] == "LONG" else (op - stp)
                            if w > 0:
                                t["pnl"] = round(t["pnl"] - w * pv, 2)
                                t["exit"] = round(op, 2)
                                n += 1
                                tot += w * pv
        out.append(t)
    return out, n, tot


def run(argv, mode):
    """mode: 'goc' | 'engine' | 'live'"""
    import futures._validated_core as VC
    import global_index.deploy_sim as DS
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    orig = VC.backtest_swing_tf
    stat = {"n": 0, "tot": 0.0}

    def patched(df, labels, cost, *, ema_period=20, chandelier_atr_mult=3.0,
                max_hold_days=5, **kw):
        if kw.get("return_open") or kw.get("resume_pos") is not None:
            return orig(df, labels, cost, ema_period=ema_period,
                        chandelier_atr_mult=chandelier_atr_mult,
                        max_hold_days=max_hold_days, **kw)
        if mode == "engine":
            tr = orig(df, labels, cost, ema_period=ema_period,
                      chandelier_atr_mult=chandelier_atr_mult,
                      max_hold_days=max_hold_days, **kw)
            H = 0.0
        else:
            cfg = dict(TrendFollowStrategy().config)
            cfg["ema_period"] = ema_period
            cfg["chandelier_atr_mult"] = chandelier_atr_mult
            s = TrendFollowStrategy(cfg)
            cache = cache_for(df)
            sig = build_sig_cache(cache, labels, s, ema_period,
                                  set(s.config["allowed_regimes"]))
            tr, _ = run_loop(df, labels, cost, strat=s, ema_period=ema_period,
                             mult=chandelier_atr_mult, max_hold_days=max_hold_days,
                             cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sig, stop_active_hour=ARM, ratchet=False)
            H = ARM
        tr, n, tot = correct(tr, df, cost.point_value, H)
        stat["n"] += n
        stat["tot"] += tot
        return tr

    if mode != "goc":
        VC.backtest_swing_tf = patched
    buf = io.StringIO()
    try:
        old = sys.argv
        sys.argv = ["deploy_sim"] + list(argv)
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old
    finally:
        VC.backtest_swing_tf = orig
    return buf.getvalue(), stat


def grab(out):
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("net $"):
            return s
    return "(khong doc duoc)"


def maxdd(out):
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("MaxDD $"):
            return s
    return ""


def main() -> int:
    rows = []
    for name, argv, pinned in ARTIFACTS:
        print("\n" + "#" * 92)
        print("### {}   (so ghim: {})".format(name, pinned))
        print("#" * 92, flush=True)
        for mode, label in (("goc", "GOC (mo neo)"),
                            ("engine", "ENGINE + SUA KHOP LENH"),
                            ("live", "LIVE 14:05 + SUA KHOP LENH")):
            out, stat = run(argv, mode)
            Path("scratch").mkdir(exist_ok=True)
            fn = "scratch/gate_{}_{}.txt".format(name.split()[0].lower(), mode)
            Path(fn).write_text(out, encoding="utf-8")
            line = grab(out)
            print("  {:<28} {}".format(label, line))
            print("  {:<28} {}".format("", maxdd(out)))
            if mode != "goc":
                print("  {:<28} [sua {} lenh, ${:,.0f}]".format("", stat["n"], stat["tot"]))
            rows.append((name, label, line, maxdd(out)))
            sys.stdout.flush()

    print("\n" + "=" * 92)
    print("TOM TAT")
    print("=" * 92)
    for name, label, line, dd in rows:
        print("  {:<20} {:<28} {}".format(name, label, line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
