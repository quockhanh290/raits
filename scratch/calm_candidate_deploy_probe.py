from __future__ import annotations

import argparse
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from global_index.deploy_sim import metrics, size_combined
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.directional_market_filter_probe import allowed_short_days, feature_frame
from scratch.harness import ARM_LIVE, Cfg, patched_engine


def _as_ts(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    try:
        return pd.Timestamp(x)
    except Exception:
        return None


def _bar_at(df: pd.DataFrame, ts) -> pd.Series | None:
    ts = _as_ts(ts)
    if ts is None:
        return None
    try:
        return df.loc[ts]
    except KeyError:
        pass
    if ts.tzinfo is not None:
        naive = ts.tz_localize(None)
        idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    else:
        naive = ts
        idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    locs = np.where(idx == naive)[0]
    if len(locs) == 0:
        return None
    return df.iloc[int(locs[0])]


def _bar_at_5m(df: pd.DataFrame, ts) -> pd.Series | None:
    ts = _as_ts(ts)
    if ts is None:
        return None
    day = df[df.index.normalize() == ts.normalize()]
    if day.empty and ts.tzinfo is not None:
        naive_day = ts.tz_localize(None).normalize()
        idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
        day = df[idx.normalize() == naive_day]
    if day.empty:
        return None
    bars = day.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return _bar_at(bars, ts)


def _price_inside_bar(price, bar: pd.Series | None) -> bool:
    if bar is None:
        return False
    try:
        px = float(price)
        lo = float(bar["low"])
        hi = float(bar["high"])
    except Exception:
        return False
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def audit_trade_fills(
    trade_map: dict[str, list[dict]],
    dfs: dict[str, pd.DataFrame],
    *,
    source: str,
    check_entry_price: bool = True,
) -> dict:
    audit = Counter()
    samples: dict[str, list[dict]] = {}

    def sample(key: str, inst: str, t: dict, bar: pd.Series | None = None) -> None:
        if len(samples.setdefault(key, [])) >= 5:
            return
        item = {
            "inst": inst,
            "day": str(t.get("day")),
            "entry_time": str(t.get("entry_time")),
            "exit_time": str(t.get("exit_time")),
            "entry": t.get("entry"),
            "exit": t.get("exit"),
            "reason": t.get("exit_reason") or t.get("reason"),
        }
        if bar is not None:
            item.update({
                "bar_open": float(bar["open"]),
                "bar_high": float(bar["high"]),
                "bar_low": float(bar["low"]),
                "bar_close": float(bar["close"]),
            })
        samples[key].append(item)

    audit["trades"] = 0
    for inst, trades in trade_map.items():
        df = dfs.get(inst)
        for t in trades:
            audit["trades"] += 1
            entry_ts = _as_ts(t.get("entry_time"))
            exit_ts = _as_ts(t.get("exit_time"))
            if entry_ts is None:
                audit["missing_entry_time"] += 1
            if exit_ts is None:
                audit["missing_exit_time"] += 1
            if entry_ts is not None and exit_ts is not None and exit_ts <= entry_ts:
                audit["same_or_before_bar_exit"] += 1
            exit_bar = _bar_at(df, exit_ts) if df is not None else None
            if exit_bar is None:
                audit["missing_exit_bar"] += 1
                sample("missing_exit_bar", inst, t)
            elif not _price_inside_bar(t.get("exit"), exit_bar):
                audit["outside_exit_bar"] += 1
                sample("outside_exit_bar", inst, t, exit_bar)
            if check_entry_price:
                entry_bar = _bar_at(df, entry_ts) if df is not None else None
                if entry_bar is not None and not _price_inside_bar(t.get("entry"), entry_bar) and source == "normal":
                    entry_bar_5m = _bar_at_5m(df, entry_ts)
                    if _price_inside_bar(t.get("entry"), entry_bar_5m):
                        entry_bar = entry_bar_5m
                if entry_bar is None:
                    audit["missing_entry_bar"] += 1
                elif not _price_inside_bar(t.get("entry"), entry_bar):
                    audit["outside_entry_bar"] += 1

            if source == "stress":
                # The full 10:15-10:19 signal bar is only known at 10:20.
                known = pd.Timestamp(t.get("day")).normalize() + pd.Timedelta(hours=10, minutes=20)
                if entry_ts is None:
                    audit["signal_after_entry"] += 1
                else:
                    cmp_entry = entry_ts.tz_localize(None) if entry_ts.tzinfo is not None else entry_ts
                    if cmp_entry < known:
                        audit["signal_after_entry"] += 1
            elif source == "calm":
                # Completed overnight return is known at RTH open; entry must not precede 09:30.
                known = pd.Timestamp(t.get("day")).normalize() + pd.Timedelta(hours=9, minutes=30)
                if entry_ts is None:
                    audit["signal_after_entry"] += 1
                else:
                    cmp_entry = entry_ts.tz_localize(None) if entry_ts.tzinfo is not None else entry_ts
                    if cmp_entry < known:
                        audit["signal_after_entry"] += 1
    out = dict(audit)
    if samples:
        out["samples"] = samples
    return out


def _audit_ok(a: dict) -> bool:
    bad = (
        "outside_exit_bar",
        "missing_exit_time",
        "missing_exit_bar",
        "same_or_before_bar_exit",
        "signal_after_entry",
    )
    return all(int(a.get(k, 0)) == 0 for k in bad)


def reject_bucket(why: str) -> str:
    why = str(why)
    if " gross " in why:
        return "gross_cap"
    if " net " in why:
        return "net_cap"
    return why


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def first_at_or_after(g: pd.DataFrame, hhmm: str, col: str = "open") -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0][col])


def calm_trades(
    dfs: dict[str, pd.DataFrame],
    labels: dict[pd.Timestamp, str],
    costs: dict,
    *,
    instruments: set[str],
    min_overnight: float,
    max_overnight: float,
    exit_time: str,
    entry_delay_minutes: int,
    entry_extra_slippage_ticks: float,
) -> tuple[dict[str, list[dict]], int]:
    out = {inst: [] for inst in dfs}
    outside_exit_bar = 0
    for inst, df in dfs.items():
        if inst not in instruments:
            continue
        work = df.copy()
        work["tday"] = trading_day_index(work.index)
        pv = BASKET[inst].point_value
        for day, g in work.groupby("tday"):
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            rth = g.between_time("09:30", "15:59")
            pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
            if len(rth) < 160 or len(pre) < 30:
                continue
            entry_time = (pd.Timestamp("09:30") + pd.Timedelta(minutes=entry_delay_minutes)).strftime("%H:%M")
            entry = first_at_or_after(rth, entry_time, "open")
            exit_bar = first_at_or_after(rth, exit_time, "open")
            if not entry or not exit_bar:
                continue
            overnight_ret = float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0)
            if not (min_overnight < overnight_ret <= max_overnight):
                continue
            entry_ts, entry_px = entry
            exit_ts, exit_px = exit_bar
            if pd.Timestamp(exit_ts) < pd.Timestamp(entry_ts):
                outside_exit_bar += 1
                continue
            entry_px = float(entry_px) + entry_extra_slippage_ticks * BASKET[inst].tick
            exit_row = rth.loc[exit_ts]
            row_outside_exit = 0 if _price_inside_bar(exit_px, exit_row) else 1
            outside_exit_bar += row_outside_exit
            pnl = (exit_px - entry_px) * pv - costs[inst].round_turn_cost()
            out[inst].append({
                "day": day.date(),
                "exit_day": day.date(),
                "regime": "Calm",
                "direction": "LONG",
                "entry": round(entry_px, 2),
                "exit": round(exit_px, 2),
                "points": round(exit_px - entry_px, 2),
                "pnl": round(pnl, 2),
                "reason": f"CALM_NEG_OVERNIGHT_FADE_X{exit_time.replace(':', '')}",
                "entry_time": entry_ts,
                "exit_time": exit_ts,
                "exit_reason": f"{exit_time}_OPEN",
                "overnight_ret": overnight_ret,
                "outside_exit_bar": row_outside_exit,
            })
    return out, outside_exit_bar


def real_risk(atr_series, mult: float, point_value: float, entry_day, contracts: int) -> float:
    try:
        av = atr_series.asof(pd.Timestamp(entry_day))
    except Exception:
        av = np.nan
    if av is None or pd.isna(av):
        av = float(atr_series.median())
    return contracts * mult * float(av) * point_value


def daily_metrics_from_trades(
    all_tr: list[dict],
    *,
    account: float,
    n_contracts: int | None,
    base_margin: float,
    clusters: dict,
):
    for t in all_tr:
        t["risk_sized"] = real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"] = t["pnl1"]
    guard0 = MultiClusterGuard(clusters=dict(clusters), account=account)
    d1, _ = replay_details(all_tr, account, guard0, {})
    m1 = metrics(d1)
    auto_n, sz = size_combined(m1["maxdd"], base_margin, account)
    if n_contracts is not None:
        n = n_contracts
        sz["binding"] = "FIXED (--n-contracts override)"
        sz["proj_dd_pct"] = n * m1["maxdd"] / account if account else 0.0
    else:
        n = auto_n

    contracts_by = {inst: n for inst in BASKET}
    contracts_by["MNKD"] = 1
    for t in all_tr:
        mult = t["mult"]
        tn = 1 if t.get("cluster") == "global_nkd" else n
        t["risk_sized"] = real_risk(t["atr"], mult, t["pv"], t["_atr_entry"], tn)
        t["pnl_sized"] = t["pnl1"] * tn
    guard = MultiClusterGuard(clusters=dict(clusters), account=account)
    daily, st = replay_details(all_tr, account, guard, contracts_by)
    return daily, metrics(daily), st, n, sz, m1


def replay_details(all_trades: list[dict], account: float, guard: MultiClusterGuard, contracts_by_inst: dict):
    days = sorted({t["entry"] for t in all_trades} | {t["exit"] for t in all_trades})
    by_entry = {}
    for t in all_trades:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []
    realized = {}
    equity = account
    taken = {c: 0 for c in guard.clusters}
    rejected = {c: 0 for c in guard.clusters}
    taken_by_source = {}
    rejected_by_source = {}
    rejected_detail = []
    calm_overlap = 0
    calm_rejected_existing = 0
    calm_rejected_daily_cap = 0

    for day in days:
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                still.append((pos, t))
        open_pos = still

        def replay_priority(t: dict) -> tuple:
            if t.get("source") == "calm":
                return (0, float(t.get("overnight_ret", 0.0)), str(t.get("inst", "")))
            return (0, entry_priority_key(t), str(t.get("inst", "")))

        calm_taken_today = 0
        for t in sorted(by_entry.get(day, []), key=replay_priority):
            n = contracts_by_inst.get(t["inst"], 1)
            pos = Position(t["inst"], t["direction"], n, t["risk_sized"], t["cluster"])
            same_inst_open = [p for p, _ in open_pos if p.instrument == t["inst"]]
            if t.get("source") == "calm" and same_inst_open:
                calm_overlap += 1
            max_calm_today = int(t.get("calm_max_per_day", 0) or 0)
            if t.get("source") == "calm" and max_calm_today > 0 and calm_taken_today >= max_calm_today:
                rejected[t["cluster"]] = rejected.get(t["cluster"], 0) + 1
                rejected_by_source["calm"] = rejected_by_source.get("calm", 0) + 1
                rejected_detail.append({
                    "day": day,
                    "source": "calm",
                    "cluster": t["cluster"],
                    "inst": t["inst"],
                    "direction": t["direction"],
                    "reason": "calm_daily_cap",
                    "same_inst_open": len(same_inst_open),
                    "open_sources": ",".join(sorted({ot.get("source", "unknown") for _, ot in open_pos})),
                })
                calm_rejected_daily_cap += 1
                continue
            ok, why = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rejected[t["cluster"]] = rejected.get(t["cluster"], 0) + 1
                rejected_by_source[t.get("source", "unknown")] = rejected_by_source.get(t.get("source", "unknown"), 0) + 1
                rejected_detail.append({
                    "day": day,
                    "source": t.get("source", "unknown"),
                    "cluster": t["cluster"],
                    "inst": t["inst"],
                    "direction": t["direction"],
                    "reason": why,
                    "same_inst_open": len(same_inst_open),
                    "open_sources": ",".join(sorted({ot.get("source", "unknown") for _, ot in open_pos})),
                })
                if t.get("source") == "calm" and same_inst_open:
                    calm_rejected_existing += 1
                continue
            taken[t["cluster"]] = taken.get(t["cluster"], 0) + 1
            taken_by_source[t.get("source", "unknown")] = taken_by_source.get(t.get("source", "unknown"), 0) + 1
            if t.get("source") == "calm":
                calm_taken_today += 1
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                open_pos.append((pos, t))

    return pd.Series(realized).sort_index(), {
        "taken": taken,
        "rejected": rejected,
        "halted": 0,
        "taken_by_source": taken_by_source,
        "rejected_by_source": rejected_by_source,
        "rejected_by_source_reason": dict(Counter((d["source"], reject_bucket(d["reason"])) for d in rejected_detail)),
        "rejected_detail": rejected_detail,
        "calm_overlap": calm_overlap,
        "calm_rejected_existing": calm_rejected_existing,
        "calm_rejected_daily_cap": calm_rejected_daily_cap,
    }


def summarize(name: str, daily: pd.Series, m: dict, st: dict, n: int, account: float) -> dict:
    years = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 1.0
    row = {
        "name": name,
        "net": float(m["pnl"]),
        "pf": float(m["pf"]),
        "calmar": float(m["calmar"]),
        "sharpe": float(m["sharpe"]),
        "maxdd": float(m["maxdd"]),
        "maxdd_pct": float(m["maxdd"] / account * 100.0) if account else 0.0,
        "return_per_year_pct": float(m["pnl"] / account / years * 100.0) if account else 0.0,
        "contracts": n,
        "halts": int(st.get("halted", 0)),
    }
    for cl, x in st.get("taken", {}).items():
        row[f"{cl}_taken"] = int(x)
    for cl, x in st.get("rejected", {}).items():
        row[f"{cl}_rejected"] = int(x)
    row["calm_taken"] = int(st.get("taken_by_source", {}).get("calm", 0))
    row["calm_rejected"] = int(st.get("rejected_by_source", {}).get("calm", 0))
    row["stress_taken"] = int(st.get("taken_by_source", {}).get("stress", 0))
    row["stress_rejected"] = int(st.get("rejected_by_source", {}).get("stress", 0))
    row["calm_overlap"] = int(st.get("calm_overlap", 0))
    row["calm_rejected_existing"] = int(st.get("calm_rejected_existing", 0))
    row["calm_rejected_daily_cap"] = int(st.get("calm_rejected_daily_cap", 0))
    row["reject_reasons"] = st.get("rejected_by_source_reason", {})
    return row


def print_block(title: str, rows: list[dict], yearly: dict[str, pd.Series]) -> None:
    print(f"\n=== {title} ===")
    for r in rows:
        print(
            f"{r['name']:<20} net=${r['net']:>9,.0f} pf={r['pf']:>5.2f} "
            f"sharpe={r['sharpe']:>5.2f} calmar={r['calmar']:>5.2f} "
            f"maxdd=${r['maxdd']:>8,.0f}({r['maxdd_pct']:>5.1f}%) "
            f"ret/yr={r['return_per_year_pct']:>6.1f}% n={r['contracts']} "
            f"stress_t/r={r['stress_taken']}/{r['stress_rejected']} "
            f"calm_t/r={r['calm_taken']}/{r['calm_rejected']} overlap={r['calm_overlap']} "
            f"rej_existing={r['calm_rejected_existing']} rej_daily={r['calm_rejected_daily_cap']}"
        )
        if r.get("reject_reasons"):
            pretty = ", ".join(
                f"{src}:{reason}={n}"
                for (src, reason), n in sorted(r["reject_reasons"].items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))
            )
            print(f"  reject_reasons: {pretty}")
    print("-- yearly net --")
    years = sorted({int(y) for s in yearly.values() for y in s.index.year})
    for y in years:
        parts = []
        for name, s in yearly.items():
            parts.append(f"{name}=${s[s.index.year == y].sum():,.0f}")
        print(f"  {y}  " + " | ".join(parts))


def run_window(args, which: str, argv: list[str]) -> tuple[list[dict], dict[str, pd.Series], dict]:
    import futures._validated_core as VC
    import raits.strategies.trend_follow as tf
    from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
    from futures.stress_liquidation_1020 import StressLiquidation1020Engine
    from global_index._core import FuturesCost as GIFC
    from global_index._core import load_parquet as gi_load
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels

    def opt(flag: str, default=None):
        if flag not in argv:
            return default
        i = argv.index(flag)
        return argv[i + 1]

    t0 = time.perf_counter()

    def checkpoint(label: str) -> None:
        print(f"[{which}] {label} {time.perf_counter() - t0:.1f}s", flush=True)

    data_dir = opt("--data-dir")
    nkd_parquet = opt("--nkd-parquet")
    regime_csv = opt("--regime-csv", args.regime_csv)
    start = opt("--start")
    end = opt("--end")
    hmm_fit_end = opt("--hmm-fit-end", args.hmm_fit_end_oos)
    n_contracts = int(opt("--n-contracts", args.n_contracts)) if opt("--n-contracts", None) is not None else args.n_contracts
    slippage_ticks = float(opt("--slippage-ticks", args.slippage_ticks))

    def clip(df: pd.DataFrame) -> pd.DataFrame:
        if start:
            df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
        if end:
            df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
        return df

    dfs = {name: clip(load_parquet(str(Path(data_dir) / data_filename(contract)))) for name, contract in BASKET.items()}
    atr = {name: daily_atr_series(df) for name, df in dfs.items()}
    pv = {name: contract.point_value for name, contract in BASKET.items()}
    labels = label_regimes(benchmark_daily(regime_csv), args.hmm_train_end, 3, hmm_fit_end)
    checkpoint("loaded basket/labels")
    costs = costs_for_basket(slippage_ticks=slippage_ticks)
    nkd_spec = gi_specs.SPECS["MNKD"]
    ndf = gi_load(nkd_parquet)
    ndf.index = ndf.index.tz_convert(nkd_spec.session_tz)
    ndf = clip(ndf)
    natr = daily_atr_series(ndf)
    spy = pd.Series(label_regimes(benchmark_daily(regime_csv), args.hmm_train_end, 3, hmm_fit_end))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nlab = RegimeLabels(spy.sort_index(), lag_days=1)
    ncost = GIFC(
        point_value=nkd_spec.point_value,
        tick=nkd_spec.tick,
        commission_rt=nkd_spec.commission_rt,
        slippage_ticks_per_side=slippage_ticks,
    )

    cfg = Cfg(fix_fill=True, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False, ema=50, stop_basis=2.0)
    stat = {"n": 0, "tot": 0.0}
    orig_bt, bt_fn = patched_engine(cfg, stat)
    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    short_days = allowed_short_days(feature_frame(regime_csv), "below_sma50")

    def filtered_generate(self, *a, **kw):
        sig = old_generate(self, *a, **kw)
        if not sig or sig.get("direction") != "SHORT":
            return sig
        resume_bar = a[1]
        day = pd.Timestamp(resume_bar.name).tz_localize(None).normalize()
        return sig if day in short_days else None

    try:
        VC.backtest_swing_tf = bt_fn
        tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
        tf.TrendFollowStrategy.generate_signal = filtered_generate
        swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
        nkd = VC.backtest_swing_tf(
            ndf,
            nlab,
            ncost,
            ema_period=10,
            chandelier_atr_mult=2.5,
            max_hold_days=5,
            gap_fill=True,
        )
    finally:
        VC.backtest_swing_tf = orig_bt
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
        tf.TrendFollowStrategy.generate_signal = old_generate
    checkpoint("normal/nkd complete")

    stress = StressLiquidation1020Engine(
        variant=args.stress_variant,
        instruments=set(args.stress_instruments),
    ).backtest_basket(dfs, labels, costs)
    checkpoint("stress complete")
    calm, calm_outside = calm_trades(
        dfs,
        labels,
        costs,
        instruments=set(args.calm_instruments),
        min_overnight=args.min_overnight,
        max_overnight=args.max_overnight,
        exit_time=args.calm_exit_time,
        entry_delay_minutes=args.calm_entry_delay_minutes,
        entry_extra_slippage_ticks=args.calm_entry_extra_slippage_ticks,
    )
    checkpoint("calm complete")
    fill_audits = {
        "normal": audit_trade_fills(swing, dfs, source="normal", check_entry_price=False),
        "stress": audit_trade_fills(stress, dfs, source="stress"),
        "calm": audit_trade_fills(calm, dfs, source="calm"),
    }
    if not args.exclude_nkd:
        fill_audits["nkd"] = audit_trade_fills({"MNKD": nkd}, {"MNKD": ndf}, source="normal", check_entry_price=False)
    checkpoint("strict fill/lookahead audit complete")

    def assemble(include_stress: bool, include_calm: bool, calm_cluster: str = "roska4_calm") -> list[dict]:
        all_tr = []
        for inst, trades in swing.items():
            for t in trades:
                all_tr.append({
                    "inst": inst,
                    "cluster": "roska4_swing",
                    "entry": pd.Timestamp(t["day"]),
                    "exit": pd.Timestamp(t["exit_day"]),
                    "direction": t["direction"],
                    "pnl1": float(t["pnl"]),
                    "atr": atr[inst],
                    "mult": 2.5,
                    "pv": pv[inst],
                    "_atr_entry": pd.Timestamp(t["day"]),
                    "source": "normal",
                    "entry_time": t.get("entry_time"),
                    "exit_time": t.get("exit_time"),
                    "entry_px": t.get("entry"),
                    "exit_px": t.get("exit"),
                    "exit_reason": t.get("exit_reason") or t.get("reason"),
                })
        if include_stress:
            for inst, trades in stress.items():
                for t in trades:
                    all_tr.append({
                        "inst": inst,
                        "cluster": "roska4_stress",
                        "entry": pd.Timestamp(t["day"]),
                        "exit": pd.Timestamp(t["exit_day"]),
                        "direction": t["direction"],
                        "pnl1": float(t["pnl"]),
                        "atr": atr[inst],
                        "mult": 2.5,
                        "pv": pv[inst],
                        "_atr_entry": pd.Timestamp(t["day"]),
                        "source": "stress",
                        "entry_time": t.get("entry_time"),
                        "exit_time": t.get("exit_time"),
                        "entry_px": t.get("entry"),
                        "exit_px": t.get("exit"),
                        "exit_reason": t.get("exit_reason") or t.get("reason"),
                    })
        if include_calm:
            for inst, trades in calm.items():
                for t in trades:
                    all_tr.append({
                        "inst": inst,
                        "cluster": calm_cluster,
                        "entry": pd.Timestamp(t["day"]),
                        "exit": pd.Timestamp(t["exit_day"]),
                        "direction": t["direction"],
                        "pnl1": float(t["pnl"]),
                        "atr": atr[inst],
                        "mult": args.calm_risk_atr_mult,
                        "pv": pv[inst],
                        "_atr_entry": pd.Timestamp(t["day"]),
                        "source": "calm",
                        "entry_time": t.get("entry_time"),
                        "exit_time": t.get("exit_time"),
                        "entry_px": t.get("entry"),
                        "exit_px": t.get("exit"),
                        "exit_reason": t.get("exit_reason") or t.get("reason"),
                        "overnight_ret": t.get("overnight_ret"),
                        "calm_max_per_day": args.calm_max_per_day,
                    })
        if not args.exclude_nkd:
            for t in nkd:
                ed = pd.Timestamp(t["day"]).tz_localize(None)
                xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
                all_tr.append({
                    "inst": "MNKD",
                    "cluster": "global_nkd",
                    "entry": ed,
                    "exit": xd,
                    "direction": t["direction"],
                    "pnl1": float(t["pnl"]),
                    "atr": natr,
                    "mult": 2.5,
                    "pv": nkd_spec.point_value,
                    "_atr_entry": ed,
                    "source": "nkd",
                    "entry_time": t.get("entry_time"),
                    "exit_time": t.get("exit_time"),
                    "entry_px": t.get("entry"),
                    "exit_px": t.get("exit"),
                    "exit_reason": t.get("exit_reason") or t.get("reason"),
                })
        return all_tr

    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", max_gross_pct=args.swing_cap, max_net_pct=args.swing_net_cap),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=args.stress_cap, max_net_pct=None),
        "roska4_calm": ClusterBudget("roska4_calm", max_gross_pct=args.calm_cap, max_net_pct=args.calm_net_cap),
        "global_nkd": ClusterBudget("global_nkd", max_gross_pct=0.06, max_net_pct=0.06),
    }
    base_margin = sum(BASKET[n].est_margin for n in BASKET) + (0 if args.exclude_nkd else nkd_spec.est_margin)
    configs = [
        ("normal", False, False, "roska4_calm", clusters),
        ("normal_stress", True, False, "roska4_calm", clusters),
        ("calm_swing_cap", True, True, "roska4_swing", clusters),
        ("calm_own_cap", True, True, "roska4_calm", clusters),
        ("calm_relaxed_cap", True, True, "roska4_calm", {
            **clusters,
            "roska4_calm": ClusterBudget("roska4_calm", max_gross_pct=99.0, max_net_pct=99.0),
        }),
    ]
    rows = []
    yearly = {}
    for name, inc_stress, inc_calm, calm_cluster, cfg_clusters in configs:
        all_tr = assemble(inc_stress, inc_calm, calm_cluster=calm_cluster)
        daily, m, st, n, _, _ = daily_metrics_from_trades(
            all_tr,
            account=args.account,
            n_contracts=n_contracts,
            base_margin=base_margin,
            clusters=cfg_clusters,
        )
        rows.append(summarize(name, daily, m, st, n, args.account))
        yearly[name] = daily
    checkpoint("portfolio replay complete")

    audit = {
        "which": which,
        "calm_outside_exit_bar": calm_outside,
        "calm_trades": sum(len(x) for x in calm.values()),
        "calm_by_inst": {inst: len(x) for inst, x in calm.items()},
        "stress_trades": sum(len(x) for x in stress.values()),
        "stress_by_inst": {inst: len(x) for inst, x in stress.items()},
        "normal_fix_n": stat["n"],
        "normal_fix_dollars": stat["tot"],
        "fill_audits": fill_audits,
        "fill_audits_ok": {k: _audit_ok(v) for k, v in fill_audits.items()},
    }
    return rows, yearly, audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--n-contracts", type=int, default=1)
    ap.add_argument("--stress-variant", choices=["breadth3", "wide_range3"], default="breadth3")
    ap.add_argument("--stress-instruments", nargs="+", default=["MNQ", "MES"])
    ap.add_argument("--calm-instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--min-overnight", type=float, default=-0.008)
    ap.add_argument("--max-overnight", type=float, default=-0.001)
    ap.add_argument("--calm-exit-time", default="12:00")
    ap.add_argument("--calm-entry-delay-minutes", type=int, default=0)
    ap.add_argument("--calm-entry-extra-slippage-ticks", type=float, default=0.0)
    ap.add_argument("--calm-max-per-day", type=int, default=0)
    ap.add_argument("--calm-risk-atr-mult", type=float, default=1.0)
    ap.add_argument("--exclude-nkd", action="store_true")
    ap.add_argument("--swing-cap", type=float, default=0.05)
    ap.add_argument("--swing-net-cap", type=float, default=0.044)
    ap.add_argument("--stress-cap", type=float, default=0.025)
    ap.add_argument("--calm-cap", type=float, default=0.05)
    ap.add_argument("--calm-net-cap", type=float, default=0.05)
    args = ap.parse_args()

    from scratch import harness as H

    print("Calm deploy scratch config:")
    print(f"  calm: LONG RTH open -> {args.calm_exit_time} open, overnight_ret in ({args.min_overnight:.3%}, {args.max_overnight:.3%}], inst={','.join(args.calm_instruments)}")
    print(f"  calm execution: entry_delay={args.calm_entry_delay_minutes}m extra_entry_slip={args.calm_entry_extra_slippage_ticks:g} ticks max_per_day={args.calm_max_per_day or 'none'}")
    print(f"  calm cluster: gross={args.calm_cap:.1%}, net={args.calm_net_cap:.1%}, risk_proxy={args.calm_risk_atr_mult:g}x daily ATR")
    print(f"  stress: liquidation1020 {args.stress_variant}, inst={','.join(args.stress_instruments)}, cap={args.stress_cap:.1%}")
    print("  normal: Normal-only EMA50, 2x daily ATR stop, live/corrected fill, SHORT only below SPY SMA50 D-1")
    if args.exclude_nkd:
        print("  nkd: excluded from scratch combined run")

    all_rows = []
    for which in args.which:
        try:
            rows, yearly, audit = run_window(args, which, list(H.ARGV[which]))
        except BaseException as exc:
            print(f"ERROR {which}: {type(exc).__name__}: {exc}", flush=True)
            raise
        print_block(which, rows, yearly)
        print(f"-- fill audit -- calm_outside_exit_bar={audit['calm_outside_exit_bar']} calm_trades={audit['calm_trades']} by_inst={audit['calm_by_inst']}")
        print(f"-- stress audit -- stress_trades={audit['stress_trades']} by_inst={audit['stress_by_inst']}")
        for sleeve, fa in audit["fill_audits"].items():
            status = "OK" if audit["fill_audits_ok"][sleeve] else "FAIL"
            print(f"-- strict fill/lookahead audit {sleeve}: {status} {fa}")
        print(f"-- normal fill correction -- n={audit['normal_fix_n']} dollars={audit['normal_fix_dollars']:.0f}")
        for row in rows:
            row["which"] = which
            all_rows.append(row)

    print("\n=== deltas ===")
    for which in args.which:
        sub = {r["name"]: r for r in all_rows if r["which"] == which}
        if "normal_stress" in sub and "calm_own_cap" in sub:
            a = sub["normal_stress"]
            b = sub["calm_own_cap"]
            print(
                f"{which:<10} calm_delta net=${b['net'] - a['net']:>8,.0f} "
                f"calmar={b['calmar'] - a['calmar']:>+5.2f} "
                f"maxdd={b['maxdd_pct'] - a['maxdd_pct']:>+5.1f}%"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
