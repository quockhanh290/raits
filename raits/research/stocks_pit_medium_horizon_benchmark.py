from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd


INPUT = Path("raits/data/cache/stocks_pit_medium_horizon_2018_2021/spy_0935_open_2018_2021.parquet")
FETCH_MANIFEST = Path("raits/data/cache/stocks_pit_medium_horizon_2018_2021/spy_0935_open_2018_2021_manifest.json")
OUTPUT = Path("STOCKS_PIT_MEDIUM_HORIZON_2026-10-03_BENCHMARK.csv")
MANIFEST = Path("STOCKS_PIT_MEDIUM_HORIZON_2026-10-03_BENCHMARK_MANIFEST.json")
INITIAL_EQUITY = 100_000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    source = json.loads(FETCH_MANIFEST.read_text(encoding="ascii"))
    prices = pd.read_parquet(INPUT).sort_values("date").copy()
    prices["date"] = pd.to_datetime(prices["date"])
    returns = prices["open"].pct_change().fillna(0.0)
    equity = INITIAL_EQUITY * (1.0 + returns).cumprod()
    peak = equity.cummax()
    years = (prices["date"].iloc[-1] - prices["date"].iloc[0]).days / 365.25
    yearly = (1.0 + returns).groupby(prices["date"].dt.year).prod() - 1.0
    rows = [{
        "benchmark": "SPY_0935_price_only_buy_hold",
        "start": prices["date"].iloc[0].date(),
        "end": prices["date"].iloc[-1].date(),
        "rows": len(prices),
        "pnl": equity.iloc[-1] - INITIAL_EQUITY,
        "cagr": (equity.iloc[-1] / INITIAL_EQUITY) ** (1.0 / years) - 1.0,
        "sharpe": returns.mean() / returns.std() * math.sqrt(252.0),
        "ddDollar": (equity - peak).min(),
        "ddPct": (equity / peak - 1.0).min(),
        **{f"return{year}": value for year, value in yearly.items()},
    }]
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT, index=False)
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "scriptHash": sha256(Path(__file__)),
        "input": str(INPUT).replace("\\", "/"),
        "inputHash": sha256(INPUT),
        "fetchManifest": str(FETCH_MANIFEST).replace("\\", "/"),
        "fetchManifestHash": sha256(FETCH_MANIFEST),
        "sourcePost2021Consumed": source["post2021Consumed"],
        "method": "unadjusted SPY price-only buy-and-hold marked at each session's 09:35 five-minute aggregate open; no dividend credit",
        "output": str(OUTPUT),
        "outputHash": sha256(OUTPUT),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(result.to_string(index=False))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
