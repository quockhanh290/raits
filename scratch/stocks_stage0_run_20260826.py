"""scratch/stocks_stage0_run_20260826.py — Stage STOCKS-0 backtest runner. READ-ONLY.

Produces, under scratch/ only:
    _stocks_stage0_ledger_<config>.csv      one row per candidate, taken or rejected
    _stocks_stage0_results.json             every measured number the report quotes

Run:
    python scratch\\stocks_stage0_run_20260826.py --configs B
    python scratch\\stocks_stage0_run_20260826.py --configs A,B,C,D --all-symbols
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from global_index import track1_normal_r4 as NR                      # noqa: E402
from global_index import track1_normal_filters as NF                 # noqa: E402
from scratch import stocks_stage0_data_20260826 as D                 # noqa: E402
from scratch import stocks_stage0_engine_20260826 as E               # noqa: E402
from scratch import stocks_stage0_regime_20260826 as R               # noqa: E402

HERE = Path(__file__).resolve().parent

#: The window every headline number is measured on. Chosen by the DATA, not by the result:
#: 2019-01-02 is the first session the causal HMM can label, 2022-12-30 the last session the
#: 5-minute cache holds. Fixed before any P&L was computed.
WIN_START, WIN_END = "2019-01-02", "2022-12-30"
IS_END = "2020-12-31"          # in-sample half; nothing is selected on it in this stage

CONFIGS = {
    "A": dict(label="signal_only", spy_short_gate=False, context_filter=None),
    "B": dict(label="spy_short_gate", spy_short_gate=True, context_filter=None),
    "C": dict(label="r4_filter_futures_threshold", spy_short_gate=True,
              context_filter="futures"),
    "D": dict(label="r4_filter_stock_p90", spy_short_gate=True, context_filter="stock"),
}


# ═══════════════════════════════════════════════════════════════════════════════
def eligible_universe(cal, liq: E.LiquidityFilter, verbose=True) -> tuple:
    """Symbols that clear the liquidity and history floors, and the reason each other failed.

    The floors are tested on the WHOLE window rather than per session for admission to the
    universe; the per-session floor is applied again at each candidate, because a name that is
    liquid on average can be illiquid on the day it signals.
    """
    uni = D.universe()
    keep, rejected = [], {}
    for t in uni:
        n = sum(1 for d in cal if D.session_path(t, d).exists())
        if n < liq.min_history_sessions:
            rejected[t] = "history_{}_sessions".format(n)
            continue
        keep.append(t)
    if verbose:
        print("universe: {} cached, {} pass history floor, {} rejected"
              .format(len(uni), len(keep), len(rejected)))
    return keep, rejected


def symbol_candidates(sym: str, cal, labels_obj, params, short_days, ctx_mode,
                      stock_range_threshold, liq: E.LiquidityFilter) -> tuple:
    """Every Normal-R4 candidate this symbol produced, with its features and liquidity verdict."""
    df = D.load_symbol(sym, cal)
    if df.empty or len(df) < 78 * liq.min_history_sessions // 2:
        return [], None, dict(reason="insufficient_bars", bars=len(df))

    daily = D.daily_from_5m(df)
    datr = D.daily_atr_causal(daily)
    adv = D.adv_dollar(daily)

    # One filter object. It is the GATE only when the config says so; either way its
    # `features()` supply the two rule values every ledger row has to carry.
    meas = NF.R4ContextFilter(df, range_max=(stock_range_threshold
                                             if ctx_mode == "stock" else params.range_max),
                              vol_max=params.rel_volume_max,
                              vol_feature=params.vol_feature)
    gate = meas if ctx_mode in ("futures", "stock") else None

    trades, stops, stats = E.run_symbol(df, labels_obj, params, short_days=short_days,
                                        datr=datr, context_filter=gate)
    E.clear_engine_cache()

    out = []
    for t in trades:
        ets = pd.Timestamp(t["entry_time"]) if t.get("entry_time") is not None else None
        xts = pd.Timestamp(t["exit_time"]) if t.get("exit_time") is not None else None
        if ets is None:
            continue
        eday = pd.Timestamp(t["day"]).normalize()
        rec = stops.get(ets)
        stop_px = float(rec[1]) if rec else float("nan")
        f = meas.features(ets)
        bar_vol = float(df["volume"].get(ets, np.nan))
        adv_usd = float(adv.get(eday, np.nan))
        # The engine rounds entry and exit to two decimals before booking `points`, so
        # `t["entry"]` is the price the P&L was computed from and has to stay the P&L basis.
        # The STOP, however, was returned unrounded, and the rule that produced it is
        # `entry_raw -+ 2.0 x daily ATR`. Measuring the stop distance against the ROUNDED
        # entry therefore reproduces 2.0 x ATR on only 58% of rows — off by up to half a
        # cent, which is small money and a wrong number. The share count is computed from
        # the rule's own distance; both prices are carried so the ledger can be checked.
        px = float(t["entry"])
        px_signal = float(rec[0]) if rec else px

        rej = ""
        if not np.isfinite(adv_usd):
            rej = "adv_unknown"
        elif adv_usd < liq.min_adv_usd:
            rej = "adv_below_floor"
        elif px < liq.min_price:
            rej = "price_below_floor"

        dist = abs(px_signal - stop_px)
        out.append(dict(
            symbol=sym, candidate_ts=str(ets), entry_ts=ets, exit_ts=(xts if xts is not None
                                                                      else ets),
            entry_day=str(eday.date()), exit_day=str(t["exit_day"]),
            direction=t["direction"], regime=str(t["regime"]),
            entry_price=px, entry_price_signal=px_signal, exit_price=float(t["exit"]),
            stop_price=stop_px, stop_distance=dist,
            stop_distance_pct=(dist / px * 100 if px else float("nan")),
            daily_atr=float(datr.asof(eday)) if len(datr) else float("nan"),
            prev_day_range_pct=float(f["prev_range_pct"]) * 100 if np.isfinite(
                f["prev_range_pct"]) else float("nan"),
            entry_bar_rvol=float(f["rvol"]) if np.isfinite(f["rvol"]) else float("nan"),
            adv_usd=adv_usd, entry_bar_volume=bar_vol,
            points=float(t["points"]), hold_days=int(t["hold_days"]),
            exit_reason=str(t["reason"]),
            entry_reason="ema{}_pullback_volume_resume|regime={}|window=14:00-15:55".format(
                params.ema_period, t["regime"]),
            liquidity_reject=rej,
            risk_rank=dist,
        ))
    return out, stats, dict(reason="ok", bars=len(df), sessions=len(daily))


# ═══════════════════════════════════════════════════════════════════════════════
def metrics(rows: list, initial: float) -> dict:
    taken = [r for r in rows if r.status == "TAKEN"]
    if not taken:
        return dict(trades=0, net=0.0)
    net = np.array([r.net_pnl for r in taken])
    gross = np.array([r.gross_pnl for r in taken])
    costs = np.array([r.total_cost for r in taken])
    order = np.argsort([pd.Timestamp(r.exit_ts) for r in taken])
    eq = initial + np.cumsum(net[order])
    peak = np.maximum.accumulate(np.concatenate([[initial], eq]))
    dd = peak[1:] - eq
    wins, losses = net[net > 0], net[net <= 0]
    hold = np.array([r.hold_days for r in taken])
    notional = np.array([r.notional for r in taken])
    yrs = max((pd.Timestamp(taken[order[-1]].exit_ts)
               - pd.Timestamp(taken[order[0]].entry_ts)).days / 365.25, 1e-9)
    return dict(
        candidates=len(rows), trades=len(taken), rejected=len(rows) - len(taken),
        net=round(float(net.sum()), 2), gross=round(float(gross.sum()), 2),
        costs=round(float(costs.sum()), 2),
        cost_pct_of_gross=(round(float(costs.sum() / abs(gross.sum()) * 100), 1)
                           if gross.sum() else None),
        return_pct=round(float(net.sum() / initial * 100), 2),
        cagr_pct=round(float(((initial + net.sum()) / initial) ** (1 / yrs) * 100 - 100), 2),
        win_rate=round(float(len(wins) / len(net) * 100), 1),
        avg_win=round(float(wins.mean()), 2) if len(wins) else 0.0,
        avg_loss=round(float(losses.mean()), 2) if len(losses) else 0.0,
        profit_factor=(round(float(wins.sum() / abs(losses.sum())), 2)
                       if len(losses) and losses.sum() != 0 else None),
        expectancy=round(float(net.mean()), 2),
        max_dd=round(float(dd.max()), 2),
        calmar=(round(float((net.sum() / yrs) / dd.max()), 2) if dd.max() > 0 else None),
        sharpe_per_trade=(round(float(net.mean() / net.std(ddof=1)), 3)
                          if len(net) > 1 and net.std(ddof=1) > 0 else None),
        avg_hold_days=round(float(hold.mean()), 2),
        median_hold_days=float(np.median(hold)),
        turnover_notional=round(float(notional.sum()), 2),
        turnover_x_capital=round(float(notional.sum() / initial), 1),
        years=round(yrs, 2),
    )


def ledger_self_check(rows: list, cands: list, sizing) -> dict:
    """Checks the ledger has to survive before any number from it is quoted.

    Written to be able to go RED. Each one names a value that is impossible if the pipeline is
    sound, and several of them have already fired during this build: LC3 caught the ledger
    sizing on the engine's rounded entry instead of the rule's own distance.
    """
    taken = [r for r in rows if r.status == "TAKEN"]
    out: dict = {}
    out["LC0_candidates_nonempty"] = len(cands) > 0
    out["LC1_rows_match_candidates"] = len(rows) == len(cands)
    if not taken:
        out["LC_taken_nonempty"] = False
        return out
    out["LC_taken_nonempty"] = True
    out["LC2_shares_positive"] = all(r.shares >= 1 and r.notional > 0 for r in taken)
    out["LC3_net_equals_gross_minus_cost"] = all(
        abs(r.net_pnl - (r.gross_pnl - r.total_cost)) < 0.011 for r in taken)

    ratio_ok = 0
    for r in taken:
        if np.isfinite(r.daily_atr) and r.daily_atr > 0:
            if abs(r.stop_distance / r.daily_atr - 2.0) < 1e-9:
                ratio_ok += 1
    out["LC4_stop_distance_is_2x_daily_atr_frac"] = round(ratio_ok / len(taken), 4)
    out["LC4_pass"] = ratio_ok / len(taken) > 0.995

    # The engine books entry and exit at two decimals, so gross can differ from
    # points x shares by up to one cent per share. More than that is a real defect.
    out["LC5_gross_within_engine_rounding"] = all(
        abs(r.gross_pnl - (r.exit_price - r.entry_price)
            * (1 if r.direction == "LONG" else -1) * r.shares) <= 0.011 * r.shares + 0.02
        for r in taken)
    out["LC6_regime_is_normal_only"] = all(r.regime == "Normal" for r in taken)
    out["LC7_entry_inside_window"] = all(
        pd.Timestamp(r.entry_ts).time() >= pd.Timestamp("14:00").time()
        and pd.Timestamp(r.entry_ts).time() <= pd.Timestamp("15:55").time() for r in taken)
    out["LC8_exit_not_before_entry"] = all(
        pd.Timestamp(r.exit_ts) >= pd.Timestamp(r.entry_ts) for r in taken)
    out["LC9_equity_basis_positive"] = all(r.equity_basis_at_entry > 0 for r in taken)
    out["LC10_adv_participation_respected"] = all(
        (not np.isfinite(r.adv_usd)) or r.adv_usd <= 0
        or r.shares <= sizing.max_pct_of_adv_shares * (r.adv_usd / r.entry_price) + 1
        for r in taken)
    out["LC11_liquidity_floor_respected"] = all(
        r.adv_usd >= E.LiquidityFilter().min_adv_usd
        and r.entry_price >= E.LiquidityFilter().min_price for r in taken)
    return out


def breakdowns(rows: list) -> dict:
    taken = [r for r in rows if r.status == "TAKEN"]
    out: dict = {}
    if not taken:
        return out
    df = pd.DataFrame([asdict(r) for r in taken])
    df["year"] = pd.to_datetime(df["exit_ts"]).dt.year
    out["by_year"] = {int(y): dict(trades=int(len(g)), net=round(float(g.net_pnl.sum()), 2),
                                   win_rate=round(float((g.net_pnl > 0).mean() * 100), 1))
                      for y, g in df.groupby("year")}
    sym = df.groupby("symbol").net_pnl.agg(["count", "sum"]).sort_values("sum",
                                                                        ascending=False)
    out["by_symbol"] = {k: dict(trades=int(v["count"]), net=round(float(v["sum"]), 2))
                        for k, v in sym.iterrows()}
    out["top10_winners"] = df.nlargest(10, "net_pnl")[
        ["symbol", "entry_ts", "direction", "shares", "net_pnl", "exit_reason"]
    ].to_dict("records")
    out["top10_losers"] = df.nsmallest(10, "net_pnl")[
        ["symbol", "entry_ts", "direction", "shares", "net_pnl", "exit_reason"]
    ].to_dict("records")
    out["by_exit_reason"] = {k: dict(trades=int(len(g)), net=round(float(g.net_pnl.sum()), 2))
                             for k, g in df.groupby("exit_reason")}
    out["by_direction"] = {k: dict(trades=int(len(g)), net=round(float(g.net_pnl.sum()), 2))
                           for k, g in df.groupby("direction")}
    out["concentration"] = dict(
        top1_share_pct=round(float(sym["sum"].iloc[0] / df.net_pnl.sum() * 100), 1)
        if df.net_pnl.sum() else None,
        top5_share_pct=round(float(sym["sum"].head(5).sum() / df.net_pnl.sum() * 100), 1)
        if df.net_pnl.sum() else None,
        n_symbols_traded=int(df.symbol.nunique()))
    rej = pd.DataFrame([asdict(r) for r in rows if r.status == "REJECTED"])
    out["reject_reasons"] = ({k: int(v) for k, v in rej.reject_reason.value_counts().items()}
                             if len(rej) else {})
    return out


# ═══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    # Declared here rather than beside the assignment: Python requires `global` to precede
    # every use of the name in the function, and these are read as argparse defaults above
    # the point where they are set.
    global WIN_START, WIN_END, IS_END
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="B")
    ap.add_argument("--labels", default="causal", choices=["causal", "production"])
    ap.add_argument("--lag", type=int, default=1)
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-etf", action="store_true")
    # The window is a CLI argument rather than a constant because the answerable window
    # is decided by the DATA, and the data boundary moved once already: there are zero
    # 5-minute session files for 2023 onward, and the causal HMM cannot label before
    # 2019-01-02. A window passed on the command line is one a reader can check against
    # the coverage table; a window baked into a constant is one they have to trust.
    ap.add_argument("--start", default=WIN_START)
    ap.add_argument("--end", default=WIN_END)
    ap.add_argument("--is-end", default=None,
                    help="last day of the in-sample half; default = midpoint")
    args = ap.parse_args()

    WIN_START, WIN_END = args.start, args.end
    if args.is_end:
        IS_END = args.is_end
    else:
        _mid = (pd.Timestamp(WIN_START)
                + (pd.Timestamp(WIN_END) - pd.Timestamp(WIN_START)) / 2)
        IS_END = str(_mid.normalize().date())

    t_start = time.time()
    cal_all = D.calendar("SPY")
    cal = pd.DatetimeIndex([d for d in cal_all
                            if pd.Timestamp(WIN_START) <= d <= pd.Timestamp(WIN_END)])
    print("window {} .. {}  ({} sessions)".format(WIN_START, WIN_END, len(cal)))

    liq = E.LiquidityFilter()
    sizing = E.SizingModel()
    cost = E.StockCostModel()

    syms, uni_rejected = eligible_universe(cal, liq)
    if args.no_etf:
        syms = [s for s in syms if s not in D.ETFS]
    if args.max_symbols:
        syms = syms[:args.max_symbols]
    print("symbols to run:", len(syms))

    lab_df = R.labels()
    labels_obj = R.LaggedLabels(lab_df[args.labels], lag=args.lag)

    params_base = dict(ema_period=args.ema, stop_basis_atr_mult=2.0,
                       chandelier_atr_mult=2.5, max_hold_days=5, ratchet=False,
                       fill_law=NR.FILL_PRODUCTION)

    results: dict = {}
    for key in [c.strip().upper() for c in args.configs.split(",") if c.strip()]:
        cfg = CONFIGS[key]
        print("\n=== config {} — {} ===".format(key, cfg["label"]))
        params = NR.NormalR4Params(**params_base)
        short_days = (NF.short_days_from_csv(str(D.SPY_CSV), params.spy_short_filter)
                      if cfg["spy_short_gate"] else None)
        if short_days is None:
            # No SPY gate means every session admits a SHORT. Expressed as a full set rather
            # than a None branch so the engine keeps running one code path.
            short_days = {pd.Timestamp(d).normalize() for d in cal}

        stock_threshold = float("nan")
        if cfg["context_filter"] == "stock":
            base = results.get("B", {}).get("_prev_range_is")
            if not base:
                print("  config D needs config B's in-sample prior-day ranges; run B first.")
                continue
            stock_threshold = float(np.percentile(base, 90))
            print("  stock-derived prior-day range p90 (IS {}..{}): {:.4f}"
                  .format(WIN_START, IS_END, stock_threshold))

        cands, stats_all, prev_range_is, skipped = [], {}, [], {}
        for i, s in enumerate(syms, 1):
            t0 = time.time()
            c, st, info = symbol_candidates(s, cal, labels_obj, params, short_days,
                                            cfg["context_filter"], stock_threshold, liq)
            if info["reason"] != "ok":
                skipped[s] = info
            cands.extend(c)
            if st:
                stats_all[s] = st
            for r in c:
                if r["entry_day"] <= IS_END and np.isfinite(r["prev_day_range_pct"]):
                    prev_range_is.append(r["prev_day_range_pct"] / 100.0)
            print("  [{:3d}/{:3d}] {:6s} {:4d} candidates  ({:.1f}s)".format(
                i, len(syms), s, len(c), time.time() - t0), flush=True)

        # The candidate stream is cached BEFORE the book sees it. Everything downstream —
        # cost model, risk fraction, caps — can then be re-measured by re-booking the same
        # stream, which is the only way a sensitivity is a sensitivity rather than a
        # different backtest: exactly one thing moves.
        stream = HERE / "_stocks_stage0_candidates_{}.pkl".format(
            args.tag or "{}_{}_lag{}_ema{}".format(key, args.labels, args.lag, args.ema))
        pd.to_pickle(cands, stream)

        rows, eq = E.build_book(cands, sizing, cost)
        m = metrics(rows, sizing.initial_capital)
        b = breakdowns(rows)
        lc = ledger_self_check(rows, cands, sizing)
        print("\n  --- ledger self-check ---")
        for k, v in lc.items():
            mark = "[PASS]" if (v is True or (isinstance(v, float) and k.endswith("_frac")
                                              and v > 0.995)) else (
                "[----]" if not isinstance(v, bool) else "[FAIL]")
            print("  {} {} = {}".format(mark, k, v))

        is_rows = [r for r in rows if r.entry_day <= IS_END]
        oos_rows = [r for r in rows if r.entry_day > IS_END]

        ident_cfg = dict(
            universe_definition="polygon_5min_cache_tickers_history>=250_sessions",
            universe_size=len(syms), universe_is_point_in_time=False,
            data_source_identity=D.DATA_SOURCE, bar_interval="5min", adjusted=True,
            session="RTH_0930_1555", timezone="America/New_York",
            calendar_source="SPY_cached_session_files",
            ema_period=params.ema_period, max_hold_days=params.max_hold_days,
            entry_window="14:00-15:55", signal_rule="trend_follow_ema_pullback_volume_resume",
            stop_basis="fixed_entry_atr", stop_multiple=params.stop_basis_atr_mult,
            stop_anchor="entry", ratchet=params.ratchet, arm_hour="14:05",
            arm_timezone="America/New_York",
            atr_basis="daily_atr14_rth_shift1_causal", fill_law=params.fill_law,
            regime_model="spy_gaussian_hmm_3state", regime_fit_end=(
                "2018-12-31" if args.labels == "causal" else "2024-12-31"),
            regime_label_lag_days=args.lag,
            regime_csv_identity="spy_daily_live.csv",
            spy_short_filter=(params.spy_short_filter if cfg["spy_short_gate"] else "none"),
            spy_short_lookback=NF.SPY_SHORT_LOOKBACK,
            spy_short_lag_days=NF.SPY_SHORT_LAG_DAYS,
            r4_context_filter=str(cfg["context_filter"]),
            r4_range_threshold=(stock_threshold if cfg["context_filter"] == "stock"
                                else (params.range_max if cfg["context_filter"] else None)),
            r4_range_derivation_window=("stocks_IS_{}_{}".format(WIN_START, IS_END)
                                        if cfg["context_filter"] == "stock"
                                        else ("futures_floor_2018_2024"
                                              if cfg["context_filter"] else None)),
            r4_rel_volume_max=(params.rel_volume_max if cfg["context_filter"] else None),
            execution_model="entry_at_resume_bar_close;stop_exit_at_stop;gap_exit_at_open;"
                            "maxhold_exit_at_0930_bar_open",
            sizing_basis="risk_pct_of_initial_plus_realised/|entry-stop|",
            risk_pct=sizing.risk_pct,
            max_position_notional_pct=sizing.max_position_notional_pct,
            max_gross_notional_pct=sizing.max_gross_notional_pct,
            max_concurrent_positions=sizing.max_concurrent_positions,
            commission_per_share=cost.commission_per_share,
            min_commission_per_order=cost.min_commission_per_order,
            slippage_bps_per_side=cost.slippage_bps_per_side,
            stop_exit_extra_bps=cost.stop_exit_extra_bps,
            borrow_bps_per_year=cost.borrow_bps_per_year,
            min_price=liq.min_price, min_adv_usd=liq.min_adv_usd,
            min_history_sessions=liq.min_history_sessions,
            max_pct_of_adv_shares=sizing.max_pct_of_adv_shares,
            max_pct_of_entry_bar_volume=sizing.max_pct_of_entry_bar_volume,
            initial_capital=sizing.initial_capital,
            window="{}..{}".format(WIN_START, WIN_END))
        readable, chash = E.config_identity(ident_cfg)

        tag = args.tag or "{}_{}_lag{}_ema{}".format(key, args.labels, args.lag, args.ema)
        led = HERE / "_stocks_stage0_ledger_{}.csv".format(tag)
        pd.DataFrame([asdict(r) for r in rows]).to_csv(led, index=False)

        results[key] = dict(
            config=cfg["label"], config_hash=chash, config_readable=readable,
            config_fields=ident_cfg,
            overall=m, is_window=metrics(is_rows, sizing.initial_capital),
            oos_window=metrics(oos_rows, sizing.initial_capital),
            breakdowns=b, self_check=lc, filter_stats_symbols=len(stats_all),
            filter_stats_total={k: int(sum(v.get(k, 0) for v in stats_all.values()))
                                for k in ("seen", "blocked_range", "blocked_vol",
                                          "blocked_missing", "passed")} if stats_all else {},
            skipped_symbols=skipped, ledger=str(led), candidate_stream=str(stream),
            _prev_range_is=prev_range_is)

        print("\n  candidates={} taken={} rejected={}".format(
            m.get("candidates", 0), m.get("trades", 0), m.get("rejected", 0)))
        print("  net ${:,.2f}  gross ${:,.2f}  costs ${:,.2f} ({}% of gross)".format(
            m.get("net", 0), m.get("gross", 0), m.get("costs", 0),
            m.get("cost_pct_of_gross")))
        print("  return {}%  CAGR {}%  PF {}  win {}%  maxDD ${:,.2f}  Calmar {}".format(
            m.get("return_pct"), m.get("cagr_pct"), m.get("profit_factor"),
            m.get("win_rate"), m.get("max_dd", 0), m.get("calmar")))
        print("  ledger:", led)

    out = HERE / ("_stocks_stage0_results{}.json".format("_" + args.tag if args.tag else ""))
    slim = {k: {kk: vv for kk, vv in v.items() if kk != "_prev_range_is"}
            for k, v in results.items()}
    out.write_text(json.dumps(dict(window=[WIN_START, WIN_END], is_end=IS_END,
                                   labels=args.labels, lag=args.lag, ema=args.ema,
                                   symbols=syms, universe_rejected=uni_rejected,
                                   results=slim), indent=2, default=str), encoding="utf-8")
    print("\nwrote", out, " ({:.0f}s total)".format(time.time() - t_start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
