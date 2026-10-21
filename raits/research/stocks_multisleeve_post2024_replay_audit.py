from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def yearly_stats(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (account, year), group in events.groupby(["account", events["effective_date"].dt.year]):
        group = group.sort_values(["effective_date", "clock"])
        start_equity = float(group.iloc[0]["equity"] - group.iloc[0]["event_pnl"])
        equity = np.r_[start_equity, group["equity"].to_numpy(dtype=float)]
        peaks = np.maximum.accumulate(equity)
        rows.append({
            "account": account,
            "year": int(year),
            "start_equity": start_equity,
            "end_equity": float(equity[-1]),
            "pnl": float(group["event_pnl"].sum()),
            "return": float(equity[-1] / start_equity - 1.0),
            "dd_dollar_year_reset": float((equity - peaks).min()),
            "dd_pct_year_reset": float((equity / peaks - 1.0).min()),
            "sessions": int(group["effective_date"].nunique()),
            "status_at_year_end": str(group.iloc[-1]["status"]),
        })
    return pd.DataFrame(rows)


def sleeve_stats(ticker_pnl: pd.DataFrame) -> pd.DataFrame:
    frame = ticker_pnl.copy()
    frame["year"] = frame["effective_date"].dt.year
    frame["sleeve"] = np.where(frame["ticker"].eq("SPY"), "spy_first5", "sic_pairs")
    return (frame.groupby(["account", "year", "sleeve"], as_index=False)
        .agg(mark_pnl=("mark_pnl", "sum"), slippage_cost=("slippage_cost", "sum"),
             borrow_cost=("borrow_cost", "sum"), financing_cost=("financing_cost", "sum"),
             net_pnl=("net_pnl", "sum")))


def concentration_stats(ticker_pnl: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for account, group in ticker_pnl.groupby("account"):
        by = group.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        positive = by[by > 0]
        positive_total = float(positive.sum())
        net_total = float(by.sum())
        gross_abs = float(by.abs().sum())
        row: dict[str, object] = {
            "account": account,
            "net_pnl": net_total,
            "positive_pnl": positive_total,
            "negative_pnl": float(by[by < 0].sum()),
            "gross_absolute_pnl": gross_abs,
            "profitable_tickers": int((by > 0).sum()),
            "losing_tickers": int((by < 0).sum()),
            "effective_ticker_count_positive": (
                float(positive_total**2 / positive.pow(2).sum()) if positive_total > 0 else 0.0
            ),
            "top_ticker": str(by.index[0]) if len(by) else "",
        }
        for count in (1, 3, 5, 10):
            top = float(positive.head(count).sum())
            row[f"top{count}_share_positive_pnl"] = top / positive_total if positive_total > 0 else np.nan
            row[f"top{count}_share_net_pnl"] = top / net_total if net_total > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def operational_stats(orders: pd.DataFrame, issues: pd.DataFrame) -> pd.DataFrame:
    order_counts = orders.groupby(["account", "status", "reason"], dropna=False).size().rename("count").reset_index()
    issue_counts = issues.groupby(["account", "issue_type", "reason"], dropna=False).size().rename("count").reset_index()
    order_counts.insert(1, "record_type", "order")
    order_counts = order_counts.rename(columns={"status": "classification"})
    issue_counts.insert(1, "record_type", "issue")
    issue_counts = issue_counts.rename(columns={"issue_type": "classification"})
    return pd.concat([
        order_counts[["account", "record_type", "classification", "reason", "count"]],
        issue_counts[["account", "record_type", "classification", "reason", "count"]],
    ], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the touched post-2024 multi-sleeve implementation replay.")
    parser.add_argument("--input-prefix", default="STOCKS_MULTISLEEVE_POST2024_IMPLEMENTATION_REPLAY")
    parser.add_argument("--output-prefix", default="STOCKS_MULTISLEEVE_POST2024_IMPLEMENTATION_REPLAY_AUDIT")
    args = parser.parse_args()

    source = Path(args.input_prefix)
    output = Path(args.output_prefix)
    paths = {
        "events": Path(f"{source}_ACCOUNT_EVENTS.csv"),
        "ticker_pnl": Path(f"{source}_TICKER_PNL.csv"),
        "orders": Path(f"{source}_ORDERS.csv"),
        "issues": Path(f"{source}_ISSUES.csv"),
    }
    events = pd.read_csv(paths["events"], parse_dates=["effective_date"])
    ticker_pnl = pd.read_csv(paths["ticker_pnl"], parse_dates=["effective_date"])
    orders = pd.read_csv(paths["orders"])
    issues = pd.read_csv(paths["issues"])

    outputs = {
        "yearly": Path(f"{output}_YEARLY.csv"),
        "sleeves": Path(f"{output}_SLEEVES.csv"),
        "concentration": Path(f"{output}_CONCENTRATION.csv"),
        "operations": Path(f"{output}_OPERATIONS.csv"),
    }
    yearly_stats(events).to_csv(outputs["yearly"], index=False)
    sleeve_stats(ticker_pnl).to_csv(outputs["sleeves"], index=False)
    concentration_stats(ticker_pnl).to_csv(outputs["concentration"], index=False)
    operational_stats(orders, issues).to_csv(outputs["operations"], index=False)

    script = Path(__file__).resolve()
    manifest = {
        "script": str(script).replace("\\", "/"),
        "scriptHash": sha256(script),
        "classification": "Touched implementation replay audit; not clean OOS and not forward paper PnL.",
        "definitions": {
            "yearlyDrawdown": "Peak-to-trough within each calendar year after resetting the peak to year-start equity.",
            "positiveShare": "Top positive ticker contributions divided by total positive ticker PnL; bounded to [0, 1].",
            "netShare": "Top positive ticker contributions divided by net account PnL; may exceed 1 when losses offset winners.",
            "effectiveTickerCount": "Inverse HHI over positive ticker PnL contributions.",
            "sleeveMapping": "SPY is spy_first5; every non-SPY ticker is sic_pairs.",
        },
        "inputs": {name: {"path": str(path), "sha256": sha256(path)} for name, path in paths.items()},
        "outputs": {name: {"path": str(path), "sha256": sha256(path)} for name, path in outputs.items()},
    }
    Path(f"{output}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(yearly_stats(events).to_string(index=False))
    print(concentration_stats(ticker_pnl).to_string(index=False))


if __name__ == "__main__":
    main()
