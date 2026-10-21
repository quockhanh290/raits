"""Reproducible clean retest for the stock YDAY panic/rebound WFO candidate.

This script addresses the measurement issues raised in
STOCKS_CLAUDE_AUDIT_WFO_CANDIDATE_2026-09-08.md:

* candidate rules are evaluated from a declared pool, without OOS filtering;
* WFO chooses rules using train years only;
* rules that require today's open/gap enter at 09:35, not at the open;
* half-days without a 15:55 bar are handled by an explicit policy;
* PE/earnings is optional and off by default because the current calendar is
  filing-date based, not announcement-date based.

The goal is not to optimize P&L. The goal is to make the measurement auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


START_CAPITAL = 50_000.0
DEFAULT_COST_BPS = 4.0
DEFAULT_TEST_YEARS = (2020, 2021, 2022, 2023, 2024)
MAX_INTRADAY_ADJ_PRICE_RATIO = 2.0
ETF_TICKERS = {
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLE",
    "XLK",
    "XLF",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLB",
    "XLU",
    "XLRE",
    "XLC",
}


@dataclass(frozen=True)
class Rule:
    name: str
    yday_threshold: float
    top_n: int
    gap_mode: str = "any"
    spy_mode: str = "any"
    mom20_mode: str = "any"

    @property
    def needs_open_confirmation(self) -> bool:
        return self.gap_mode != "any"


DECLARED_RULE_POOL = (
    Rule("raw_-4", -0.04, 3),
    Rule("raw_-5", -0.05, 3),
    Rule("raw_-6", -0.06, 3),
    Rule("raw_-7", -0.07, 3),
    Rule("gapdown_-4", -0.04, 3, gap_mode="gapdown"),
    Rule("gapdown_-5", -0.05, 3, gap_mode="gapdown"),
    Rule("gapdown_-6", -0.06, 3, gap_mode="gapdown"),
    Rule("gapdown_-7", -0.07, 3, gap_mode="gapdown"),
    Rule("nodeep_-7_spyBD", -0.07, 3, gap_mode="no_deep_gap", spy_mode="spy_bigdown"),
    Rule("panic_-7_spyBD", -0.07, 3, spy_mode="spy_bigdown"),
    Rule("panic_-7_spyBD_momneg", -0.07, 3, spy_mode="spy_bigdown", mom20_mode="mom20_neg"),
    Rule("quality_-5_gapdown_mompos", -0.05, 3, gap_mode="gapdown", mom20_mode="mom20_pos"),
)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bar_at(day: pd.DataFrame, hhmm: str, field: str) -> float:
    rows = day.between_time(hhmm, hhmm)
    if rows.empty:
        return math.nan
    return float(rows.iloc[0][field])


def max_intraday_adj_price_ratio(day: pd.DataFrame) -> float:
    opens = day["open"].astype(float).to_numpy()
    closes = day["close"].astype(float).to_numpy()
    if len(closes) < 2:
        return math.nan
    prev_close = closes[:-1]
    curr_close = closes[1:]
    curr_open = opens[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.column_stack(
            [
                curr_close / prev_close,
                prev_close / curr_close,
                curr_open / prev_close,
                prev_close / curr_open,
            ]
        )
    ratios[~np.isfinite(ratios)] = np.nan
    if np.isnan(ratios).all():
        return math.nan
    return float(np.nanmax(ratios))


def build_daily_table(
    bars: dict[str, pd.DataFrame],
    half_day_policy: str,
    *,
    skip_etfs: bool = True,
    add_spy_feature: bool = True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict[str, object]] = []
    counters = {
        "raw_tickers": len(bars),
        "skipped_etfs": 0,
        "skipped_no_1555": 0,
        "used_last_bar_exit": 0,
    }

    for ticker, frame in bars.items():
        if skip_etfs and ticker in ETF_TICKERS:
            counters["skipped_etfs"] += 1
            continue
        df = frame.sort_index()
        for date_value, day in df.groupby(df.index.date):
            open_0930 = bar_at(day, "09:30", "open")
            close_0930 = bar_at(day, "09:30", "close")
            open_0935 = bar_at(day, "09:35", "open")
            close_1555 = bar_at(day, "15:55", "close")
            max_adj_price_ratio = max_intraday_adj_price_ratio(day)
            if math.isnan(close_1555):
                if half_day_policy == "skip":
                    counters["skipped_no_1555"] += 1
                    continue
                close_1555 = float(day.iloc[-1]["close"])
                counters["used_last_bar_exit"] += 1
            if math.isnan(open_0930) or math.isnan(close_0930) or math.isnan(open_0935):
                continue
            rows.append(
                {
                    "date": pd.Timestamp(date_value),
                    "ticker": ticker,
                    "open_0930": open_0930,
                    "close_0930": close_0930,
                    "open_0935": open_0935,
                    "close_1555": close_1555,
                    "max_adj_price_ratio": max_adj_price_ratio,
                    "volume_0930": float(day.between_time("09:30", "09:30").iloc[0].get("volume", math.nan)),
                }
            )

    daily = pd.DataFrame(rows).sort_values(["ticker", "date"])
    daily["prev_open_0930"] = daily.groupby("ticker")["open_0930"].shift(1)
    daily["prev_close_1555"] = daily.groupby("ticker")["close_1555"].shift(1)
    daily["prev_dayret"] = daily["prev_close_1555"] / daily["prev_open_0930"] - 1.0
    daily["gap"] = daily["open_0930"] / daily["prev_close_1555"] - 1.0
    daily["ret_open_to_1555"] = daily["close_1555"] / daily["open_0930"] - 1.0
    daily["ret_0935_to_1555"] = daily["close_1555"] / daily["open_0935"] - 1.0
    daily["ret20_pre"] = daily.groupby("ticker")["prev_close_1555"].transform(lambda s: s / s.shift(20) - 1.0)
    daily["year"] = daily["date"].dt.year

    daily = daily.replace([np.inf, -np.inf], np.nan)
    daily = daily.dropna(
        subset=[
            "open_0930",
            "open_0935",
            "close_1555",
            "prev_open_0930",
            "prev_close_1555",
            "prev_dayret",
            "gap",
            "ret20_pre",
            "max_adj_price_ratio",
        ]
    )
    daily = daily[
        (daily["open_0930"] > 3.0)
        & (daily["open_0935"] > 3.0)
        & (daily["close_1555"] > 3.0)
        & (daily["prev_open_0930"] > 3.0)
        & (daily["prev_close_1555"] > 3.0)
        & (daily["gap"].abs() <= 0.30)
        & (daily["max_adj_price_ratio"] <= MAX_INTRADAY_ADJ_PRICE_RATIO)
        & (daily["prev_dayret"].abs() <= 0.50)
    ].copy()

    if add_spy_feature and "SPY" in bars:
        spy_daily, _ = build_daily_table(
            {"SPY": bars["SPY"]},
            half_day_policy,
            skip_etfs=False,
            add_spy_feature=False,
        )
        spy = spy_daily[["date", "prev_dayret"]].rename(columns={"prev_dayret": "spy_prev_dayret"})
        daily = daily.merge(spy, on="date", how="left")
        daily = daily.dropna(subset=["spy_prev_dayret"])
    else:
        daily["spy_prev_dayret"] = math.nan

    return daily, counters


def load_earnings_pairs(path: Path | None) -> set[tuple[str, pd.Timestamp]]:
    if path is None:
        return set()
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {(ticker, pd.Timestamp(date_value)) for ticker, dates in raw.items() for date_value in dates}


def apply_rule(daily: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    df = daily[daily["prev_dayret"] <= rule.yday_threshold].copy()
    if rule.gap_mode == "gapdown":
        df = df[df["gap"] < 0.0]
    elif rule.gap_mode == "no_deep_gap":
        df = df[df["gap"] >= -0.02]
    elif rule.gap_mode != "any":
        raise ValueError(f"unknown gap_mode: {rule.gap_mode}")

    if rule.spy_mode == "spy_bigdown":
        df = df[df["spy_prev_dayret"] <= -0.01]
    elif rule.spy_mode != "any":
        raise ValueError(f"unknown spy_mode: {rule.spy_mode}")

    if rule.mom20_mode == "mom20_pos":
        df = df[df["ret20_pre"] > 0.0]
    elif rule.mom20_mode == "mom20_neg":
        df = df[df["ret20_pre"] <= 0.0]
    elif rule.mom20_mode != "any":
        raise ValueError(f"unknown mom20_mode: {rule.mom20_mode}")

    entry_ret_col = "ret_0935_to_1555" if rule.needs_open_confirmation else "ret_open_to_1555"
    result = (
        df.sort_values(["date", "prev_dayret"])
        .groupby("date", group_keys=False)
        .head(rule.top_n)
        .copy()
    )
    result["rule"] = rule.name
    result["sleeve"] = "YDAY"
    result["gross_ret"] = result[entry_ret_col]
    result["entry_time"] = "09:35" if rule.needs_open_confirmation else "09:30_MOO"
    result["score"] = result["prev_dayret"]
    return result[
        [
            "date",
            "year",
            "ticker",
            "rule",
            "sleeve",
            "gross_ret",
            "entry_time",
            "score",
            "volume_0930",
        ]
    ]


def build_pe_signals(daily: pd.DataFrame, earnings_pairs: set[tuple[str, pd.Timestamp]]) -> pd.DataFrame:
    if not earnings_pairs:
        return pd.DataFrame(
            columns=["date", "year", "ticker", "rule", "sleeve", "gross_ret", "entry_time", "score", "volume_0930"]
        )
    rows = daily[[("ticker"), ("date")]].apply(tuple, axis=1)
    df = daily[rows.isin(earnings_pairs) & (daily["gap"] <= -0.05)].copy()
    result = df.sort_values(["date", "gap"]).groupby("date", group_keys=False).head(2).copy()
    result["rule"] = "PE_FILING_GAPDOWN_0935"
    result["sleeve"] = "PE_FILING_WARN"
    result["gross_ret"] = -result["ret_0935_to_1555"]
    result["entry_time"] = "09:35"
    result["score"] = result["gap"]
    return result[
        [
            "date",
            "year",
            "ticker",
            "rule",
            "sleeve",
            "gross_ret",
            "entry_time",
            "score",
            "volume_0930",
        ]
    ]


def simulate(
    signals: pd.DataFrame,
    years: Iterable[int],
    *,
    start_capital: float,
    position_pct: float,
    max_positions: int,
    cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = signals[signals["year"].isin(set(years))].copy()
    if selected.empty:
        return pd.DataFrame(), pd.DataFrame()

    equity = start_capital
    trades: list[dict[str, object]] = []
    curve: list[dict[str, object]] = []
    cost = cost_bps / 10_000.0
    for date_value, day in selected.groupby("date", sort=True):
        clean = []
        seen = set()
        # Prefer YDAY over PE on same ticker/day, then most severe signal.
        for _, signal in day.sort_values(["sleeve", "score"], ascending=[False, True]).iterrows():
            if signal["ticker"] in seen:
                continue
            seen.add(signal["ticker"])
            clean.append(signal)

        day_pnl = 0.0
        for signal in clean[:max_positions]:
            pnl = equity * position_pct * (float(signal["gross_ret"]) - cost)
            day_pnl += pnl
            trades.append(
                {
                    "date": date_value,
                    "year": int(signal["year"]),
                    "ticker": signal["ticker"],
                    "rule": signal["rule"],
                    "sleeve": signal["sleeve"],
                    "entry_time": signal["entry_time"],
                    "gross_ret": float(signal["gross_ret"]),
                    "pnl": pnl,
                    "equity_before": equity,
                }
            )
        equity += day_pnl
        curve.append(
            {
                "date": date_value,
                "equity": equity,
                "day_pnl": day_pnl,
                "positions": len(clean[:max_positions]),
            }
        )
    return pd.DataFrame(trades), pd.DataFrame(curve)


def metrics(trades: pd.DataFrame, curve: pd.DataFrame, start_capital: float) -> dict[str, float]:
    if trades.empty or curve.empty:
        return {
            "N": 0,
            "days": 0,
            "pnl": 0.0,
            "pf": math.nan,
            "wr": math.nan,
            "dd": 0.0,
            "cagr": 0.0,
            "ending_equity": start_capital,
        }
    gross_profit = float(trades.loc[trades["pnl"] > 0, "pnl"].sum())
    gross_loss = float(-trades.loc[trades["pnl"] < 0, "pnl"].sum())
    equity = curve["equity"].to_numpy()
    drawdown = float((equity - np.maximum.accumulate(equity)).min())
    years = (pd.Timestamp(curve["date"].iloc[-1]) - pd.Timestamp(curve["date"].iloc[0])).days / 365.25
    cagr = (float(curve["equity"].iloc[-1]) / start_capital) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    return {
        "N": float(len(trades)),
        "days": float(trades["date"].nunique()),
        "pnl": float(trades["pnl"].sum()),
        "pf": gross_profit / gross_loss if gross_loss else math.inf,
        "wr": float((trades["pnl"] > 0).mean()),
        "dd": drawdown,
        "cagr": cagr,
        "ending_equity": float(curve["equity"].iloc[-1]),
    }


def train_score(m: dict[str, float]) -> float:
    """Fixed WFO selection score.

    This is deliberately simple and documented. It favors robust PF, then P&L,
    and penalizes deep drawdown and tiny samples.
    """
    if m["N"] < 35 or not math.isfinite(m["pf"]) or m["pf"] < 1.2:
        return -1e9
    return (
        m["pnl"] / 10_000.0
        + 8.0 * math.log(m["pf"])
        + min(m["N"], 200.0) / 200.0
        - abs(m["dd"]) / 20_000.0
    )


def run_wfo(
    signal_by_rule: dict[str, pd.DataFrame],
    pe_signals: pd.DataFrame,
    *,
    mode: str,
    test_years: tuple[int, ...],
    include_pe: bool,
    start_capital: float,
    position_pct: float,
    max_positions: int,
    cost_bps: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    choices = []
    test_trades = []
    test_curves = []
    equity = start_capital

    for year in test_years:
        train_years = range(max(2017, year - 3), year) if mode == "rolling3" else range(2017, year)
        best = None
        for rule_name, yday_signals in signal_by_rule.items():
            train_signals = pd.concat([yday_signals, pe_signals], ignore_index=True) if include_pe else yday_signals
            tr, cu = simulate(
                train_signals,
                train_years,
                start_capital=start_capital,
                position_pct=position_pct,
                max_positions=max_positions,
                cost_bps=cost_bps,
            )
            m = metrics(tr, cu, start_capital)
            score = train_score(m)
            if best is None or score > best[0]:
                best = (score, rule_name, m)

        assert best is not None
        rule_name = best[1]
        test_signals = (
            pd.concat([signal_by_rule[rule_name], pe_signals], ignore_index=True)
            if include_pe
            else signal_by_rule[rule_name]
        )
        tr, cu = simulate(
            test_signals,
            [year],
            start_capital=equity,
            position_pct=position_pct,
            max_positions=max_positions,
            cost_bps=cost_bps,
        )
        if not cu.empty:
            equity = float(cu["equity"].iloc[-1])
        test_m = metrics(tr, cu, equity if cu.empty else float(cu["equity"].iloc[0] - cu["day_pnl"].iloc[0]))
        choices.append(
            {
                "year": year,
                "mode": mode,
                "chosen_rule": rule_name,
                "train_score": best[0],
                "train_pnl": best[2]["pnl"],
                "train_pf": best[2]["pf"],
                "train_N": best[2]["N"],
                "test_pnl": test_m["pnl"],
                "test_pf": test_m["pf"],
                "test_N": test_m["N"],
            }
        )
        test_trades.append(tr)
        test_curves.append(cu)

    all_trades = pd.concat(test_trades, ignore_index=True) if test_trades else pd.DataFrame()
    all_curve = pd.concat(test_curves, ignore_index=True) if test_curves else pd.DataFrame()
    return pd.DataFrame(choices), all_trades, all_curve


def fmt_money(value: float) -> str:
    return f"${value:,.0f}"


def fmt_metric(m: dict[str, float]) -> str:
    return (
        f"N={int(m['N'])} days={int(m['days'])} pnl={fmt_money(m['pnl'])} "
        f"pf={m['pf']:.2f} wr={m['wr']:.1%} dd={fmt_money(m['dd'])} "
        f"cagr={m['cagr']:.1%} end={fmt_money(m['ending_equity'])}"
    )


def write_markdown(
    path: Path,
    *,
    args: argparse.Namespace,
    data_hash: str,
    counters: dict[str, int],
    daily: pd.DataFrame,
    clean_results: list[dict[str, object]],
) -> None:
    lines = [
        "# Clean retest: YDAY panic/rebound WFO",
        "",
        "This report is generated by `raits/research/stocks_wfo_clean_retest.py`.",
        "",
        "## Configuration",
        "",
        f"- 5-min cache: `{args.bars}`",
        f"- cache sha256: `{data_hash}`",
        f"- half-day policy: `{args.half_day_policy}`",
        f"- include PE filing-date sleeve: `{args.include_pe}`",
        f"- cost bps roundtrip: `{args.cost_bps}`",
        f"- position pct: `{args.position_pct}`",
        f"- max positions/day: `{args.max_positions}`",
        f"- daily rows after filters: `{len(daily):,}`",
        f"- tickers after filters: `{daily['ticker'].nunique()}`",
        f"- skipped no-15:55 ticker-days: `{counters['skipped_no_1555']:,}`",
        "",
        "## Results",
        "",
        "| Mode | N | P&L | PF | WR | DD | CAGR | Ending equity |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in clean_results:
        m = row["metrics"]
        lines.append(
            f"| {row['label']} | {int(m['N'])} | `{fmt_money(m['pnl'])}` | "
            f"{m['pf']:.2f} | {m['wr']:.1%} | `{fmt_money(m['dd'])}` | "
            f"{m['cagr']:.1%} | `{fmt_money(m['ending_equity'])}` |"
        )
    lines.extend(["", "## WFO Choices", ""])
    for row in clean_results:
        choices = row["choices"]
        lines.append(f"### {row['label']}")
        lines.append("")
        lines.append("| Year | Chosen rule | Train N | Train P&L | Train PF | Test N | Test P&L | Test PF |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|")
        for _, choice in choices.iterrows():
            lines.append(
                f"| {int(choice['year'])} | `{choice['chosen_rule']}` | "
                f"{int(choice['train_N'])} | `{fmt_money(choice['train_pnl'])}` | "
                f"{choice['train_pf']:.2f} | {int(choice['test_N'])} | "
                f"`{fmt_money(choice['test_pnl'])}` | {choice['test_pf']:.2f} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", default="raits/data/cache/window_debug_5min.pkl")
    parser.add_argument("--earnings", default="raits/data/cache/earnings_dates_expanded.json")
    parser.add_argument("--include-pe", action="store_true", help="Include PE filing-date sleeve, WARN only.")
    parser.add_argument("--half-day-policy", choices=("skip", "last_bar"), default="skip")
    parser.add_argument("--position-pct", type=float, default=0.40)
    parser.add_argument("--max-positions", type=int, default=3)
    parser.add_argument("--cost-bps", type=float, default=DEFAULT_COST_BPS)
    parser.add_argument("--output-md", default="STOCKS_WFO_CLEAN_RETEST_2026-09-08.md")
    parser.add_argument("--trades-csv", default="STOCKS_WFO_CLEAN_RETEST_TRADES_2026-09-08.csv")
    args = parser.parse_args()

    bars_path = Path(args.bars)
    with bars_path.open("rb") as f:
        bars = pickle.load(f)
    data_hash = file_sha256(bars_path)
    daily, counters = build_daily_table(bars, args.half_day_policy)

    earnings_pairs = load_earnings_pairs(Path(args.earnings)) if args.include_pe else set()
    pe_signals = build_pe_signals(daily, earnings_pairs)
    signal_by_rule = {rule.name: apply_rule(daily, rule) for rule in DECLARED_RULE_POOL}

    results = []
    all_trade_outputs = []
    for mode in ("anchored", "rolling3"):
        choices, trades, curve = run_wfo(
            signal_by_rule,
            pe_signals,
            mode=mode,
            test_years=DEFAULT_TEST_YEARS,
            include_pe=args.include_pe,
            start_capital=START_CAPITAL,
            position_pct=args.position_pct,
            max_positions=args.max_positions,
            cost_bps=args.cost_bps,
        )
        m = metrics(trades, curve, START_CAPITAL)
        label = f"{mode}{'_with_pe_filing_WARN' if args.include_pe else '_yday_only'}"
        results.append({"label": label, "choices": choices, "trades": trades, "curve": curve, "metrics": m})
        if not trades.empty:
            t = trades.copy()
            t["wfo_mode"] = mode
            all_trade_outputs.append(t)

    print("CONFIG")
    print(f"bars={args.bars}")
    print(f"bars_sha256={data_hash}")
    print(f"half_day_policy={args.half_day_policy}")
    print(f"include_pe_filing_warn={args.include_pe}")
    print(f"position_pct={args.position_pct} max_positions={args.max_positions} cost_bps={args.cost_bps}")
    print(f"daily_rows={len(daily)} tickers={daily['ticker'].nunique()} counters={counters}")
    print()
    for row in results:
        print(row["label"], fmt_metric(row["metrics"]))
        print(row["choices"].to_string(index=False))
        print()

    output_md = Path(args.output_md)
    write_markdown(
        output_md,
        args=args,
        data_hash=data_hash,
        counters=counters,
        daily=daily,
        clean_results=results,
    )
    if all_trade_outputs:
        pd.concat(all_trade_outputs, ignore_index=True).to_csv(args.trades_csv, index=False)
    print(f"wrote {output_md}")
    print(f"wrote {args.trades_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
