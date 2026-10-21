from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_FUNDAMENTAL_QUALITY_MONTHLY_2026-09-24"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    paths = {
        "daily": Path(f"{PREFIX}_DAILY.csv"),
        "contrib": Path(f"{PREFIX}_TICKER_CONTRIB.csv"),
        "trades": Path(f"{PREFIX}_TRADES.csv"),
        "factor_panel": Path(f"{PREFIX}_FACTOR_PANEL.csv"),
        "selection": Path(f"{PREFIX}_SELECTION.json"),
    }
    daily = pd.read_csv(paths["daily"], parse_dates=["date"])
    contrib = pd.read_csv(paths["contrib"], parse_dates=["date"])
    trades = pd.read_csv(paths["trades"], parse_dates=["date"])
    factors = pd.read_csv(paths["factor_panel"], parse_dates=["date"])
    qa_rows: list[dict[str, object]] = []
    concentration_rows: list[dict[str, object]] = []
    for (scenario, cost_bps), group in daily.groupby(["scenario", "cost_bps"]):
        group = group.sort_values("date")
        matching = contrib[(contrib["scenario"].eq(scenario)) & (contrib["cost_bps"].eq(cost_bps))]
        ending_delta = float(group.iloc[-1]["equity"] - 100_000.0)
        daily_pnl = float(group["daily_pnl"].sum())
        contrib_pnl = float(matching["pnl"].sum())
        qa_rows.append({"scenario": scenario, "cost_bps": cost_bps, "start": group.iloc[0]["date"],
            "end": group.iloc[-1]["date"], "daily_pnl": daily_pnl, "ending_delta": ending_delta,
            "contrib_pnl": contrib_pnl, "daily_minus_ending": daily_pnl - ending_delta,
            "daily_minus_contrib": daily_pnl - contrib_pnl, "max_missing_marks": int(group["missing_marks"].max())})
        ticker = matching[~matching["ticker"].str.startswith("__")].groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        positive = ticker[ticker > 0]
        positive_total = float(positive.sum())
        row: dict[str, object] = {"scenario": scenario, "cost_bps": cost_bps, "book_net_pnl": daily_pnl,
            "ticker_mark_pnl": float(ticker.sum()), "positive_ticker_pnl": positive_total,
            "negative_ticker_pnl": float(ticker[ticker < 0].sum()), "top_ticker": ticker.index[0] if len(ticker) else "",
            "effective_positive_ticker_count": float(positive_total**2 / positive.pow(2).sum()) if positive_total > 0 else 0.0}
        for count in (1, 3, 5, 10):
            top = float(positive.head(count).sum())
            row[f"top{count}_positive_share"] = top / positive_total if positive_total > 0 else np.nan
            row[f"top{count}_book_net_share"] = top / daily_pnl if daily_pnl > 0 else np.nan
        concentration_rows.append(row)
    qa = pd.DataFrame(qa_rows)
    concentration = pd.DataFrame(concentration_rows)
    qa_path = Path(f"{PREFIX}_QA.csv")
    concentration_path = Path(f"{PREFIX}_AUDITED_CONCENTRATION.csv")
    qa.to_csv(qa_path, index=False)
    concentration.to_csv(concentration_path, index=False)
    script = Path(__file__).resolve()
    manifest = {
        "script": str(script).replace("\\", "/"),
        "scriptHash": sha256(script),
        "classification": "Post-result accounting audit; does not select or modify a strategy.",
        "performanceBoundary": {
            "dailyMaxDate": str(daily["date"].max().date()),
            "contribMaxDate": str(contrib["date"].max().date()),
            "tradesMaxDate": str(trades["date"].max().date()),
            "factorPanelMaxDate": str(factors["date"].max().date()),
            "validationOpened": json.loads(paths["selection"].read_text(encoding="ascii"))["validationOpened"],
        },
        "inputs": {name: {"path": str(path), "sha256": sha256(path)} for name, path in paths.items()},
        "outputs": {
            "qa": {"path": str(qa_path), "sha256": sha256(qa_path)},
            "concentration": {"path": str(concentration_path), "sha256": sha256(concentration_path)},
        },
    }
    Path(f"{PREFIX}_AUDIT_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(qa.to_string(index=False))
    print(concentration[concentration["cost_bps"].eq(4.0)].to_string(index=False))


if __name__ == "__main__":
    main()
