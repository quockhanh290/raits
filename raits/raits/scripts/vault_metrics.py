"""
scripts/vault_metrics.py
------------------------
STANDALONE, READ-ONLY — computes the MISSING vault metrics from the latest
(or specified) snapshot pickle. Does NOT re-run the engine or vault.

Vault already reported: Calmar 1.04, Sharpe 0.88, MaxDD -6.9%, PF 1.18,
WinRate 48.4%, TotalReturn 14.8%, 405 trades.
This script adds: R² vs SPY, Beta, Pearson correlation, down-month analysis,
tail-risk (Sortino, consecutive losses, worst week), per-strategy/ticker/regime/
quarter breakdowns, and a structured PASS/FAIL gate.

Assumption: starting account capital = $50,000 (override with --capital).
SPY daily data read from cache — no network calls.

Usage:
    cd d:\\raits\\raits
    python raits/scripts/vault_metrics.py
    python raits/scripts/vault_metrics.py --snapshot <path.pkl>
    python raits/scripts/vault_metrics.py --spy-csv <path.csv>
    python raits/scripts/vault_metrics.py --capital 50000
"""

import sys, os, glob, argparse, pickle
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

# Force UTF-8 on Windows terminals that default to CP1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Path setup ─────────────────────────────────────────────────────────────────
HERE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

DEFAULT_SNAP_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "data", "cache", "snapshots")
)
DEFAULT_SPY_PQ = os.path.normpath(
    os.path.join(HERE, "..", "..", "data", "cache", "daily",
                 "SPY_daily_2017-01-03_2024-12-31.parquet")
)

OOS_START = pd.Timestamp("2023-01-01")
OOS_END   = pd.Timestamp("2024-12-31")

# Blueprint tier thresholds (metrics.py check_vault_tier)
TIER1 = dict(calmar=2.0, pf=1.35, max_dd=-0.15, sharpe=1.5, win_rate=0.40, tail=-0.04)
TIER2 = dict(calmar=1.5, pf=1.20, max_dd=-0.18, sharpe=1.2, win_rate=0.35, tail=-0.05)

SEP  = "=" * 72
SEP2 = "-" * 65


# ══ Loaders ════════════════════════════════════════════════════════════════════

def find_latest_snap(snap_dir: str) -> str | None:
    pkls = sorted(glob.glob(os.path.join(snap_dir, "results_2*.pkl")))
    return pkls[-1] if pkls else None


def load_results(path: str) -> list:
    with open(path, "rb") as f:
        return pickle.load(f)


def find_vault_window(results: list) -> dict | None:
    """Return the result dict whose label contains '2023'."""
    for r in results:
        if "2023" in str(r.get("label", "")):
            return r
    return results[-1] if results else None


def trades_to_df(trades: list) -> pd.DataFrame:
    rows = []
    for t in trades:
        if t.is_open or t.net_pnl is None:
            continue
        rows.append(dict(
            ticker      = t.ticker,
            strategy    = t.strategy,
            direction   = t.direction,
            entry_time  = pd.Timestamp(t.entry_time),
            exit_time   = pd.Timestamp(t.exit_time),
            entry_price = float(t.entry_price),
            exit_price  = float(t.exit_price or 0),
            shares      = int(t.shares),
            stop        = float(t.stop),
            target      = float(t.target),
            exit_reason = t.exit_reason,
            hmm_state   = t.hmm_state,
            gross_pnl   = float(t.gross_pnl or 0),
            total_costs = float(t.total_costs or 0),
            net_pnl     = float(t.net_pnl),
        ))
    return pd.DataFrame(rows)


def load_spy_daily(spy_pq: str, spy_csv: str | None = None) -> pd.DataFrame | None:
    for path, is_pq in [(spy_pq, True), (spy_csv, False)]:
        if not path or not os.path.exists(path):
            continue
        df = pd.read_parquet(path) if is_pq else pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        return df.sort_index()
    return None


# ══ Return series ═══════════════════════════════════════════════════════════════

def _strip_tz(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_localize(None) if idx.tz is not None else idx


def build_raits_daily(equity_curve: pd.Series) -> pd.Series:
    """Daily RAITS returns from equity curve (preferred path)."""
    eq = equity_curve.copy()
    eq.index = _strip_tz(pd.DatetimeIndex(eq.index))
    eq = eq[(eq.index >= OOS_START) & (eq.index <= OOS_END + pd.Timedelta("2D"))]
    if eq.empty:
        return pd.Series(dtype=float)
    return eq.resample("B").last().ffill().dropna().pct_change().dropna()


def build_raits_daily_from_trades(trades_df: pd.DataFrame, capital: float) -> pd.Series:
    """Fallback: net P&L per exit-date / capital."""
    pnl = trades_df.groupby(trades_df["exit_time"].dt.normalize())["net_pnl"].sum()
    pnl.index = _strip_tz(pd.DatetimeIndex(pnl.index))
    bdays = pd.bdate_range(OOS_START, OOS_END)
    return pnl.reindex(bdays, fill_value=0.0) / capital


def build_raits_monthly(trades_df: pd.DataFrame, capital: float):
    """Monthly P&L ($) and return (fraction). Period('M') index."""
    df = trades_df.copy()
    df["_month"] = df["exit_time"].dt.to_period("M")
    pnl = df.groupby("_month")["net_pnl"].sum()
    return pnl, pnl / capital


def build_spy_daily(spy_df: pd.DataFrame) -> pd.Series:
    oos = spy_df[(spy_df.index >= OOS_START) & (spy_df.index <= OOS_END + pd.Timedelta("2D"))]
    return oos["close"].resample("B").last().dropna().pct_change().dropna()


def build_spy_monthly(spy_df: pd.DataFrame) -> pd.Series:
    """SPY monthly returns. Period('M') index for alignment with RAITS."""
    oos = spy_df[(spy_df.index >= OOS_START) & (spy_df.index <= OOS_END + pd.Timedelta("2D"))]
    try:
        monthly = oos["close"].resample("ME").last().dropna()
    except ValueError:
        monthly = oos["close"].resample("M").last().dropna()
    ret = monthly.pct_change().dropna()
    ret.index = ret.index.to_period("M")
    return ret


# ══ Group A: Market Independence ════════════════════════════════════════════════

def compute_group_a(raits_daily: pd.Series, spy_daily: pd.Series,
                    raits_monthly_pnl: pd.Series, raits_monthly_ret: pd.Series,
                    spy_monthly_ret: pd.Series) -> dict:
    res = {}

    # ── Daily R², Beta, Pearson ──────────────────────────────────────────────
    aligned_d = pd.concat([raits_daily.rename("r"), spy_daily.rename("s")],
                           axis=1).dropna()
    res["n_days"] = len(aligned_d)
    if len(aligned_d) >= 10:
        slope, _, r_val, _, _ = sp_stats.linregress(
            aligned_d["s"].values, aligned_d["r"].values
        )
        res["r_squared"] = float(r_val ** 2)
        res["beta"]      = float(slope)
        res["r_value"]   = float(r_val)
    else:
        res["r_squared"] = res["beta"] = res["r_value"] = float("nan")

    # ── Monthly Pearson (signed) ─────────────────────────────────────────────
    aligned_m = pd.concat([raits_monthly_ret.rename("r"), spy_monthly_ret.rename("s")],
                           axis=1).dropna()
    res["monthly_pearson"] = (
        float(aligned_m["r"].corr(aligned_m["s"])) if len(aligned_m) >= 3 else float("nan")
    )

    # ── Down-month analysis ──────────────────────────────────────────────────
    spy_m = spy_monthly_ret.to_frame("spy_ret")          # Period("M") index
    down  = spy_m[spy_m["spy_ret"] < 0].copy()
    down["raits_pnl"] = raits_monthly_pnl.reindex(down.index).fillna(0)

    res["down_months_df"]           = down
    res["n_down_months"]            = len(down)
    res["down_months_total_pnl"]    = float(down["raits_pnl"].sum())
    res["down_months_avg_pnl"]      = float(down["raits_pnl"].mean()) if len(down) > 0 else 0.0
    n_pos = int((down["raits_pnl"] > 0).sum())
    res["n_down_months_positive"]   = n_pos
    res["pct_down_positive"]        = n_pos / len(down) if len(down) > 0 else float("nan")
    return res


def _empty_group_a() -> dict:
    return dict(
        r_squared=float("nan"), beta=float("nan"), r_value=float("nan"), n_days=0,
        monthly_pearson=float("nan"), down_months_df=pd.DataFrame(),
        n_down_months=0, down_months_total_pnl=0.0, down_months_avg_pnl=0.0,
        n_down_months_positive=0, pct_down_positive=float("nan"),
    )


# ══ Group B: Tail Risk ══════════════════════════════════════════════════════════

def compute_group_b(raits_daily: pd.Series, trades_df: pd.DataFrame,
                    equity_curve: pd.Series, capital: float) -> dict:
    res = {}
    res["tail_99"]        = float(raits_daily.quantile(0.01))
    res["worst_day"]      = float(raits_daily.min())
    res["worst_day_date"] = raits_daily.idxmin()

    wi = trades_df["net_pnl"].idxmin()
    wt = trades_df.loc[wi]
    res["worst_trade_pnl"]    = float(wt["net_pnl"])
    res["worst_trade_ticker"] = wt["ticker"]
    res["worst_trade_date"]   = pd.Timestamp(wt["exit_time"]).date()

    weekly = raits_daily.resample("W").sum()
    res["worst_week"]     = float(weekly.min())
    res["worst_week_end"] = weekly.idxmin().date()

    # Max consecutive losing trades
    pnls = trades_df.sort_values("exit_time")["net_pnl"].values
    max_c = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_c = max(max_c, cur)
        else:
            cur = 0
    res["max_consec_losses"] = max_c

    # Sortino
    neg = raits_daily[raits_daily < 0]
    down_std = float(np.sqrt((neg ** 2).mean())) if len(neg) > 0 else 0.0
    res["sortino"] = (
        float(raits_daily.mean() / down_std * np.sqrt(252)) if down_std > 0 else float("inf")
    )

    # Longest drawdown duration (continuous trading days below previous equity peak)
    eq = equity_curve.copy()
    if not eq.empty:
        eq.index = _strip_tz(pd.DatetimeIndex(eq.index))
        eq_oos = eq[(eq.index >= OOS_START) & (eq.index <= OOS_END + pd.Timedelta("2D"))]
        daily_eq = eq_oos.resample("B").last().ffill().dropna()
        if len(daily_eq) > 1:
            in_dd = daily_eq < daily_eq.cummax()
            max_dd_days = cur_dd = 0
            for v in in_dd:
                cur_dd = cur_dd + 1 if v else 0
                max_dd_days = max(max_dd_days, cur_dd)
            res["max_dd_days"] = max_dd_days
        else:
            res["max_dd_days"] = 0
    else:
        res["max_dd_days"] = 0
    return res


# ══ Group C: Stability / Concentration ═════════════════════════════════════════

def compute_group_c(trades_df: pd.DataFrame) -> dict:
    res = {}
    total_pnl = float(trades_df["net_pnl"].sum())
    res["total_pnl"] = total_pnl

    # Per-strategy
    strats = []
    for strat, grp in trades_df.groupby("strategy"):
        gp = float(grp.loc[grp["net_pnl"] > 0, "net_pnl"].sum())
        gl = float(abs(grp.loc[grp["net_pnl"] <= 0, "net_pnl"].sum()))
        pf = gp / gl if gl > 0 else float("inf")
        strats.append(dict(
            strategy = strat,
            n        = len(grp),
            win_rate = float((grp["net_pnl"] > 0).sum()) / len(grp),
            net_pnl  = float(grp["net_pnl"].sum()),
            pf       = pf,
            pct      = float(grp["net_pnl"].sum()) / total_pnl if total_pnl else 0.0,
        ))
    res["strategies"] = sorted(strats, key=lambda x: -abs(x["net_pnl"]))

    # Top-5 tickers by net P&L share
    ticker_pnl = trades_df.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    res["top5_tickers"] = [
        dict(ticker=t, net_pnl=float(p), pct=float(p) / total_pnl if total_pnl else 0.0)
        for t, p in ticker_pnl.head(5).items()
    ]
    res["top1_pct"] = res["top5_tickers"][0]["pct"] if res["top5_tickers"] else 0.0

    # Per-regime
    regimes = []
    for regime, grp in trades_df.groupby("hmm_state"):
        regimes.append(dict(regime=regime, n=len(grp), net_pnl=float(grp["net_pnl"].sum())))
    res["regimes"] = regimes

    # Per-quarter (expect 8 quarters across 2023-2024)
    df = trades_df.copy()
    df["_quarter"] = df["exit_time"].dt.to_period("Q")
    quarterly = df.groupby("_quarter")["net_pnl"].sum()
    res["quarterly"] = [(str(q), float(p)) for q, p in quarterly.items()]
    res["max_quarter_pct"] = float(quarterly.max() / total_pnl) if total_pnl else 0.0

    # Long vs short split
    res["long_pnl"]  = float(trades_df[trades_df["direction"] == "LONG"]["net_pnl"].sum())
    res["short_pnl"] = float(trades_df[trades_df["direction"] == "SHORT"]["net_pnl"].sum())
    return res


# ══ Output printers ═════════════════════════════════════════════════════════════

def _nan(v) -> bool:
    try:
        return np.isnan(v)
    except (TypeError, ValueError):
        return False


def print_gate(vault_known: dict, grp_a: dict, grp_b: dict, grp_c: dict) -> None:
    print(f"\n{SEP}")
    print(f"  TIER 1 — DECISION GATE")
    print(SEP)

    r2     = grp_a.get("r_squared", float("nan"))
    pf     = vault_known["pf"]
    max_dd = vault_known["max_dd"]
    dm_pnl = grp_a.get("down_months_total_pnl", 0.0)
    max_q  = grp_c["max_quarter_pct"]
    top1   = grp_c["top1_pct"]

    checks = [
        ("R² vs SPY (daily)",          r2,     "< 0.40",  (not _nan(r2)) and r2 < 0.40),
        ("Profit Factor",              pf,     "> 1.0",   pf > 1.0),
        ("Max Drawdown",               max_dd, "> -18%",  max_dd > -0.18),
        ("Down-month net P&L ($)",     dm_pnl, "> 0",     dm_pnl > 0),
        ("Max quarter % of total P&L", max_q,  "< 60%",   max_q < 0.60),
        ("Top ticker % of total P&L",  top1,   "< 40%",   top1 < 0.40),
    ]
    all_pass = all(ok for *_, ok in checks)

    print(f"\n  VERDICT: {'PASS ✓' if all_pass else 'FAIL ✗'}\n")
    print(f"  {'Metric':<35} {'Value':>12}  {'Threshold':>10}  Result")
    print(f"  {'-'*65}")
    for metric, val, thresh, ok in checks:
        if _nan(val):
            vstr = "N/A"
        elif "R²" in metric:
            vstr = f"{val:.4f}"
        elif "Factor" in metric or "R²" in metric:
            vstr = f"{val:.2f}"
        elif "Drawdown" in metric:
            vstr = f"{val*100:.1f}%"
        elif "P&L ($)" in metric:
            vstr = f"${val:+,.0f}"
        elif "%" in metric:
            vstr = f"{val*100:.1f}%"
        else:
            vstr = f"{val:.4f}"
        print(f"  {metric:<35} {vstr:>12}  {thresh:>10}  {'OK' if ok else 'FAIL'}")

    print()
    if all_pass:
        r2_tag = "very low" if r2 < 0.10 else ("low" if r2 < 0.20 else "moderate")
        dm_tag = "positive" if dm_pnl > 0 else "negative"
        print(f"  READ: GENUINE ALPHA — R²={r2:.3f} ({r2_tag}, WFO baseline 0.018),")
        print(f"        down-months net P&L is {dm_tag} → system does not move with market.")
    else:
        fails = [m for m, *_, ok in checks if not ok]
        print(f"  READ: GATE FAILED — {', '.join(fails)}")
        if not _nan(r2) and r2 >= 0.40:
            print(f"        R²={r2:.3f} ≥ 0.40 means returns are BETA-DRIVEN, not alpha.")


def print_tier(vault_known: dict, grp_b: dict) -> None:
    print(f"\n{SEP}")
    print(f"  TIER 2 — TIER CLASSIFICATION")
    print(SEP)

    calmar   = vault_known["calmar"]
    sharpe   = vault_known["sharpe"]
    pf       = vault_known["pf"]
    max_dd   = vault_known["max_dd"]
    win_rate = vault_known["win_rate"]
    tail     = grp_b["tail_99"]
    sortino  = grp_b["sortino"]

    t1 = (calmar > TIER1["calmar"] and pf > TIER1["pf"] and max_dd > TIER1["max_dd"]
          and sharpe > TIER1["sharpe"] and win_rate > TIER1["win_rate"] and tail > TIER1["tail"])
    t2 = (calmar > TIER2["calmar"] and pf > TIER2["pf"] and max_dd > TIER2["max_dd"]
          and sharpe > TIER2["sharpe"] and win_rate > TIER2["win_rate"] and tail > TIER2["tail"])
    tier = "TIER 1" if t1 else ("TIER 2" if t2 else "TIER 3")

    print(f"\n  Result: {tier}\n")
    W = 11
    print(f"  {'Metric':<24} {'Vault':>{W}} {'T1 need':>{W}} {'T2 need':>{W}}  Status")
    print(f"  {'-'*(24 + W*3 + 9)}")
    rows = [
        ("Calmar",         f"{calmar:.2f}",        ">2.00",  ">1.50",  calmar   > TIER1["calmar"],   calmar   > TIER2["calmar"]),
        ("Sharpe",         f"{sharpe:.2f}",         ">1.50",  ">1.20",  sharpe   > TIER1["sharpe"],   sharpe   > TIER2["sharpe"]),
        ("Profit Factor",  f"{pf:.2f}",             ">1.35",  ">1.20",  pf       > TIER1["pf"],       pf       > TIER2["pf"]),
        ("Max Drawdown",   f"{max_dd*100:.1f}%",   ">-15%",  ">-18%",  max_dd   > TIER1["max_dd"],   max_dd   > TIER2["max_dd"]),
        ("Win Rate",       f"{win_rate*100:.1f}%", ">40%",   ">35%",   win_rate > TIER1["win_rate"], win_rate > TIER2["win_rate"]),
        ("Tail Risk 99%",  f"{tail*100:.2f}%",     ">-4%",   ">-5%",   tail     > TIER1["tail"],     tail     > TIER2["tail"]),
        ("Sortino",        f"{sortino:.2f}" if sortino != float("inf") else "∞",
                                                    "(info)", "(info)", True, True),
    ]
    for name, vstr, t1n, t2n, ok1, ok2 in rows:
        mark = "T1" if ok1 else ("T2" if ok2 else " -")
        print(f"  {name:<24} {vstr:>{W}} {t1n:>{W}} {t2n:>{W}}  [{mark}]")


def print_diagnostic(grp_a: dict, grp_b: dict, grp_c: dict,
                      trades_df: pd.DataFrame, capital: float) -> None:
    print(f"\n{SEP}")
    print(f"  TIER 3 — DIAGNOSTIC DETAIL")
    print(SEP)
    total_pnl = grp_c["total_pnl"]

    # ── [A] Market Independence ───────────────────────────────────────────────
    print(f"\n  [A] MARKET INDEPENDENCE")
    print(f"  {SEP2}")
    r2   = grp_a.get("r_squared",        float("nan"))
    beta = grp_a.get("beta",             float("nan"))
    pear = grp_a.get("monthly_pearson",  float("nan"))
    r2_s   = f"{r2:.4f}"   if not _nan(r2)   else "N/A"
    beta_s = f"{beta:+.4f}" if not _nan(beta) else "N/A"
    pear_s = f"{pear:+.4f}" if not _nan(pear) else "N/A"
    print(f"  R² vs SPY (daily):        {r2_s}"
          f"  ← WFO baseline 0.018, gate threshold 0.40")
    print(f"  Beta vs SPY:              {beta_s}")
    print(f"  Pearson r (monthly):      {pear_s}  (signed, not R²)")
    print(f"  Aligned trading days:     {grp_a.get('n_days', 0)}")

    n_dm = grp_a.get("n_down_months", 0)
    dm   = grp_a.get("down_months_df", pd.DataFrame())
    print(f"\n  SPY down-month analysis  ({n_dm} months in 2023-2024 where SPY < 0):")
    if not dm.empty:
        print(f"  {'Month':<10} {'SPY ret':>8} {'RAITS $':>12}")
        print(f"  {'─'*33}")
        for period, row in dm.iterrows():
            print(f"  {str(period):<10} {row['spy_ret']*100:>7.1f}% ${row['raits_pnl']:>+10,.0f}")
        print(f"  {'─'*33}")
        print(f"  Total in down months:   ${grp_a['down_months_total_pnl']:+,.0f}")
        print(f"  Avg per down month:     ${grp_a['down_months_avg_pnl']:+,.0f}")
        pct_pos = grp_a.get("pct_down_positive", float("nan"))
        n_pos   = grp_a.get("n_down_months_positive", 0)
        print(f"  RAITS profitable:       {n_pos}/{n_dm}  ({pct_pos*100:.0f}%)")
    else:
        print(f"  (SPY data unavailable — skipped)")

    # ── [B] Tail Risk ─────────────────────────────────────────────────────────
    print(f"\n  [B] TAIL RISK")
    print(f"  {SEP2}")
    print(f"  99th-pct worst day:       {grp_b['tail_99']*100:.2f}%"
          f"  (Tier1 > -4%, Tier2 > -5%)")
    print(f"  Worst single day:         {grp_b['worst_day']*100:.2f}%"
          f"  ({grp_b['worst_day_date'].date()})")
    wt_pct = grp_b["worst_trade_pnl"] / capital * 100
    print(f"  Worst single trade:       ${grp_b['worst_trade_pnl']:+,.0f}"
          f"  ({wt_pct:.2f}% acct)"
          f"  {grp_b['worst_trade_ticker']} @ {grp_b['worst_trade_date']}")
    print(f"  Worst week (sum):         {grp_b['worst_week']*100:.2f}%"
          f"  (week ending {grp_b['worst_week_end']})")
    print(f"  Max consecutive losses:   {grp_b['max_consec_losses']}")
    so = grp_b["sortino"]
    print(f"  Sortino ratio:            {so:.2f}" if so != float("inf") else
          f"  Sortino ratio:            ∞  (no losing days)")
    print(f"  Longest DD duration:      {grp_b['max_dd_days']} trading days")

    # ── [C1] Per-strategy ─────────────────────────────────────────────────────
    print(f"\n  [C1] PER-STRATEGY BREAKDOWN")
    print(f"  {'Strategy':<22} {'N':>5} {'WR':>7} {'Net P&L':>12} {'PF':>7} {'%Total':>8}  Note")
    print(f"  {'-'*74}")
    for s in grp_c["strategies"]:
        pf_str = f"{s['pf']:.2f}" if s["pf"] < 9999 else "∞"
        flag = "  ← PF < 1.0 !" if s["pf"] < 1.0 else ""
        print(f"  {s['strategy']:<22} {s['n']:>5} {s['win_rate']*100:>6.1f}%"
              f" ${s['net_pnl']:>+10,.0f} {pf_str:>7} {s['pct']*100:>7.1f}%{flag}")
    print(f"  {'-'*74}")
    print(f"  {'TOTAL':<22} {len(trades_df):>5}         ${total_pnl:>+10,.0f}")

    # ── [C2] Ticker concentration ─────────────────────────────────────────────
    print(f"\n  [C2] TOP-5 TICKER CONCENTRATION")
    print(f"  {'Ticker':<10} {'Net P&L':>12} {'% Total':>9}")
    print(f"  {'─'*34}")
    for t in grp_c["top5_tickers"]:
        print(f"  {t['ticker']:<10} ${t['net_pnl']:>+10,.0f} {t['pct']*100:>8.1f}%")
    print(f"  {'─'*34}")
    print(f"  Top-1 dominance: {grp_c['top1_pct']*100:.1f}%  (flag if > 40%;  TSLA was 17% IS)")

    # ── [C3] Regime breakdown ─────────────────────────────────────────────────
    print(f"\n  [C3] PER-REGIME BREAKDOWN")
    print(f"  {'Regime':<12} {'N':>5} {'Net P&L':>12}")
    print(f"  {'─'*32}")
    for r in sorted(grp_c["regimes"], key=lambda x: x["net_pnl"], reverse=True):
        print(f"  {r['regime']:<12} {r['n']:>5} ${r['net_pnl']:>+10,.0f}")

    # ── [C4] Per-quarter ─────────────────────────────────────────────────────
    print(f"\n  [C4] PER-QUARTER P&L  (8 quarters: 2023Q1 → 2024Q4)")
    print(f"  {'Quarter':<10} {'Net P&L':>12} {'% Total':>9}")
    print(f"  {'─'*34}")
    for q, p in grp_c["quarterly"]:
        pct = p / total_pnl * 100 if total_pnl else 0.0
        print(f"  {q:<10} ${p:>+10,.0f} {pct:>8.1f}%")
    print(f"  {'─'*34}")
    print(f"  Max quarter share: {grp_c['max_quarter_pct']*100:.1f}%  (flag if > 60%)")

    # ── [C5] Long vs Short ────────────────────────────────────────────────────
    print(f"\n  [C5] LONG vs SHORT SPLIT")
    lp = grp_c["long_pnl"];  sp = grp_c["short_pnl"]
    print(f"  Long:  ${lp:>+10,.0f}  ({lp/total_pnl*100:.1f}% of total)" if total_pnl else
          f"  Long:  ${lp:>+10,.0f}")
    print(f"  Short: ${sp:>+10,.0f}  ({sp/total_pnl*100:.1f}% of total)" if total_pnl else
          f"  Short: ${sp:>+10,.0f}")


# ══ Main ════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vault missing-metrics analyser — read-only, no engine re-run"
    )
    parser.add_argument("--snapshot",    type=str,   default=None,
                        help="Snapshot .pkl (default: latest in snapshots/)")
    parser.add_argument("--spy-parquet", type=str,   default=DEFAULT_SPY_PQ,
                        help="SPY daily parquet in cache")
    parser.add_argument("--spy-csv",     type=str,   default=None,
                        help="Fallback SPY CSV if parquet not found")
    parser.add_argument("--capital",     type=float, default=50_000.0,
                        help="Starting account capital in $ (default: 50,000)")
    args = parser.parse_args()

    # ── 1. Locate & load snapshot ────────────────────────────────────────────
    snap = args.snapshot or find_latest_snap(DEFAULT_SNAP_DIR)
    if not snap or not os.path.exists(snap):
        print(f"ERROR: no snapshot found in {DEFAULT_SNAP_DIR}")
        print("  Pass --snapshot <path.pkl> explicitly.")
        sys.exit(1)

    print(f"\n{SEP}")
    print(f"  VAULT MISSING-METRICS ANALYSER  (read-only)")
    print(SEP)
    print(f"  Snapshot:  {os.path.basename(snap)}")
    print(f"  Capital:   ${args.capital:,.0f}  (assumption: starting account size)")

    results = load_results(snap)
    vault   = find_vault_window(results)
    if vault is None:
        print("ERROR: 2023-2024 window not found in snapshot.")
        sys.exit(1)

    label = vault.get("label", "?")
    print(f"  Window:    {label}")

    # ── 2. Trades ────────────────────────────────────────────────────────────
    trades_df = trades_to_df(vault["trades"])
    trades_df = trades_df[
        (trades_df["exit_time"] >= OOS_START) &
        (trades_df["exit_time"] <= OOS_END + pd.Timedelta("1D"))
    ].copy().reset_index(drop=True)

    if trades_df.empty:
        print("\nERROR: No 2023-2024 closed trades found.")
        print("  This snapshot may be an IS run (2017-2022), not the vault run.")
        print("  Pass --snapshot <path-to-vault-result.pkl> explicitly.")
        sys.exit(1)

    equity_curve = vault.get("equity_curve", pd.Series(dtype=float))
    metrics_raw  = vault.get("metrics", {})

    print(f"  Trades:    {len(trades_df)}"
          f"  ({trades_df['exit_time'].min().date()} → {trades_df['exit_time'].max().date()})")

    # ── 3. SPY ───────────────────────────────────────────────────────────────
    spy_df = load_spy_daily(args.spy_parquet, args.spy_csv)
    if spy_df is None:
        print(f"\n  WARNING: SPY parquet not found at:\n    {args.spy_parquet}")
        print(f"  Pass --spy-csv <path> to supply SPY data.")
        print(f"  Group A metrics (R², Beta, down-months) will be skipped.")
    else:
        print(f"  SPY cache: {spy_df.index.min().date()} → {spy_df.index.max().date()}")

    capital = args.capital

    # ── 4. Build return series ───────────────────────────────────────────────
    raits_daily = build_raits_daily(equity_curve)
    if raits_daily.empty:
        print("  INFO: Equity curve outside OOS window — using trade P&L / capital fallback.")
        raits_daily = build_raits_daily_from_trades(trades_df, capital)

    raits_monthly_pnl, raits_monthly_ret = build_raits_monthly(trades_df, capital)

    if spy_df is not None:
        spy_daily_ret   = build_spy_daily(spy_df)
        spy_monthly_ret = build_spy_monthly(spy_df)
    else:
        spy_daily_ret = spy_monthly_ret = None

    # ── 5. Known vault metrics (fall back to reported values if not in pkl) ──
    vault_known = dict(
        calmar    = metrics_raw.get("calmar_ratio",  1.04),
        sharpe    = metrics_raw.get("sharpe_ratio",  0.88),
        pf        = metrics_raw.get("profit_factor", 1.18),
        max_dd    = metrics_raw.get("max_drawdown",  -0.069),
        win_rate  = metrics_raw.get("win_rate",      0.484),
        total_ret = metrics_raw.get("total_return",  0.148),
    )

    print(f"\n  Known vault metrics (from run report):")
    print(f"    Calmar={vault_known['calmar']:.2f}  Sharpe={vault_known['sharpe']:.2f}  "
          f"MaxDD={vault_known['max_dd']*100:.1f}%  PF={vault_known['pf']:.2f}  "
          f"WR={vault_known['win_rate']*100:.1f}%  TotalRet={vault_known['total_ret']*100:.1f}%  "
          f"Trades={len(trades_df)}")

    # ── 6. Compute all groups ────────────────────────────────────────────────
    if spy_df is not None and not raits_daily.empty and not spy_daily_ret.empty:
        grp_a = compute_group_a(
            raits_daily, spy_daily_ret,
            raits_monthly_pnl, raits_monthly_ret, spy_monthly_ret,
        )
    else:
        grp_a = _empty_group_a()

    grp_b = compute_group_b(raits_daily, trades_df, equity_curve, capital)
    grp_c = compute_group_c(trades_df)

    # ── 7. Print three-tier output ───────────────────────────────────────────
    print_gate(vault_known, grp_a, grp_b, grp_c)
    print_tier(vault_known, grp_b)
    print_diagnostic(grp_a, grp_b, grp_c, trades_df, capital)

    print(f"\n{SEP}")
    print(f"  Analysis complete.")
    print(SEP)


if __name__ == "__main__":
    main()
