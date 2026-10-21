from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_MULTIVARIATE_INTERACTION_2026-10-03"
SCRIPT = Path("raits/research/stocks_pit_multivariate_interaction_map.py")
PREREG = Path("STOCKS_PIT_MULTIVARIATE_INTERACTION_PREREG_2026-10-03.json")
DEPENDENCIES = [
    Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl"),
    Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"),
    Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"),
    Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_tape_features_pre1000.parquet"),
    Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv"),
    Path("STOCKS_PIT_1000_FLOW_EXACT_CLOCK_ROWS_2026-10-02.csv"),
    Path("raits/data/cache/external_equity_context/polygon_2018_2024/manifest.json"),
    Path("raits/data/cache/external_events/polygon_2018_2024/manifest.json"),
]
MIN_NET_EDGE = {"d5": 0.0040, "d20": 0.0080}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def normal_pvalue(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0)) if np.isfinite(t_value) else 1.0


def bh_qvalues(pvalues: pd.Series) -> np.ndarray:
    values = pvalues.to_numpy(dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    result = np.empty(len(values)); result[order] = np.minimum(adjusted, 1.0)
    return result


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    summary = json.loads(Path(f"{PREFIX}_SUMMARY.json").read_text(encoding="ascii"))
    selection = pd.read_csv(f"{PREFIX}_SELECTION.csv")
    daily = pd.read_csv(f"{PREFIX}_DAILY_SPREADS.csv", parse_dates=["date"])
    confirmation = Path(f"{PREFIX}_CONFIRMATION.csv")

    check(sha256(SCRIPT) == prereg["script_hash"] == manifest["scriptHash"], "script hash mismatch")
    check(sha256(PREREG) == manifest["preregistrationHash"], "preregistration hash mismatch")
    check(len(selection) == 8 and selection["candidate"].nunique() == 8, "candidate count mismatch")
    check(set(daily["stage"]) == {"development_oof"}, "non-development stage was opened")
    check(set(daily["date"].dt.year) == {2019, 2020}, "development year boundary mismatch")
    check(np.allclose(daily["gross_spread"] - daily["net_spread"], 0.0016, atol=1e-12), "cost proxy mismatch")
    check((daily["top_obs"] == daily["bottom_obs"]).all(), "cohort sides are not matched")

    recomputed = []
    yearly = {}
    for candidate, group in daily.groupby("candidate", sort=False):
        mean = float(group["net_spread"].mean())
        std = float(group["net_spread"].std())
        t_value = mean / std * math.sqrt(len(group)) if std > 0 else np.nan
        recomputed.append({
            "candidate": candidate, "grossSpreadAudit": float(group["gross_spread"].mean()),
            "netSpreadAudit": mean, "tNetAudit": t_value, "pAudit": normal_pvalue(t_value),
            "datesAudit": len(group), "topObsAudit": int(group["top_obs"].sum()),
            "bottomObsAudit": int(group["bottom_obs"].sum()),
        })
        yearly[candidate] = group.groupby(group["date"].dt.year)["net_spread"].mean().to_dict()
    audit = pd.DataFrame(recomputed)
    joined = selection.merge(audit, on="candidate", validate="one_to_one")
    for column in ("grossSpread", "netSpread", "tNet", "p"):
        check(np.allclose(joined[column], joined[f"{column}Audit"], atol=1e-12), f"{column} mismatch")
    for column in ("dates", "topObs", "bottomObs"):
        check((joined[column] == joined[f"{column}Audit"]).all(), f"{column} mismatch")
    check(np.allclose(selection["q"], bh_qvalues(selection["p"]), atol=1e-12), "BH q mismatch")
    development = (
        selection["q"].le(0.10) & selection["netSpread"].ge(selection["horizon"].map(MIN_NET_EDGE))
        & selection["tNet"].ge(2.0) & selection["dates"].ge(80)
        & selection["topObs"].ge(400) & selection["bottomObs"].ge(400)
        & selection["candidate"].map(lambda value: yearly[value][2019]).gt(0)
        & selection["candidate"].map(lambda value: yearly[value][2020]).gt(0)
    )
    check((development == selection["developmentPass"].astype(bool)).all(), "development gate mismatch")
    check(int(development.sum()) == summary["developmentPasses"] == 0, "development pass count")
    check(int(selection["replicationPass"].sum()) == summary["replicationPasses"] == 0, "replication pass count")
    check(not summary["confirmationOpened"] and summary["confirmationPasses"] == 0, "confirmation gate")
    check(confirmation.stat().st_size <= 2, "confirmation artifact must be empty")
    check(not summary["productionPassAllowed"], "production pass unexpectedly allowed")
    check(manifest["oldManual62Used"] is False and manifest["post2021PerformanceConsumed"] is False, "boundary flag")

    payload = {
        "status": "PASS", "checks": 18, "candidates": len(selection),
        "developmentPasses": int(development.sum()), "replicationPasses": 0,
        "confirmationOpened": False, "developmentYears": [2019, 2020],
        "scriptHash": sha256(SCRIPT), "preregistrationHash": sha256(PREREG),
        "dependencies": {str(path).replace("\\", "/"): sha256(path) for path in DEPENDENCIES},
        "post2021PerformanceConsumed": False,
    }
    Path(f"{PREFIX}_AUDIT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
