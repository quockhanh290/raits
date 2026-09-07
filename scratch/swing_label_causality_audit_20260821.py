from __future__ import annotations

import argparse
import io
import math
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
from futures.basket import BASKET, REGIME, SWING_TF_PARAM, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from global_index.deploy_sim import metrics, replay, size_combined
from global_index.net_exposure_multi import MultiClusterGuard
from scratch.harness import ARGV


ACCOUNT = 50_000.0


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def lag1(labels: dict[pd.Timestamp, str]) -> dict[pd.Timestamp, str]:
    s = pd.Series(labels).sort_index()
    s.index = pd.DatetimeIndex(s.index).normalize()
    shifted = s.shift(1).dropna()
    return {pd.Timestamp(k).normalize(): str(v) for k, v in shifted.items()}


def clip(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    if end:
        df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
    return df


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return math.inf
    wins = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    losses = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses else math.inf


def trade_df(trades_by_inst: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for inst, trades in trades_by_inst.items():
        for t in trades:
            r = dict(t)
            r["inst"] = inst
            r["day"] = pd.Timestamp(r["day"]).normalize()
            r["exit_day"] = pd.Timestamp(r["exit_day"]).normalize()
            rows.append(r)
    if not rows:
        return pd.DataFrame(columns=["inst", "day", "exit_day", "direction", "pnl", "regime"])
    return pd.DataFrame(rows).sort_values(["day", "inst", "exit_day"]).reset_index(drop=True)


def dense_daily(tr: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    if tr.empty:
        return pd.Series(0.0, index=sessions)
    sparse = tr.groupby("exit_day")["pnl"].sum().sort_index()
    use = sessions[(sessions >= sparse.index.min()) & (sessions <= sparse.index.max())]
    dense = pd.Series(0.0, index=use)
    dense.loc[sparse.index] = sparse.values
    return dense


def summarize_trades(name: str, tr: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    daily = dense_daily(tr, sessions)
    m = metrics(daily)
    return {
        "name": name,
        "trades": int(len(tr)),
        "entry_days": int(tr["day"].nunique()) if not tr.empty else 0,
        "net": float(tr["pnl"].sum()) if not tr.empty else 0.0,
        "pf": pf(tr),
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
    }


def load_window(which: str):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    regime_csv = arg_from(argv, "--regime-csv", "spy_daily_live.csv")
    hmm_fit_end = arg_from(argv, "--hmm-fit-end", REGIME["hmm_fit_end"])
    slippage = float(arg_from(argv, "--slippage-ticks", 2.0))

    dfs = {
        name: clip(load_parquet(str(Path(data_dir) / data_filename(contract))), start, end)
        for name, contract in BASKET.items()
    }
    atrs = {name: daily_atr_series(df) for name, df in dfs.items()}
    bench = benchmark_daily(regime_csv)
    labels0 = label_regimes(bench, "2018-01-01", REGIME["n_components"], hmm_fit_end)
    labels1 = lag1(labels0)
    costs = costs_for_basket(slippage_ticks=slippage)
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return argv, dfs, atrs, labels0, labels1, costs, sessions


def label_impact(labels0: dict, labels1: dict, sessions: pd.DatetimeIndex) -> dict:
    days = [d for d in sessions if d in labels0 or d in labels1]
    comparable = [d for d in days if d in labels0 and d in labels1]
    flips = [d for d in comparable if labels0[d] != labels1[d]]
    return {
        "lag0_labeled": sum(1 for d in sessions if d in labels0),
        "lag1_labeled": sum(1 for d in sessions if d in labels1),
        "comparable": len(comparable),
        "flips": len(flips),
        "flips_by_pair": pd.Series(
            [f"{labels0[d]}->{labels1[d]}" for d in flips], dtype="object"
        ).value_counts().to_dict(),
    }


def changed_trade_days(tr0: pd.DataFrame, tr1: pd.DataFrame) -> dict:
    d0 = set(tr0["day"]) if not tr0.empty else set()
    d1 = set(tr1["day"]) if not tr1.empty else set()
    only0 = d0 - d1
    only1 = d1 - d0
    both = d0 & d1
    return {
        "lag0_only_days": len(only0),
        "lag1_only_days": len(only1),
        "both_days": len(both),
        "lag0_only_pnl": float(tr0.loc[tr0["day"].isin(only0), "pnl"].sum()) if len(tr0) else 0.0,
        "lag1_only_pnl": float(tr1.loc[tr1["day"].isin(only1), "pnl"].sum()) if len(tr1) else 0.0,
        "both_lag0_pnl": float(tr0.loc[tr0["day"].isin(both), "pnl"].sum()) if len(tr0) else 0.0,
        "both_lag1_pnl": float(tr1.loc[tr1["day"].isin(both), "pnl"].sum()) if len(tr1) else 0.0,
    }


def per_year(tr: pd.DataFrame) -> dict[int, float]:
    if tr.empty:
        return {}
    return {int(y): float(g["pnl"].sum()) for y, g in tr.groupby(tr["exit_day"].dt.year)}


def per_instrument(tr: pd.DataFrame) -> dict[str, float]:
    if tr.empty:
        return {}
    return {str(k): float(v) for k, v in tr.groupby("inst")["pnl"].sum().items()}


def build_r4(dfs, labels, costs) -> pd.DataFrame:
    eng = SwingTFEngine(
        ema_period=SWING_TF_PARAM["ema_period"],
        chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
        max_hold_days=SWING_TF_PARAM["max_hold_days"],
    )
    return trade_df(eng.backtest_basket(dfs, labels, costs, gap_fill=True))


def combined_deploy_daily(which: str, r4_tr: pd.DataFrame, atrs: dict[str, pd.Series],
                          argv: list[str]) -> tuple[pd.Series, dict]:
    from futures.circuit_breaker import CircuitBreaker
    from global_index import specs as gi_specs
    from global_index._core import FuturesCost as GIFC
    from global_index._core import load_parquet as gi_load
    from global_index.regime import RegimeLabels
    from futures._validated_core import backtest_swing_tf

    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    regime_csv = arg_from(argv, "--regime-csv", "spy_daily_live.csv")
    hmm_fit_end = arg_from(argv, "--hmm-fit-end", REGIME["hmm_fit_end"])
    nkd_parquet = arg_from(argv, "--nkd-parquet")
    nkd_inst = arg_from(argv, "--nkd-instrument", "MNKD")
    slippage = float(arg_from(argv, "--slippage-ticks", 2.0))
    fixed_contracts = arg_from(argv, "--n-contracts")

    def real_risk(atr_series, mult, point_value, entry_day, contracts):
        try:
            av = atr_series.asof(pd.Timestamp(entry_day))
        except Exception:
            av = np.nan
        if av is None or pd.isna(av):
            av = float(atr_series.median())
        return contracts * mult * float(av) * point_value

    all_tr = []
    for _, t in r4_tr.iterrows():
        inst = str(t["inst"])
        all_tr.append({
            "inst": inst,
            "cluster": "roska4_swing",
            "entry": pd.Timestamp(t["day"]),
            "exit": pd.Timestamp(t["exit_day"]),
            "direction": t["direction"],
            "pnl1": float(t["pnl"]),
            "atr": atrs[inst],
            "mult": SWING_TF_PARAM["chandelier_atr_mult"],
            "pv": BASKET[inst].point_value,
            "_atr_entry": pd.Timestamp(t["day"]),
        })

    c = gi_specs.SPECS[nkd_inst]
    spy = pd.Series(label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3, hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ndf = gi_load(nkd_parquet)
    ndf.index = ndf.index.tz_convert(c.session_tz)
    ndf = clip(ndf, start, end)
    natr = daily_atr_series(ndf)
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=slippage)
    nkd = backtest_swing_tf(ndf, nlab, ncost, ema_period=10,
                            chandelier_atr_mult=2.5, max_hold_days=5, gap_fill=True)
    for t in nkd:
        ed = pd.Timestamp(t["day"]).tz_localize(None)
        xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
        all_tr.append({
            "inst": nkd_inst,
            "cluster": "global_nkd",
            "entry": ed,
            "exit": xd,
            "direction": t["direction"],
            "pnl1": float(t["pnl"]),
            "atr": natr,
            "mult": 2.5,
            "pv": c.point_value,
            "_atr_entry": ed,
        })

    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"] = t["pnl1"]

    guard0 = MultiClusterGuard(account=ACCOUNT)
    d1, _ = replay(all_tr, ACCOUNT, guard0, {}, CircuitBreaker)
    m1 = metrics(d1)
    base_margin = sum(BASKET[n].est_margin for n in BASKET) + c.est_margin
    auto_n, sz = size_combined(m1["maxdd"], base_margin, ACCOUNT)
    n_contracts = int(fixed_contracts) if fixed_contracts is not None else auto_n
    sz["binding"] = "FIXED (--n-contracts override)" if fixed_contracts is not None else sz["binding"]
    sz["proj_dd_pct"] = n_contracts * m1["maxdd"] / ACCOUNT

    contracts_by = {n: n_contracts for n in BASKET}
    contracts_by[nkd_inst] = 1
    for t in all_tr:
        n = 1 if t["cluster"] == "global_nkd" else n_contracts
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"] = t["pnl1"] * n

    guard = MultiClusterGuard(account=ACCOUNT)
    daily, st = replay(all_tr, ACCOUNT, guard, contracts_by, CircuitBreaker)
    st = dict(st)
    st["n_contracts"] = n_contracts
    st["sizer"] = sz
    st["one_micro_maxdd"] = m1["maxdd"]
    st["which"] = which
    return daily, st


def fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def fmt_float(v: float) -> str:
    if math.isinf(v):
        return "inf"
    return f"{v:.2f}"


def run_window(which: str) -> dict:
    argv, dfs, atrs, labels0, labels1, costs, sessions = load_window(which)
    tr0 = build_r4(dfs, labels0, costs)
    tr1 = build_r4(dfs, labels1, costs)
    d0, st0 = combined_deploy_daily(which, tr0, atrs, argv)
    d1, st1 = combined_deploy_daily(which, tr1, atrs, argv)
    return {
        "which": which,
        "labels": label_impact(labels0, labels1, sessions),
        "r4_lag0": summarize_trades("lag0", tr0, sessions),
        "r4_lag1": summarize_trades("lag1", tr1, sessions),
        "changed": changed_trade_days(tr0, tr1),
        "year_lag0": per_year(tr0),
        "year_lag1": per_year(tr1),
        "inst_lag0": per_instrument(tr0),
        "inst_lag1": per_instrument(tr1),
        "combined_lag0": metrics(d0),
        "combined_lag1": metrics(d1),
        "combined_st_lag0": st0,
        "combined_st_lag1": st1,
    }


def write_report(results: list[dict], out_path: Path) -> None:
    lines = [
        "# Swing Regime Label Causality Audit - 2026-08-21",
        "",
        "Scope: scratch-only measurement. Production code was not modified.",
        "",
        "Question: does the validated R4 swing baseline depend materially on same-day",
        "HMM regime labels that are only known after the 16:00 SPY close, while entries",
        "can occur from 14:00 to 15:55?",
        "",
        "Method:",
        "",
        "- `lag0` = existing `label_regimes` labels.",
        "- `lag1` = previous available label, applied only to R4 swing.",
        "- NKD remains on its existing `RegimeLabels(..., lag_days=1)` path in combined replay.",
        "- Costs use the harness window settings, usually 2 ticks/side.",
        "",
        "## R4 Swing 1-Micro Results",
        "",
        "| Window | Basis | Trades | Entry days | Net | PF | Sharpe | Calmar | MaxDD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        for key in ("r4_lag0", "r4_lag1"):
            x = r[key]
            lines.append(
                f"| {r['which']} | {x['name']} | {x['trades']} | {x['entry_days']} | "
                f"{fmt_money(x['net'])} | {fmt_float(x['pf'])} | {fmt_float(x['sharpe'])} | "
                f"{fmt_float(x['calmar'])} | {fmt_money(x['maxdd'])} |"
            )
    lines += [
        "",
        "## Combined Deploy Replay",
        "",
        "R4 labels are varied. NKD labels are left on the current causal lag-1 path.",
        "",
        "| Window | Basis | Net | PF | Sharpe | Calmar | MaxDD | R4 contracts | Swing taken/rejected | NKD taken/rejected |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        for basis, mk, sk in (("lag0", "combined_lag0", "combined_st_lag0"),
                             ("lag1", "combined_lag1", "combined_st_lag1")):
            m = r[mk]
            st = r[sk]
            taken = st["taken"]
            rej = st["rejected"]
            lines.append(
                f"| {r['which']} | {basis} | {fmt_money(m['pnl'])} | {fmt_float(m['pf'])} | "
                f"{fmt_float(m['sharpe'])} | {fmt_float(m['calmar'])} | {fmt_money(m['maxdd'])} | "
                f"{st['n_contracts']} | {taken['roska4_swing']}/{rej['roska4_swing']} | "
                f"{taken['global_nkd']}/{rej['global_nkd']} |"
            )
    lines += [
        "",
        "## Label And Trade-Day Movement",
        "",
        "| Window | Comparable label days | Label flips | Lag0-only trade days / PnL | Lag1-only trade days / PnL | Both-days lag0 vs lag1 PnL |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lab = r["labels"]
        ch = r["changed"]
        lines.append(
            f"| {r['which']} | {lab['comparable']} | {lab['flips']} | "
            f"{ch['lag0_only_days']} / {fmt_money(ch['lag0_only_pnl'])} | "
            f"{ch['lag1_only_days']} / {fmt_money(ch['lag1_only_pnl'])} | "
            f"{fmt_money(ch['both_lag0_pnl'])} vs {fmt_money(ch['both_lag1_pnl'])} |"
        )
    lines += [
        "",
        "## By Instrument Net",
        "",
    ]
    for r in results:
        lines.append(f"### {r['which']}")
        insts = sorted(set(r["inst_lag0"]) | set(r["inst_lag1"]))
        lines.append("")
        lines.append("| Instrument | Lag0 | Lag1 | Delta |")
        lines.append("|---|---:|---:|---:|")
        for inst in insts:
            a = r["inst_lag0"].get(inst, 0.0)
            b = r["inst_lag1"].get(inst, 0.0)
            lines.append(f"| {inst} | {fmt_money(a)} | {fmt_money(b)} | {fmt_money(b - a)} |")
        lines.append("")
    lines += [
        "## By Exit Year Net",
        "",
    ]
    for r in results:
        years = sorted(set(r["year_lag0"]) | set(r["year_lag1"]))
        lines.append(f"### {r['which']}")
        lines.append("")
        lines.append("| Year | Lag0 | Lag1 | Delta |")
        lines.append("|---|---:|---:|---:|")
        for y in years:
            a = r["year_lag0"].get(y, 0.0)
            b = r["year_lag1"].get(y, 0.0)
            lines.append(f"| {y} | {fmt_money(a)} | {fmt_money(b)} | {fmt_money(b - a)} |")
        lines.append("")
    lines += [
        "## Verdict",
        "",
    ]
    floor = next((r for r in results if r["which"] == "floor"), results[0])
    floor_delta = floor["r4_lag1"]["net"] - floor["r4_lag0"]["net"]
    if abs(floor_delta) > 0.1 * max(abs(floor["r4_lag0"]["net"]), 1.0):
        lines += [
            "The lag-1 repair is material for the swing baseline. The stack-wide",
            "lag-0 convention should not be treated as harmless until the validated",
            "tables are refreshed or caveated on a causal-label basis.",
        ]
    else:
        lines += [
            "The lag-1 repair is not material on the floor R4 swing baseline by net PnL.",
            "Still, the live timing convention should be documented because labels are",
            "not fully known before 16:00.",
        ]
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2324", "vault2025", "vault2026"])
    args = ap.parse_args()

    results = []
    for which in args.which:
        print(f"\n=== {which} ===")
        r = run_window(which)
        results.append(r)
        for key in ("r4_lag0", "r4_lag1"):
            x = r[key]
            print(
                f"R4 {x['name']:5s} trades={x['trades']:4d} days={x['entry_days']:4d} "
                f"net={fmt_money(x['net']):>10s} PF={fmt_float(x['pf'])} "
                f"Calmar={fmt_float(x['calmar'])} MaxDD={fmt_money(x['maxdd'])}"
            )
        print(f"labels flips={r['labels']['flips']} pairs={r['labels']['flips_by_pair']}")
        ch = r["changed"]
        print(
            "trade days lag0_only={lag0_only_days} ({lag0_only_pnl:+,.0f}) "
            "lag1_only={lag1_only_days} ({lag1_only_pnl:+,.0f}) both_pnl={both_lag0_pnl:+,.0f}->{both_lag1_pnl:+,.0f}"
            .format(**ch)
        )
        for basis, mk in (("combined lag0", "combined_lag0"), ("combined lag1", "combined_lag1")):
            m = r[mk]
            print(
                f"{basis:13s} net={fmt_money(m['pnl']):>10s} PF={fmt_float(m['pf'])} "
                f"Calmar={fmt_float(m['calmar'])} MaxDD={fmt_money(m['maxdd'])}"
            )

    out = Path("scratch/swing_label_causality_audit_20260821_report.md")
    write_report(results, out)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
