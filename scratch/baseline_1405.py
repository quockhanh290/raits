"""Baseline TRIEN KHAI ($42.459 / Calmar 1.72) duoi luat khop lenh da sua — CHI DOC.

Cho toi gio moi do tren khung 1 hop dong, khong sizing, khong cap. Bai nay dua phep hieu
chinh vao DUNG duong sinh ra baseline: deploy_sim, co sizing + net-exposure cap + breaker.

Cach lam KHONG dung file production: deploy_sim.main() import backtest_swing_tf BEN TRONG
than ham, nen thay thuoc tinh do tren module luc chay la du. Khong sua mot dong ma nao.

Bon lan chay:
  1 GOC        — deploy_sim nguyen ban. PHAI tai tao $42.459 / Calmar 1.72 (mo neo bat buoc)
  2 GOC+SUA    — cung quy uoc engine, nhung khop lenh dung o lan xet stop dau tien
  3 LIVE       — stop vu trang D+1 14:00 tren dong ho sleeve (dung luat live dang chay)
  4 LIVE+SUA   — nhu 3, khop lenh dung

    python scratch/baseline_corrected.py
"""
from __future__ import annotations
import io, sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

BASE_ARGV = ["deploy_sim",
             "--data-dir", "data/cache/futures/frozen_sim",
             "--nkd-parquet", "global_index/data/NKD_frozen_2024.parquet",
             "--regime-csv", "spy_daily_live.csv",
             "--end", "2024-12-31",
             "--n-contracts", "1",
             "--slippage-ticks", "2"]

_CACHE = {}
RATCHET = False   # luat live: stop co dinh tai muc vao lenh, khong keo theo gia


def _cache_for(df):
    from futures._validated_core import _swing_cache, daily_atr_series
    k = id(df)
    if k not in _CACHE:
        _CACHE[k] = _swing_cache(df, daily_atr_series(df))
    return _CACHE[k]


def _correct(trades, df, point_value, H):
    """Tru phan khop lenh khong the co: lenh thoat NGAY tai bar vu trang ma gia mo da o
    ben kia muc stop -> khop tai GIA MO (dung quy uoc engine dung cho GAP exit).
    Tra ve (trades da sua, so lenh sua, tong tien sua)."""
    cache = _cache_for(df)
    ts, hl = cache.get("ts", {}), cache["hl"]
    n = 0
    tot = 0.0
    out = []
    for t in trades:
        t = dict(t)
        if t["reason"] == "CHANDELIER":
            d0 = pd.Timestamp(t["day"]).normalize()
            d1 = pd.Timestamp(t["exit_day"]).normalize()
            if d1 == d0 + pd.Timedelta(days=1):
                day_ts = ts.get(d1)
                if day_ts is not None and len(day_ts):
                    naive = day_ts.tz_localize(None) if day_ts.tz is not None else day_ts
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
                                t["pnl"] = round(t["pnl"] - w * point_value, 2)
                                t["exit"] = round(op, 2)
                                n += 1
                                tot += w * point_value
        out.append(t)
    return out, n, tot


def run(tag, arm_hours, do_correct):
    """arm_hours=None -> quy uoc engine. do_correct -> ap phep sua."""
    import futures._validated_core as VC
    import global_index.deploy_sim as DS
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    orig = VC.backtest_swing_tf
    stat = {"n": 0, "tot": 0.0, "trades": 0}

    def patched(df, labels, cost, *, ema_period=20, chandelier_atr_mult=3.0,
                max_hold_days=5, **kw):
        if kw.get("return_open") or kw.get("resume_pos") is not None:
            return orig(df, labels, cost, ema_period=ema_period,
                        chandelier_atr_mult=chandelier_atr_mult,
                        max_hold_days=max_hold_days, **kw)
        if arm_hours is None:
            tr = orig(df, labels, cost, ema_period=ema_period,
                      chandelier_atr_mult=chandelier_atr_mult,
                      max_hold_days=max_hold_days, **kw)
            H = 0.0
        else:
            cfg = dict(TrendFollowStrategy().config)
            cfg["ema_period"] = ema_period
            cfg["chandelier_atr_mult"] = chandelier_atr_mult
            s = TrendFollowStrategy(cfg)
            cache = _cache_for(df)
            sig = build_sig_cache(cache, labels, s, ema_period,
                                  set(s.config["allowed_regimes"]))
            tr, _ = run_loop(df, labels, cost, strat=s, ema_period=ema_period,
                             mult=chandelier_atr_mult, max_hold_days=max_hold_days,
                             cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
                             sig_cache=sig, stop_active_hour=arm_hours, ratchet=RATCHET)
            H = arm_hours
        stat["trades"] += len(tr)
        if do_correct:
            tr, n, tot = _correct(tr, df, cost.point_value, H)
            stat["n"] += n
            stat["tot"] += tot
        return tr

    VC.backtest_swing_tf = patched
    buf = io.StringIO()
    try:
        old = sys.argv
        sys.argv = list(BASE_ARGV)
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
        if s.startswith("net $") or ("Calmar" in s and "net" in s):
            return s
    return "(khong doc duoc dong tom tat)"


def main() -> int:
    runs = [("8 LIVE 14:05 (job that) + stop CO DINH + KHOP TAI GIA THI TRUONG", 14+5/60, True)]
    saved = {}
    for tag, H, c in runs:
        print("\n" + "=" * 90)
        print("### " + tag)
        print("=" * 90)
        out, stat = run(tag, H, c)
        saved[tag] = (out, stat)
        Path("scratch").mkdir(exist_ok=True)
        Path("scratch/baseline_" + tag.split()[0] + ".txt").write_text(out, encoding="utf-8")
        print(out.strip()[-2500:])
        if c:
            print("\n  [sua] {} lenh, tong ${:,.0f} (tren co so 1 hop dong, truoc sizing)"
                  .format(stat["n"], stat["tot"]))
    print("\n" + "=" * 90)
    print("### TOM TAT — dong ket qua cua tung lan")
    print("=" * 90)
    for tag, _, _ in runs:
        print("  {:<28} {}".format(tag, grab(saved[tag][0])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
