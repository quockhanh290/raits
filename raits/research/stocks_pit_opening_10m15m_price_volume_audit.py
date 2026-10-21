from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_OPENING_10M15M_PRICE_VOLUME_2026-10-01"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    paths = {name: Path(f"{PREFIX}_{suffix}") for name, suffix in {
        "development": "DEVELOPMENT.csv", "daily": "DAILY.csv", "trades": "TRADES.csv",
        "contrib": "TICKER_CONTRIB.csv", "yearly": "YEARLY.csv", "qa": "QA.csv",
        "coverage": "COVERAGE.csv", "inventory": "RAW_FILE_INVENTORY.csv",
        "exact": "EXACT_CLOCK_ROWS.csv", "selection": "SELECTION.json", "manifest": "MANIFEST.json",
    }.items()}
    daily = pd.read_csv(paths["daily"], parse_dates=["date"])
    trades = pd.read_csv(paths["trades"], parse_dates=["date"])
    contrib = pd.read_csv(paths["contrib"], parse_dates=["date"])
    qa = pd.read_csv(paths["qa"])
    selection = json.loads(paths["selection"].read_text(encoding="ascii"))

    base = daily[daily["cost_bps"].eq(4.0)].copy()
    yearly_rows = []
    for (variant, year), group in base.groupby(["variant", base["date"].dt.year]):
        group = group.sort_values("date")
        start_equity = float(group.iloc[0]["equity"] - group.iloc[0]["daily_pnl"])
        equity = np.r_[start_equity, group["equity"].to_numpy(float)]
        peaks = np.maximum.accumulate(equity)
        yearly_rows.append({"variant": variant, "year": int(year), "pnl": float(group["daily_pnl"].sum()),
            "gross_pnl": float(group["gross_pnl"].sum()), "trading_cost": float(group["trading_cost"].sum()),
            "borrow_cost": float(group["borrow_cost"].sum()), "return": float(equity[-1] / start_equity - 1.0),
            "dd_dollar_year_reset": float((equity - peaks).min()), "dd_pct_year_reset": float((equity / peaks - 1.0).min()),
            "active_days": int(group["trade_legs"].gt(0).sum()), "trade_legs": int(group["trade_legs"].sum())})
    yearly = pd.DataFrame(yearly_rows)

    concentration_rows = []
    base_contrib = contrib[contrib["cost_bps"].eq(4.0)]
    for variant, group in base_contrib.groupby("variant"):
        by = group.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        positive = by[by > 0]; positive_total = float(positive.sum()); net = float(by.sum())
        row: dict[str, object] = {"variant": variant, "net_pnl": net, "positive_pnl": positive_total,
            "negative_pnl": float(by[by < 0].sum()), "top_ticker": by.index[0] if len(by) else "",
            "effective_positive_ticker_count": float(positive_total**2 / positive.pow(2).sum()) if positive_total > 0 else 0.0}
        for count in (1, 3, 5, 10):
            top = float(positive.head(count).sum())
            row[f"top{count}_positive_share"] = top / positive_total if positive_total > 0 else np.nan
            row[f"top{count}_net_share"] = top / net if net > 0 else np.nan
        concentration_rows.append(row)
    concentration = pd.DataFrame(concentration_rows)

    execution = trades.groupby("variant", as_index=False).agg(trade_legs=("ticker", "size"),
        active_days=("date", "nunique"), fallback_exit_legs=("exit_delay_minutes", lambda x: int(x.gt(0).sum())),
        max_exit_delay_minutes=("exit_delay_minutes", "max"), max_target_abs_weight=("target_weight", lambda x: float(x.abs().max())),
        max_initial_adv_fraction=("adv20", lambda x: float((10_000.0 / x).max())))

    qa_error = float(qa[["dailyMinusEnding", "dailyMinusContrib"]].abs().to_numpy().max())
    assert qa_error < 1e-8
    assert daily["date"].max() <= pd.Timestamp("2022-12-30")
    assert trades["date"].max() <= pd.Timestamp("2022-12-30")
    assert contrib["date"].max() <= pd.Timestamp("2022-12-30")
    assert selection["validationOpened"] is False
    assert float(base["max_order_adv_fraction"].max()) <= 0.01 + 1e-12
    assert float(execution["max_target_abs_weight"].max()) <= 0.10 + 1e-12

    outputs = {
        "yearly": Path(f"{PREFIX}_AUDIT_YEARLY.csv"),
        "concentration": Path(f"{PREFIX}_AUDIT_CONCENTRATION.csv"),
        "execution": Path(f"{PREFIX}_AUDIT_EXECUTION.csv"),
    }
    yearly.to_csv(outputs["yearly"], index=False)
    concentration.to_csv(outputs["concentration"], index=False)
    execution.to_csv(outputs["execution"], index=False)
    script = Path(__file__).resolve()
    audit_manifest = {
        "script": str(script).replace("\\", "/"), "scriptHash": sha256(script),
        "classification": "Post-result audit only; it does not select or change a rule.",
        "boundary": {"maxDailyDate": str(daily["date"].max().date()), "maxTradeDate": str(trades["date"].max().date()),
            "validationOpened": selection["validationOpened"], "post2024Consumed": False},
        "checks": {"maxLedgerReconciliationError": qa_error, "maxOrderAdvFraction": float(base["max_order_adv_fraction"].max()),
            "maxTargetAbsWeight": float(execution["max_target_abs_weight"].max()), "maxExitDelayMinutes": float(execution["max_exit_delay_minutes"].max())},
        "inputs": {name: {"path": str(path), "sha256": sha256(path)} for name, path in paths.items()},
        "outputs": {name: {"path": str(path), "sha256": sha256(path)} for name, path in outputs.items()},
        "invalidRunPreserved": "STOCKS_PIT_OPENING_10M15M_PRICE_VOLUME_2026-10-01_INVALID_EXIT_AVAILABILITY_LOOKAHEAD_*",
    }
    Path(f"{PREFIX}_AUDIT_MANIFEST.json").write_text(json.dumps(audit_manifest, indent=2) + "\n", encoding="ascii")
    print(yearly.to_string(index=False))
    print(execution.to_string(index=False))
    print(json.dumps(audit_manifest["checks"], indent=2))


if __name__ == "__main__":
    main()
