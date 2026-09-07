"""
Normal sleeve risk/account-halt policy probe - scratch/research only.

Loads the saved trade tables from normal_sleeve_halt_probe_20260821, rebuilds
only the risk metadata needed by MultiClusterGuard, and replays alternate account
breaker thresholds / release rules without touching production code.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ACCOUNT = 50_000.0
R4 = ("MES", "MNQ", "MYM", "M2K")


def _root():
    import sys
    p = str(Path.cwd())
    if p not in sys.path:
        sys.path.insert(0, p)


def load_trade_json(which: str) -> dict:
    path = Path(f"scratch/normal_sleeve_trades_{which}_20260821.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    for table in ("booked", "corrected"):
        for inst, trades in raw[table].items():
            for t in trades:
                for k in ("entry", "exit", "points", "pnl"):
                    if k in t:
                        t[k] = float(t[k])
    return raw


def _argv_value(argv, key, default=None):
    return argv[argv.index(key) + 1] if key in argv else default


def _clip(df: pd.DataFrame, argv: list[str]) -> pd.DataFrame:
    start = _argv_value(argv, "--start")
    end = _argv_value(argv, "--end")
    if start:
        ts = pd.Timestamp(start).tz_localize(df.index.tz) if df.index.tz else pd.Timestamp(start)
        df = df[df.index >= ts]
    if end:
        ts = pd.Timestamp(end).tz_localize(df.index.tz) if df.index.tz else pd.Timestamp(end)
        df = df[df.index <= ts]
    return df


def build_meta(raw: dict) -> dict:
    _root()
    from futures._validated_core import daily_atr_series, load_parquet
    from futures.basket import BASKET, data_filename
    from global_index import specs as gi_specs
    from global_index._core import load_parquet as gi_load

    argv = raw["argv"]
    data_dir = Path(_argv_value(argv, "--data-dir"))
    nkd_inst = raw["nkd_instrument"]
    meta = {}
    for inst in R4:
        c = BASKET[inst]
        df = _clip(load_parquet(str(data_dir / data_filename(c))), argv)
        meta[inst] = dict(
            cluster="roska4_swing",
            atr=daily_atr_series(df),
            mult=2.5,
            pv=float(c.point_value),
        )
    c = gi_specs.SPECS[nkd_inst]
    ndf = gi_load(_argv_value(argv, "--nkd-parquet"))
    ndf.index = ndf.index.tz_convert(c.session_tz)
    ndf = _clip(ndf, argv)
    meta[nkd_inst] = dict(
        cluster="global_nkd",
        atr=daily_atr_series(ndf),
        mult=2.5,
        pv=float(c.point_value),
    )
    return meta


def real_risk(atr_series, mult, point_value, entry_day, contracts):
    try:
        av = atr_series.asof(pd.Timestamp(entry_day))
    except Exception:
        av = np.nan
    if av is None or pd.isna(av):
        av = float(atr_series.median())
    return contracts * mult * float(av) * point_value


def build_book(trades_by_inst: dict, meta: dict, n_contracts=1) -> list[dict]:
    out = []
    for inst, trades in trades_by_inst.items():
        m = meta[inst]
        for t in trades:
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t.get("exit_day") or t["day"])
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            n = 1 if m["cluster"] == "global_nkd" else n_contracts
            out.append(dict(
                inst=inst,
                cluster=m["cluster"],
                entry=ed,
                exit=xd,
                direction=t["direction"],
                pnl1=float(t["pnl"]),
                pnl_sized=float(t["pnl"]) * n,
                risk_sized=real_risk(m["atr"], m["mult"], m["pv"], ed, n),
            ))
    return out


def make_guard(account: float, swing_cap: float):
    _root()
    from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", swing_cap, swing_cap if swing_cap != 0.05 else 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
        "global_nkd": ClusterBudget("global_nkd", 0.06, 0.06),
    }
    return MultiClusterGuard(clusters=clusters, account=account)


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(pnl=0.0, pf=0.0, sharpe=0.0, calmar=0.0, maxdd=0.0)
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    wins = daily[daily > 0].sum()
    losses = -daily[daily < 0].sum()
    return dict(
        pnl=float(daily.sum()),
        pf=float(wins / losses) if losses > 1e-9 else float("inf"),
        sharpe=float(daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 1e-9 else 0.0,
        calmar=float((daily.sum() / span) / dd) if dd > 1e-9 else float("inf"),
        maxdd=dd,
    )


def replay(book: list[dict], threshold: float | None, release: str, cooldown_days: int, swing_cap: float):
    _root()
    from global_index.net_exposure_multi import Position, entry_priority_key

    guard = make_guard(ACCOUNT, swing_cap)
    days = sorted({t["entry"] for t in book} | {t["exit"] for t in book})
    by_entry = {}
    for t in book:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []
    realized = {}
    equity = ACCOUNT
    peak = ACCOUNT
    taken = {c: 0 for c in guard.clusters}
    rejected = {c: 0 for c in guard.clusters}
    halted_entries = 0
    halted_days = 0
    lost_pnl = 0.0
    first_halt = None
    cooldown_left = 0
    peak_rel_dd = 0.0
    peak_rel_day = None
    peak_at_worst = ACCOUNT

    for day in days:
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                still.append((pos, t))
        open_pos = still

        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > peak_rel_dd:
            peak_rel_dd = float(dd)
            peak_rel_day = str(pd.Timestamp(day).date())
            peak_at_worst = float(peak)

        allow = True
        if threshold is not None:
            if cooldown_left > 0:
                allow = False
                cooldown_left -= 1
            elif dd >= threshold:
                allow = False
                if first_halt is None:
                    first_halt = dict(day=str(pd.Timestamp(day).date()), equity=equity, peak=peak, dd=dd)
                if release == "flat_reset" and not open_pos:
                    peak = equity
                    allow = True
                elif release == "cooldown_reset":
                    cooldown_left = max(cooldown_days - 1, 0)
                    peak = equity

        if not allow:
            halted_days += 1

        for t in sorted(by_entry.get(day, []), key=entry_priority_key):
            if not allow:
                halted_entries += 1
                lost_pnl += t["pnl_sized"]
                continue
            pos = Position(t["inst"], t["direction"], 1, t["risk_sized"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rejected[t["cluster"]] += 1
                continue
            taken[t["cluster"]] += 1
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
                peak = max(peak, equity)
            else:
                open_pos.append((pos, t))

    daily = pd.Series(realized).sort_index()
    m = metrics(daily)
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 1.0
    return dict(
        net=m["pnl"], pf=m["pf"], sharpe=m["sharpe"], calmar=m["calmar"],
        maxdd=m["maxdd"], maxdd_pct=m["maxdd"] / ACCOUNT, ret_yr=m["pnl"] / ACCOUNT / span,
        trade_count=len(book), taken=sum(taken.values()), rejected=sum(rejected.values()),
        halted_days=halted_days, blocked_trades=halted_entries, lost_trade_pnl=lost_pnl,
        peak_rel_dd=peak_rel_dd, peak_rel_day=peak_rel_day,
        safety_margin_15=0.15 - peak_rel_dd, first_halt=first_halt,
        yearly={int(y): float(g.sum()) for y, g in daily.groupby(daily.index.year)} if len(daily) else {},
    )


def daily_from_book(book: list[dict]) -> pd.Series:
    d = {}
    for t in book:
        d[t["exit"]] = d.get(t["exit"], 0.0) + t["pnl_sized"]
    return pd.Series(d).sort_index()


def bootstrap_cluster(daily: pd.Series, freq: str, n_iter: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    if daily.empty:
        return {}
    grouped = daily.groupby(pd.Grouper(freq=freq)).sum()
    grouped = grouped[grouped.index.notna()]
    vals = grouped.to_numpy(dtype=float)
    draws = rng.choice(vals, size=(n_iter, len(vals)), replace=True)
    nets = draws.sum(axis=1)
    wins = np.where(draws > 0, draws, 0).sum(axis=1)
    losses = -np.where(draws < 0, draws, 0).sum(axis=1)
    pf = np.divide(wins, losses, out=np.full_like(wins, np.inf, dtype=float), where=losses > 1e-9)
    maxdds = []
    for row in draws:
        eq = np.cumsum(row)
        maxdds.append(float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) else 0.0)
    return dict(
        clusters=int(len(vals)),
        net_ci=[float(np.percentile(nets, q)) for q in (2.5, 5, 50, 95, 97.5)],
        pf_ci=[float(np.percentile(pf[np.isfinite(pf)], q)) for q in (5, 50, 95)] if np.isfinite(pf).any() else [],
        maxdd_ci=[float(np.percentile(maxdds, q)) for q in (5, 50, 95)],
        p_net_positive=float((nets > 0).mean()),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--out", default="scratch/normal_sleeve_risk_policy_probe_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_sleeve_risk_policy_probe_20260821.json")
    ap.add_argument("--bootstrap-iters", type=int, default=20000)
    args = ap.parse_args()

    report = []
    results = {}

    def emit(s=""):
        print(s)
        report.append(s)

    emit("=" * 112)
    emit("NORMAL SLEEVE - RISK / ACCOUNT HALT POLICY PROBE (scratch only)")
    emit("=" * 112)
    emit("Uses saved corrected trade tables. No production code modified.")
    emit("")

    for which in args.which:
        raw = load_trade_json(which)
        meta = build_meta(raw)
        nkd = raw["nkd_instrument"]
        books = {
            "R4 only": build_book({k: raw["corrected"][k] for k in R4}, meta),
            "R4 + NKD corrected": build_book({**{k: raw["corrected"][k] for k in R4}, nkd: raw["corrected"][nkd]}, meta),
            "NKD only corrected": build_book({nkd: raw["corrected"][nkd]}, meta),
        }
        emit("#" * 112)
        emit(f"WINDOW: {which}")
        emit("#" * 112)
        results[which] = {}

        scenarios = []
        for variant in ("R4 only", "R4 + NKD corrected"):
            for th in (0.15, 0.175, 0.20, 0.25, None):
                scenarios.append((variant, th, "latch", 0, 0.05))
            for release, cd in (("flat_reset", 0), ("cooldown_reset", 20), ("cooldown_reset", 60)):
                scenarios.append((variant, 0.15, release, cd, 0.05))
        if which == "floor":
            scenarios.extend([
                ("R4 + NKD corrected", 0.15, "latch", 0, 0.075),
                ("R4 + NKD corrected", None, "latch", 0, 0.075),
                ("R4 only", 0.15, "latch", 0, 0.075),
                ("R4 only", None, "latch", 0, 0.075),
            ])

        rows = []
        for variant, th, release, cd, cap in scenarios:
            label = "off" if th is None else f"{th:.1%}"
            r = replay(books[variant], th, release, cd, cap)
            r.update(variant=variant, threshold=label, release=release, cooldown_days=cd, swing_cap=cap)
            rows.append(r)

        emit("  {:<20} {:>7} {:<14} {:>5} {:>10} {:>5} {:>7} {:>7} {:>8} {:>8} {:>7} {:>6} {:>7} {:>10}".format(
            "variant", "breaker", "release", "cap", "net$", "PF", "Sharpe", "Calmar",
            "MaxDD%", "ret/yr", "trades", "haltD", "block", "lost pnl"))
        for r in rows:
            emit("  {variant:<20} {threshold:>7} {release:<14} {swing_cap:>5.1%} {net:>10,.0f} {pf:>5.2f} {sharpe:>7.2f} {calmar:>7.2f} {maxdd_pct:>8.1%} {ret_yr:>8.1%} {taken:>7} {halted_days:>6} {blocked_trades:>7} {lost_trade_pnl:>10,.0f}".format(**r))
        emit("")
        years = sorted({y for r in rows for y in r["yearly"]})
        emit("  YEARLY NET$ (key rows)")
        key_rows = [r for r in rows if r["release"] == "latch" and r["swing_cap"] in (0.05, 0.075)]
        emit("  {:<20} {:>7} {:>5} {}".format("variant", "breaker", "cap", " ".join(f"{y:>9}" for y in years)))
        for r in key_rows:
            emit("  {:<20} {:>7} {:>5.1%} {}".format(
                r["variant"], r["threshold"], r["swing_cap"],
                " ".join("{:>9,.0f}".format(r["yearly"].get(y, 0.0)) for y in years)))
        emit("")

        if which == "floor":
            nkd_daily = daily_from_book(books["NKD only corrected"])
            boot = {
                "day": bootstrap_cluster(nkd_daily, "D", args.bootstrap_iters, 2101),
                "week": bootstrap_cluster(nkd_daily, "W", args.bootstrap_iters, 2102),
                "month": bootstrap_cluster(nkd_daily, "ME", args.bootstrap_iters, 2103),
            }
            y = {int(yy): float(g.sum()) for yy, g in nkd_daily.groupby(nkd_daily.index.year)}
            conc = dict(y2022_2023=y.get(2022, 0.0) + y.get(2023, 0.0),
                        other_years=sum(v for k, v in y.items() if k not in (2022, 2023)))
            emit("  NKD DIRECT ALPHA BOOTSTRAP (corrected, floor, clustered PnL resampling)")
            for name, b in boot.items():
                emit("    {:<5} clusters {:>4} | net 2.5/50/97.5 ${:>8,.0f} / ${:>8,.0f} / ${:>8,.0f} | p(net>0) {:>5.1%} | PF 5/50/95 {} | MaxDD 5/50/95 ${:,.0f}/${:,.0f}/${:,.0f}".format(
                    name, b["clusters"], b["net_ci"][0], b["net_ci"][2], b["net_ci"][4],
                    b["p_net_positive"],
                    "/".join(f"{x:.2f}" for x in b["pf_ci"]),
                    b["maxdd_ci"][0], b["maxdd_ci"][1], b["maxdd_ci"][2]))
            emit("    concentration: 2022+2023 ${:,.0f}; all other floor years ${:,.0f}".format(
                conc["y2022_2023"], conc["other_years"]))
            emit("")
            results[which]["nkd_bootstrap"] = boot
            results[which]["nkd_concentration"] = conc

        results[which]["rows"] = rows

    Path(args.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(args.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {args.out} and {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
