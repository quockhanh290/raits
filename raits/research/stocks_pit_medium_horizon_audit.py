from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = Path("STOCKS_PIT_MEDIUM_HORIZON_2026-10-03")
SCRIPT = Path("raits/research/stocks_pit_medium_horizon_replay.py")
PREREG = Path("STOCKS_PIT_MEDIUM_HORIZON_PREREG_2026-10-03.json")
VARIANTS = {
    "weekly_sector_momo20",
    "weekly_sector_momo60",
    "weekly_sector_reversal20",
    "weekly_consistent_lowvol_momo",
    "monthly_sector_blend_momo",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    development = pd.read_csv(f"{PREFIX}_DEVELOPMENT.csv")
    validation_path = Path(f"{PREFIX}_VALIDATION.csv")
    validation = pd.DataFrame() if validation_path.stat().st_size <= 2 else pd.read_csv(validation_path)
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date", "planned_exit_date"])
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    contrib = pd.read_csv(f"{PREFIX}_TICKER_CONTRIB.csv")
    qa = pd.read_csv(f"{PREFIX}_QA.csv")

    check(sha256(SCRIPT) == prereg["script_hash"] == manifest["scriptHash"], "script hash mismatch")
    check(sha256(PREREG) == manifest["preregistrationHash"], "prereg hash mismatch")
    for path, expected in manifest["inputs"].items():
        check(sha256(Path(path)) == expected, f"input hash mismatch: {path}")

    check(set(development["variant"]) == VARIANTS and len(development) == 5, "frozen family mismatch")
    check(not development["developmentPass"].astype(bool).any(), "unexpected development passer")
    check(selection["status"] == "KILL_NO_DEVELOPMENT_PASS", "selection status mismatch")
    check(not selection["validationOpened"], "validation unexpectedly opened")
    check(validation.empty, "validation artifact must remain empty")
    check(trades["scope"].eq("development").all(), "non-development trades present")
    check(trades["planned_exit_date"].max() <= pd.Timestamp("2021-12-31"), "locked period consumed")

    check(trades["sector_count"].ge(10).all(), "sector breadth violation")
    check(trades["target_weight"].eq(0.05).all(), "weight violation")
    check(trades["direction"].isin([-1, 1]).all(), "direction violation")
    check((trades.loc[trades["variant"].eq("weekly_sector_momo20"), "direction"] ==
           np.sign(trades.loc[trades["variant"].eq("weekly_sector_momo20"), "resid20"])).all(), "momo20 direction")
    check((trades.loc[trades["variant"].eq("weekly_sector_momo60"), "direction"] ==
           np.sign(trades.loc[trades["variant"].eq("weekly_sector_momo60"), "resid60"])).all(), "momo60 direction")
    check((trades.loc[trades["variant"].eq("weekly_sector_reversal20"), "direction"] ==
           -np.sign(trades.loc[trades["variant"].eq("weekly_sector_reversal20"), "resid20"])).all(), "reversal direction")
    consistent = trades[trades["variant"].isin(["weekly_consistent_lowvol_momo", "monthly_sector_blend_momo"])]
    check((consistent["direction"] == np.sign(consistent["resid20"])).all(), "blend direction")
    check((np.sign(consistent["resid20"]) == np.sign(consistent["resid60"])).all(), "blend consistency")

    cohort = trades.groupby(["variant", "date"])
    check((cohort.size() <= 10).all(), "cohort leg cap violation")
    check(cohort["direction"].sum().eq(0).all(), "unmatched sides")
    check(trades.groupby(["variant", "date", "direction", "sic_description"]).size().le(1).all(), "SIC cap violation")
    check((trades["planned_exit_date"] > trades["date"]).all(), "non-positive holding period")
    for variant, group in trades.groupby("variant"):
        dates = sorted(group["date"].unique())
        exits = sorted(group["planned_exit_date"].unique())
        check(set(exits[:-1]).issubset(set(dates[1:])), f"non-overlap schedule mismatch: {variant}")
    bad_exit = trades["unreplayable_exit"].astype(bool)
    check(trades.loc[bad_exit, "raw_return"].eq(-1.0).all(), "missing-exit writeoff mismatch")

    target_gross = trades.groupby(["variant", "date"])["target_weight"].sum()
    check(target_gross.le(0.5000001).all(), "entry target gross cap violation")
    check(daily["max_order_adv_fraction"].le(0.0100001).all(), "ADV cap violation")
    check((daily["dd_dollar"] <= 1e-8).all() and (daily["dd_pct"] <= 1e-8).all(), "drawdown sign violation")
    check(qa["dailyMinusEnding"].abs().max() < 1e-6, "daily/equity reconciliation")
    check(qa["dailyMinusContrib"].abs().max() < 1e-6, "daily/contribution reconciliation")

    for row in development.itertuples(index=False):
        d = daily[(daily["variant"] == row.variant) & daily["cost_bps"].eq(4.0)]
        c = contrib[(contrib["variant"] == row.variant) & contrib["cost_bps"].eq(4.0)]
        check(abs(d["daily_pnl"].sum() - row.pnl) < 1e-6, f"summary PnL mismatch: {row.variant}")
        by_ticker = c.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        positive = by_ticker[by_ticker > 0]
        for n, field in [(1, "top1PositiveShare"), (3, "top3PositiveShare"), (5, "top5PositiveShare"), (10, "top10PositiveShare")]:
            expected = positive.head(n).sum() / positive.sum() if positive.sum() else np.nan
            check(abs(expected - getattr(row, field)) < 1e-10, f"concentration mismatch: {row.variant}/{n}")

    result = {
        "status": "PASS",
        "checks": 28,
        "validationOpened": False,
        "maxPerformanceDate": str(trades["planned_exit_date"].max().date()),
        "maxMarkedGross": float(daily["gross"].max()),
        "scriptHash": sha256(SCRIPT),
    }
    Path(f"{PREFIX}_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
