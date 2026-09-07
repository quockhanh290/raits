from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


INST_TO_PARQUET = {
    "MES": "ES_continuous_1m_8y.parquet",
    "MNQ": "NQ_continuous_1m_8y.parquet",
    "MYM": "YM_continuous_1m_8y.parquet",
    "M2K": "RTY_continuous_1m_8y.parquet",
}

POINT_VALUE = {
    "MES": 5.0,
    "MNQ": 2.0,
    "MYM": 0.5,
    "M2K": 5.0,
}


def load_prices(data_dir: Path, inst: str) -> pd.DataFrame:
    df = pd.read_parquet(data_dir / INST_TO_PARQUET[inst])
    df.columns = [str(c).lower() for c in df.columns]
    idx = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York").tz_localize(None)
    prices = pd.DataFrame(
        {
            "open": df["open"].to_numpy(),
            "high": df["high"].to_numpy(),
            "low": df["low"].to_numpy(),
            "close": df["close"].to_numpy(),
        },
        index=idx,
    )
    return prices.sort_index()


def profit_factor(pnls: pd.Series) -> float:
    wins = float(pnls[pnls > 0].sum())
    losses = float(-pnls[pnls < 0].sum())
    return wins / losses if losses else float("inf")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades", default="scratch/calm_probe_prod_backtest.csv")
    parser.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()

    trades = pd.read_csv(args.trades)
    trades["exit_time_et"] = (
        pd.to_datetime(trades["exit_time"], utc=True, errors="coerce")
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)
    )
    trades["exit_day_dt"] = pd.to_datetime(trades["exit_day"], errors="coerce")
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce")
    trades["exit"] = pd.to_numeric(trades["exit"], errors="coerce")
    trades["corrected_exit"] = trades["exit"]
    trades["correction_dollars"] = 0.0
    trades["corrected_pnl"] = trades["pnl"]

    corrections: list[dict] = []
    missing = 0

    for inst, idxs in trades.groupby("inst").groups.items():
        prices = load_prices(Path(args.data_dir), inst)
        pv = POINT_VALUE[inst]

        for i in idxs:
            row = trades.loc[i]
            if row["reason"] != "CHANDELIER" or pd.isna(row["exit_time_et"]) or pd.isna(row["exit"]):
                continue
            ts = row["exit_time_et"]
            if ts not in prices.index:
                missing += 1
                continue

            bar_open = float(prices.loc[ts, "open"])
            stop_price = float(row["exit"])
            direction = row["direction"]

            if direction == "LONG" and bar_open < stop_price:
                corrected_exit = bar_open
                delta_points = corrected_exit - stop_price
            elif direction == "SHORT" and bar_open > stop_price:
                corrected_exit = bar_open
                delta_points = stop_price - corrected_exit
            else:
                continue

            delta_dollars = delta_points * pv
            corrected_pnl = float(row["pnl"]) + delta_dollars
            trades.at[i, "corrected_exit"] = corrected_exit
            trades.at[i, "correction_dollars"] = delta_dollars
            trades.at[i, "corrected_pnl"] = corrected_pnl
            corrections.append(
                {
                    "inst": inst,
                    "entry_day": row["day"],
                    "exit_day": row["exit_day"],
                    "direction": direction,
                    "exit_time": str(ts),
                    "old_exit": stop_price,
                    "bar_open": bar_open,
                    "delta": delta_dollars,
                    "old_pnl": float(row["pnl"]),
                    "new_pnl": corrected_pnl,
                }
            )

    total_old = float(trades["pnl"].sum())
    total_new = float(trades["corrected_pnl"].sum())
    total_delta = float(trades["correction_dollars"].sum())

    print(f"trades_file={args.trades}")
    print(f"price_dir={args.data_dir}")
    print(f"trades={len(trades)}")
    print(f"missing_exit_bars={missing}")
    print(f"corrected_trades={len(corrections)} ({len(corrections) / len(trades):.2%})")
    print(f"old_total_pnl=${total_old:,.2f}")
    print(f"correction=${total_delta:,.2f}")
    print(f"corrected_total_pnl=${total_new:,.2f}")
    print(f"old_profit_factor={profit_factor(trades['pnl']):.3f}")
    print(f"corrected_profit_factor={profit_factor(trades['corrected_pnl']):.3f}")

    print()
    print("by_inst:")
    by_inst = trades.groupby("inst").agg(
        trades=("pnl", "size"),
        corrected=("correction_dollars", lambda s: int((s != 0).sum())),
        old_pnl=("pnl", "sum"),
        correction=("correction_dollars", "sum"),
        corrected_pnl=("corrected_pnl", "sum"),
    )
    for inst, r in by_inst.iterrows():
        print(
            f"  {inst}: n={int(r['trades'])} corrected={int(r['corrected'])} "
            f"old=${r['old_pnl']:,.2f} correction=${r['correction']:,.2f} "
            f"new=${r['corrected_pnl']:,.2f}"
        )

    print()
    print("by_exit_year:")
    trades["exit_year"] = trades["exit_day_dt"].dt.year
    by_year = trades.groupby("exit_year").agg(
        trades=("pnl", "size"),
        corrected=("correction_dollars", lambda s: int((s != 0).sum())),
        old_pnl=("pnl", "sum"),
        correction=("correction_dollars", "sum"),
        corrected_pnl=("corrected_pnl", "sum"),
    )
    for year, r in by_year.iterrows():
        print(
            f"  {int(year)}: n={int(r['trades'])} corrected={int(r['corrected'])} "
            f"old=${r['old_pnl']:,.2f} correction=${r['correction']:,.2f} "
            f"new=${r['corrected_pnl']:,.2f}"
        )

    print()
    print(f"top_{args.top}_largest_adverse_corrections:")
    corrections.sort(key=lambda r: r["delta"])
    for r in corrections[: args.top]:
        print(
            "{inst} entry={entry_day} exit_day={exit_day} {direction} "
            "exit_time={exit_time} old_exit={old_exit:.2f} bar_open={bar_open:.2f} "
            "delta=${delta:,.2f} old_pnl=${old_pnl:,.2f} new_pnl=${new_pnl:,.2f}".format(**r)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
