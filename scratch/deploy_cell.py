"""deploy_sim cho o walk-forward dung lai: ema=30, max_hold=7, stop = 2,5 x ATR ngay.

CHI DOC. Khong sua file production — thay thuoc tinh backtest_swing_tf tren module luc chay.
Ap CHI cho Ro 4 (nhan dien bang ema_period=30); NKD giu nguyen luat cua no (ema=10).
Vu trang D+1 14:05 tren dong ho sleeve, ratchet=False, khop tai gia thi truong luc dat lenh.

Chay hai lan: (A) tho, (B) da sua khop lenh.
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

ARM = 14 + 5 / 60
NEW_HOLD = 7
NEW_F = 2.5
_C, _D = {}, {}


def cache_for(df):
    from futures._validated_core import _swing_cache, daily_atr_series
    k = id(df)
    if k not in _C:
        _D[k] = daily_atr_series(df)
        _C[k] = _swing_cache(df, _D[k])
    return _C[k], _D[k]


def correct(trades, df, pv):
    cache, _ = cache_for(df)
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
                    arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
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


def run(do_correct):
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
        cfg = dict(TrendFollowStrategy().config)
        cfg["ema_period"] = ema_period
        cfg["chandelier_atr_mult"] = chandelier_atr_mult
        s = TrendFollowStrategy(cfg)
        cache, datr = cache_for(df)
        sig = build_sig_cache(cache, labels, s, ema_period,
                              set(s.config["allowed_regimes"]))
        hold = max_hold_days
        is_roska4 = (ema_period == 30)      # NKD chay ema=10
        if is_roska4:
            hold = NEW_HOLD
            sg = {}
            for day, (ts_, g) in sig.items():
                try:
                    da = float(datr.asof(pd.Timestamp(day)))
                except Exception:
                    continue
                if not np.isfinite(da) or da <= 0:
                    continue
                g2 = dict(g)
                ep = float(g2["entry_price"])
                g2["initial_stop"] = (ep - NEW_F * da) if g2["direction"] == "LONG" \
                    else (ep + NEW_F * da)
                sg[day] = (ts_, g2)
            sig = sg
        tr, _ = run_loop(df, labels, cost, strat=s, ema_period=ema_period,
                         mult=chandelier_atr_mult, max_hold_days=hold, cache=cache,
                         same_day_stop=False, stop_slip_ticks=0.0, sig_cache=sig,
                         stop_active_hour=ARM, ratchet=False)
        if do_correct:
            tr, n, tot = correct(tr, df, cost.point_value)
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


def main() -> int:
    for tag, c in (("A — o moi, THO", False), ("B — o moi, DA SUA KHOP LENH", True)):
        print("\n" + "=" * 88)
        print("### {}  (Ro 4: ema=30 hold={} stop={}xATR ngay | NKD giu nguyen)"
              .format(tag, NEW_HOLD, NEW_F))
        print("=" * 88)
        out, stat = run(c)
        Path("scratch").mkdir(exist_ok=True)
        Path("scratch/deploy_cell_" + tag.split()[0] + ".txt").write_text(out, encoding="utf-8")
        print(out.strip()[-1800:])
        if c:
            print("\n  [sua] {} lenh, tong ${:,.0f} (co so 1 hop dong, truoc sizing)"
                  .format(stat["n"], stat["tot"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
