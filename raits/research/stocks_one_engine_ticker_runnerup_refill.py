from __future__ import annotations

from pathlib import Path

import pandas as pd

import stocks_one_engine_mtm_portfolio as engine
import stocks_one_engine_runnerup_refill as refill


OUT = Path("STOCKS_ONE_ENGINE_NO_ML_TICKER_RUNNERUP_REFILL_PRICE_FIXED_2026-09-09.csv")
DETAIL_OUT = Path("STOCKS_ONE_ENGINE_NO_ML_TICKER_RUNNERUP_REFILL_DETAIL_PRICE_FIXED_2026-09-09.csv")


def top_tickers(portfolio: str, n: int) -> list[str]:
    trades = pd.read_csv(engine.TRADES_OUT)
    x = trades[(trades["portfolio"].eq(portfolio)) & trades["pnl"].notna()].copy()
    return x.groupby("ticker")["pnl"].sum().sort_values(ascending=False).head(n).index.astype(str).tolist()


def main() -> None:
    daily_px = engine.load_daily_prices()
    base_signals = engine.load_signals()
    pools = {
        "yday": refill.build_yday_candidates(),
        "broad": refill.build_broad_candidates(),
        "local": refill.build_local_candidates(daily_px),
        "intraday": refill.build_intraday_candidates(),
    }

    rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    for portfolio, cfg in refill.PORTFOLIOS.items():
        summary, _, _ = engine.simulate(f"{portfolio}_base", cfg, base_signals, daily_px)
        rows.append(
            {
                "portfolio": portfolio,
                "mode": "base",
                "excludeTopTickers": 0,
                "excludedTickers": "",
                "removed": 0,
                "replaced": 0,
                **summary,
            }
        )

        for n in [1, 3, 5, 10]:
            excluded = set(top_tickers(portfolio, n))
            sleeve_set = set(cfg["weights"].keys())
            port_signals = base_signals[base_signals["sleeve"].isin(sleeve_set)].copy()
            removed = port_signals[port_signals["ticker"].astype(str).isin(excluded)][["date", "ticker", "sleeve"]].drop_duplicates()
            key = pd.MultiIndex.from_frame(removed)
            sig_key = pd.MultiIndex.from_frame(base_signals[["date", "ticker", "sleeve"]])
            stripped = base_signals.loc[~sig_key.isin(key)].copy()
            for mode in ["none", "yday", "all"]:
                signals = stripped.copy()
                details: list[dict[str, object]] = []
                if mode != "none":
                    repl, details = refill.make_replacements(removed, base_signals, mode, pools, excluded_tickers=excluded)
                    if not repl.empty:
                        signals = pd.concat([signals, repl], ignore_index=True)
                summary, _, _ = engine.simulate(f"{portfolio}_exclude_top{n}_{mode}", cfg, signals, daily_px)
                replaced = sum(1 for d in details if d.get("status") == "replaced")
                rows.append(
                    {
                        "portfolio": portfolio,
                        "mode": mode,
                        "excludeTopTickers": n,
                        "excludedTickers": ",".join(sorted(excluded)),
                        "removed": int(len(removed)),
                        "replaced": int(replaced),
                        **summary,
                    }
                )
                for d in details:
                    d.update(
                        {
                            "portfolio": portfolio,
                            "mode": mode,
                            "excludeTopTickers": n,
                            "excludedTickers": ",".join(sorted(excluded)),
                        }
                    )
                    detail_rows.append(d)
                print(portfolio, n, mode, "removed", len(removed), "replaced", replaced, "pnl", summary["pnl"], flush=True)

    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.DataFrame(detail_rows).to_csv(DETAIL_OUT, index=False)
    print("WROTE", OUT, DETAIL_OUT)


if __name__ == "__main__":
    main()
