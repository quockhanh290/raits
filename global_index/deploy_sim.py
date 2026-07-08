"""
global_index/deploy_sim.py — "đúng như khi vào trade thực tế" (deploy-realistic)
================================================================================
Everything earlier ran 1 micro each with $500-fixed risk for cap counting. This
replays as close to live as a backtest can:

  • SIZER (real): contracts per instrument chosen so the COMBINED portfolio's
    expected DD ≤ target 10% (buffer under hard 15%) AND margin ≤ 40% of account.
    Same logic as futures/sizer.py, applied to the 3-cluster combined curve.
  • RISK PER ENTRY (real): risk$ = contracts × (chandelier_mult × daily_ATR at the
    entry day) × point_value — the actual initial stop distance, not a $500 stub.
    Computed by re-deriving daily ATR per instrument (engine doesn't store it; we
    do NOT touch _validated_core).
  • MULTI-CLUSTER exposure (real risk$) + ACCOUNT circuit breaker (DD combined).

Reports the sized contracts, binding constraint, and deploy metrics in $ AND %
(return%/yr, MaxDD%) — the numbers that actually answer "deploy $50k → what".

HONEST LIMIT: even this is an UPPER BOUND. It still assumes backtest fills at
1-tick slippage; live MNKD is thin and will slip more, fills can be partial, and
unseen events aren't here. Paper trading remains the only clean OOS left.

    python -m global_index.deploy_sim --data-dir data\\cache\\futures \
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \
        --regime-csv spy_daily.csv --include-stress
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels
    from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels
    from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(pnl=0.0, pf=0.0, calmar=0.0, sharpe=0.0, maxdd=0.0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(pnl=float(daily.sum()), pf=float(w/l) if l > 1e-9 else float("inf"),
                calmar=float((daily.sum()/span)/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                maxdd=dd)


def replay(all_trades, account, guard, contracts_by_inst, breaker_cls):
    """Chronological replay at the SIZED contract count, real risk$ per entry."""
    breaker = breaker_cls(account=account) if breaker_cls else None
    days = sorted({t["entry"] for t in all_trades} | {t["exit"] for t in all_trades})
    by_entry = {}
    for t in all_trades:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos, realized = [], {}
    equity = account
    taken = {c: 0 for c in guard.clusters}; rej = {c: 0 for c in guard.clusters}; halt = 0
    cur_day = None

    for day in days:
        # exits
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl_sized"]; realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                still.append((pos, t))
        open_pos = still

        allow = True
        if breaker is not None:
            if cur_day is None or day != cur_day:
                breaker.start_day(equity); cur_day = day
            breaker.update(equity)
            allow = breaker.status(equity).get("allow_new_entries", True)

        for t in sorted(by_entry.get(day, []), key=entry_priority_key):
            if not allow:
                halt += 1; continue
            n = contracts_by_inst.get(t["inst"], 1)
            pos = Position(t["inst"], t["direction"], n, t["risk_sized"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rej[t["cluster"]] += 1; continue
            taken[t["cluster"]] += 1
            if t["exit"] == day:
                equity += t["pnl_sized"]; realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                open_pos.append((pos, t))

    return pd.Series(realized).sort_index(), dict(taken=taken, rejected=rej, halted=halt)


def size_combined(combined_1micro_maxdd, base_margin, account,
                  target_dd_pct=0.10, hard_dd_pct=0.15, margin_budget_pct=0.40):
    target_dd = account * target_dd_pct
    dd_scale = target_dd / combined_1micro_maxdd if combined_1micro_maxdd > 0 else 1.0
    margin_scale = (account * margin_budget_pct) / base_margin if base_margin > 0 else 1.0
    scale = min(dd_scale, margin_scale)
    binding = "drawdown" if dd_scale <= margin_scale else "margin"
    n = max(1, int(scale))
    while n > 1 and n * combined_1micro_maxdd > account * hard_dd_pct:
        n -= 1; binding = "drawdown (hard-cap clamp)"
    return n, dict(dd_scale=dd_scale, margin_scale=margin_scale, binding=binding,
                   proj_dd_pct=n * combined_1micro_maxdd / account)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--include-stress", action="store_true")
    ap.add_argument("--nkd-instrument", default="MNKD", choices=list(gi_specs.SPECS.keys()))
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--nkd-mult", type=float, default=2.5)
    ap.add_argument("--roska4-mult", type=float, default=2.5, help="Rổ-4 chandelier mult (validated 2.5)")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--slippage-ticks", type=float, default=1.0,
                    help="raise (e.g. 2-3) to stress thin MNKD fills toward realism")
    ap.add_argument("--no-nkd", action="store_true",
                    help="exclude NKD → Rổ-4-only baseline through the SAME risk layer "
                         "(apples-to-apples to measure NKD's true contribution)")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    ap.add_argument("--n-contracts", type=int, default=None,
                    help="pin contract count instead of auto-sizing from period maxDD. "
                         "Use --n-contracts 1 for vault tests to match production config "
                         "(IS baseline n=1 because COVID 2020 dominates the full-history maxDD).")
    a = ap.parse_args()

    if (a.start or a.end) and a.n_contracts is None:
        print(
            "\nWARNING: --start/--end without --n-contracts\n"
            "  Sizer will auto-size from this period's maxDD.\n"
            "  If the period excludes COVID-2020, auto-n may be 2-3 (not production n=1).\n"
            "  Add --n-contracts 1 for vault/subset tests.\n"
        )

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from futures._validated_core import (load_parquet, benchmark_daily, label_regimes,
                                         backtest_swing_tf, daily_atr_series)
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import SwingTFEngine, costs_for_basket
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    def clip(df):
        if a.start: df = df[df.index >= pd.Timestamp(a.start).tz_localize(df.index.tz)]
        if a.end:   df = df[df.index <= pd.Timestamp(a.end).tz_localize(df.index.tz)]
        return df

    # ── Rổ 4 ────────────────────────────────────────────────────────────────
    dfs = {n: clip(load_parquet(str(Path(a.data_dir) / data_filename(c)))) for n, c in BASKET.items()}
    atr = {n: daily_atr_series(df) for n, df in dfs.items()}            # real ATR per instrument
    pv = {n: c.point_value for n, c in BASKET.items()}
    bench_full = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench_full, a.hmm_train_end, 3, a.hmm_fit_end)
    bench = bench_full
    if a.start: bench = bench[bench.index >= pd.Timestamp(a.start)]
    if a.end:   bench = bench[bench.index <= pd.Timestamp(a.end)]
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    stress = None
    if a.include_stress:
        from futures.stress_mid import StressMidEngine
        stress = StressMidEngine().backtest_basket(dfs, labels, costs)

    # ── NKD ─────────────────────────────────────────────────────────────────
    c = gi_specs.SPECS[a.nkd_instrument]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), a.hmm_train_end, 3, a.hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index); spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ndf = gi_load(a.nkd_parquet); ndf.index = ndf.index.tz_convert(c.session_tz); ndf = clip(ndf)
    natr = daily_atr_series(ndf)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=a.slippage_ticks)
    nkd = backtest_swing_tf(ndf, nlab, ncost, ema_period=a.nkd_ema,
                            chandelier_atr_mult=a.nkd_mult, max_hold_days=5, gap_fill=True)

    # ── assemble trades with REAL per-entry risk$ (chandelier stop × pv) ──────
    def real_risk(atr_series, mult, point_value, entry_day, contracts):
        try:
            av = atr_series.asof(pd.Timestamp(entry_day))
        except Exception:
            av = np.nan
        if av is None or pd.isna(av):
            av = float(atr_series.median())          # fallback: typical ATR
        return contracts * mult * float(av) * point_value

    all_tr = []
    for inst, lst in swing.items():
        for t in lst:
            all_tr.append(dict(inst=inst, cluster="roska4_swing", entry=pd.Timestamp(t["day"]),
                               exit=pd.Timestamp(t["exit_day"]), direction=t["direction"],
                               pnl1=t["pnl"], atr=atr[inst], mult=a.roska4_mult, pv=pv[inst]))
    if a.include_stress and stress:
        for inst, lst in stress.items():
            for t in lst:
                all_tr.append(dict(inst=inst, cluster="roska4_stress", entry=pd.Timestamp(t["day"]),
                                   exit=pd.Timestamp(t["exit_day"]), direction=t["direction"],
                                   pnl1=t["pnl"], atr=atr[inst], mult=a.roska4_mult, pv=pv[inst]))
    if not a.no_nkd:
        for t in nkd:
            ed = pd.Timestamp(t["day"]).tz_localize(None)
            xd = (pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed)
            all_tr.append(dict(inst=a.nkd_instrument, cluster="global_nkd", entry=ed, exit=xd,
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=natr, mult=a.nkd_mult, pv=c.point_value))
    # NKD atr indexed by JST date; entry stored tz-naive JST date → asof matches
    for t in all_tr:
        if t["cluster"] == "global_nkd":
            t["_atr_entry"] = pd.Timestamp(t["entry"])
        else:
            t["_atr_entry"] = pd.Timestamp(t["entry"])

    # ── 1-micro combined MaxDD (for the sizer) ───────────────────────────────
    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"] = t["pnl1"] * 1
    guard0 = MultiClusterGuard(account=a.account)
    d1, _ = replay(all_tr, a.account, guard0, {}, CircuitBreaker)
    m1 = metrics(d1)

    base_margin = sum(BASKET[n].est_margin for n in BASKET) + c.est_margin
    auto_n, sz = size_combined(m1["maxdd"], base_margin, a.account)
    if a.n_contracts is not None:
        # Production-config override: vault tests must pin n to match IS baseline
        # (IS baseline n=1 because COVID 2020 dominates full-history maxDD; vault
        # windows without COVID auto-size to n=2-3, testing a different config).
        n_contracts = a.n_contracts
        sz["dd_scale"] = sz.get("dd_scale", 0); sz["binding"] = "FIXED (--n-contracts override)"
        sz["proj_dd_pct"] = n_contracts * m1["maxdd"] / a.account
    else:
        n_contracts = auto_n

    # ── replay at SIZED contracts, real risk$ scaled by contracts ────────────
    # NKD fixed at n=1: budget 2% = $1,000 only fits 1 MNKD (risk ~$400-500/contract).
    # Rổ 4 scales with n_contracts; NKD does not scale.
    contracts_by = {n: n_contracts for n in BASKET}
    contracts_by[a.nkd_instrument] = 1
    for t in all_tr:
        n = 1 if t["cluster"] == "global_nkd" else n_contracts
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"] = t["pnl1"] * n
    guard = MultiClusterGuard(account=a.account)
    sized_daily, st = replay(all_tr, a.account, guard, contracts_by, CircuitBreaker)
    msz = metrics(sized_daily)

    yrs = max((sized_daily.index[-1] - sized_daily.index[0]).days / 365.25, 0.1) if len(sized_daily) else 1
    nkd_tag = "" if a.no_nkd else "+ NKD "
    print(f"\n{'='*72}\nDEPLOY-REALISTIC SIM | Rổ 4 {'+ STRESS ' if a.include_stress else ''}{nkd_tag}| ${a.account:,.0f}")
    print(f"{'='*72}")
    print(f"slippage {a.slippage_ticks:g} tick/side | NKD gated ema={a.nkd_ema} mult={a.nkd_mult}\n")

    print("SIZER (combined 3-cluster, DD-capped):")
    print(f"  1-micro combined MaxDD : ${m1['maxdd']:,.0f}  ({m1['maxdd']/a.account:.1%} of account)")
    print(f"  dd_scale {sz['dd_scale']:.2f} | margin_scale {sz['margin_scale']:.2f} "
          f"→ binding: {sz['binding']}")
    print(f"  → CONTRACTS: {n_contracts} micro each  "
          f"(projected DD {sz['proj_dd_pct']:.1%}, hard cap 15%)\n")

    print(f"DEPLOY METRICS at {n_contracts} micro:")
    print(f"  net ${msz['pnl']:,.0f}  |  Calmar {msz['calmar']:.2f}  |  PF {msz['pf']:.2f}  |  "
          f"Sharpe {msz['sharpe']:.2f}")
    print(f"  MaxDD ${msz['maxdd']:,.0f} ({msz['maxdd']/a.account:.1%})  |  "
          f"return ≈ {msz['pnl']/a.account/yrs:.1%}/yr on ${a.account:,.0f}")

    print("\n  per-cluster entries taken / rejected (REAL risk$):")
    for cl in guard.clusters:
        print(f"    {cl:<14} taken {st['taken'][cl]:>4}  rejected {st['rejected'][cl]:>3}")
    print(f"    circuit-breaker halts: {st['halted']}")

    print("\nper-year net$ (deploy size):")
    for y, g in sized_daily.groupby(sized_daily.index.year):
        print(f"  {y}  ${g.sum():>10,.0f}")
    print("-"*72)
    print("NOTE: upper bound. Live MNKD slips >1 tick (rerun --slippage-ticks 2-3 to see), "
          "fills partial, unseen events absent. Paper trade is the real test.\n")


if __name__ == "__main__":
    main()
