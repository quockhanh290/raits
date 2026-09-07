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


def load_price_frame(data_dir: Path, inst: str) -> pd.DataFrame:
    path = data_dir / INST_TO_PARQUET[inst]
    df = pd.read_parquet(path)
    df.columns = [str(c).lower() for c in df.columns]
    idx = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York").tz_localize(None)
    out = pd.DataFrame(
        {
            "open": df["open"].to_numpy(),
            "high": df["high"].to_numpy(),
            "low": df["low"].to_numpy(),
            "close": df["close"].to_numpy(),
        },
        index=idx,
    )
    return out.sort_index()


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
    trades["exit_price"] = pd.to_numeric(trades["exit"], errors="coerce")

    data_dir = Path(args.data_dir)
    checked = outside_bar = outside_day = missing_time = 0
    worst: list[dict] = []

    for inst, group in trades.groupby("inst"):
        prices = load_price_frame(data_dir, inst)
        day_low = prices["low"].groupby(prices.index.normalize()).min()
        day_high = prices["high"].groupby(prices.index.normalize()).max()

        for row in group.itertuples(index=False):
            ts = row.exit_time_et
            px = row.exit_price
            if pd.isna(ts) or pd.isna(px):
                continue

            day = pd.Timestamp(ts).normalize()
            if ts not in prices.index:
                missing_time += 1
                bar_low = bar_high = None
            else:
                bar = prices.loc[ts]
                bar_low = float(bar["low"])
                bar_high = float(bar["high"])

            dl = day_low.get(day)
            dh = day_high.get(day)
            if pd.isna(dl) or pd.isna(dh):
                continue

            checked += 1
            out_bar = (
                bar_low is not None
                and (float(px) < bar_low - 1e-9 or float(px) > bar_high + 1e-9)
            )
            out_day = float(px) < float(dl) - 1e-9 or float(px) > float(dh) + 1e-9

            outside_bar += int(out_bar)
            outside_day += int(out_day)

            if out_day:
                point_gap = float(dl) - float(px) if float(px) < float(dl) else float(px) - float(dh)
                worst.append(
                    {
                        "inst": inst,
                        "entry_day": row.day,
                        "exit_day": str(day.date()),
                        "direction": row.direction,
                        "exit_time": str(ts),
                        "exit_price": float(px),
                        "day_low": float(dl),
                        "day_high": float(dh),
                        "point_gap": point_gap,
                    }
                )

    worst.sort(key=lambda r: r["point_gap"], reverse=True)

    print(f"trades_file={args.trades}")
    print(f"price_dir={args.data_dir}")
    print(f"checked_trades={checked}")
    print(f"exit_time_missing_from_1m_index={missing_time}")
    print(f"outside_exit_bar={outside_bar} ({outside_bar / checked:.2%})")
    print(f"outside_exit_day={outside_day} ({outside_day / checked:.2%})")
    print()
    print(f"top_{args.top}_outside_day_by_point_gap:")
    for r in worst[: args.top]:
        print(
            "{inst} entry={entry_day} exit_day={exit_day} {direction} "
            "exit_time={exit_time} exit={exit_price:.2f} "
            "day_range={day_low:.2f}-{day_high:.2f} gap_points={point_gap:.2f}".format(**r)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
