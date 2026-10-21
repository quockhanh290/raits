from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_SYSTEMATIC_FEATURE_HORIZON_2026-10-03"
SCRIPT = Path("raits/research/stocks_systematic_feature_horizon_map.py")
PREREG = Path("STOCKS_SYSTEMATIC_FEATURE_HORIZON_PREREG_2026-10-03.json")
DEPENDENCIES = [
    Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl"),
    Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"),
    Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"),
    Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_tape_features_pre1000.parquet"),
    Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv"),
    Path("STOCKS_PIT_1000_FLOW_EXACT_CLOCK_ROWS_2026-10-02.csv"),
    Path("raits/data/cache/external_equity_context/polygon_2018_2024/manifest.json"),
    Path("raits/data/cache/external_equity_context/polygon_2018_2024/status.csv"),
    Path("raits/data/cache/external_events/polygon_2018_2024/manifest.json"),
    Path("raits/data/cache/external_events/polygon_2018_2024/status.csv"),
]
MIN_EDGE = {"intraday": 0.0010, "overnight": 0.0010, "d1": 0.0015, "d5": 0.0040, "d20": 0.0080}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def bh_qvalues(pvalues: pd.Series) -> np.ndarray:
    order = np.argsort(pvalues.to_numpy())
    ranked = pvalues.to_numpy()[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    result = np.empty(len(ranked)); result[order] = np.minimum(adjusted, 1.0)
    return result


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    results = pd.read_csv(f"{PREFIX}_DISCOVERY_REPLICATION.csv")
    confirmation_path = Path(f"{PREFIX}_CONFIRMATION.csv")

    check(sha256(SCRIPT) == prereg["script_hash"] == manifest["scriptHash"], "script hash mismatch")
    check(sha256(PREREG) == manifest["preregistrationHash"], "prereg hash mismatch")
    check(len(results) == 180, "frozen cell count mismatch")
    check(not results.duplicated(["context", "feature", "horizon"]).any(), "duplicate cells")
    check(set(results["context"]) == {"tape_yday", "tape_gap", "short_interest", "news", "edgar"}, "family mismatch")
    check(np.allclose(results["q"], bh_qvalues(results["p"]), atol=1e-12), "BH q mismatch")
    discovery = (results["q"].le(0.10) & results["spread"].abs().ge(results["horizon"].map(MIN_EDGE))
                 & results["dates"].ge(60) & results["topObs"].ge(400) & results["bottomObs"].ge(400))
    direction = np.sign(results["spread"])
    replication = (discovery & (direction * results["rep_spread"]).gt(0)
                   & (direction * results["rep_t"]).ge(1.0)
                   & results["rep_spread"].abs().ge(results["spread"].abs() * 0.25)
                   & results["rep_dates"].ge(20) & results["rep_topObs"].ge(100)
                   & results["rep_bottomObs"].ge(100))
    check((discovery == results["discoveryPass"].astype(bool)).all(), "discovery gate mismatch")
    check((replication == results["replicationPass"].astype(bool)).all(), "replication gate mismatch")
    check(int(discovery.sum()) == selection["discoveryPasses"] == 4, "discovery pass count")
    check(int(replication.sum()) == selection["replicationPasses"] == 0, "replication pass count")
    check(not selection["confirmationOpened"] and selection["confirmationPasses"] == 0, "confirmation gate")
    check(confirmation_path.stat().st_size <= 2, "confirmation artifact must be empty")
    check(not selection["productionPassAllowed"], "production pass unexpectedly allowed")
    check(manifest["post2022Consumed"] is False and manifest["oldManual62Used"] is False, "boundary/provenance flag")
    dependency_hashes = {str(path).replace("\\", "/"): sha256(path) for path in DEPENDENCIES}
    payload = {
        "status": "PASS", "checks": 16, "tests": len(results), "discoveryPasses": int(discovery.sum()),
        "replicationPasses": int(replication.sum()), "confirmationOpened": False,
        "scriptHash": sha256(SCRIPT), "preregistrationHash": sha256(PREREG),
        "dependencies": dependency_hashes, "post2022PerformanceConsumed": False,
    }
    Path(f"{PREFIX}_AUDIT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
