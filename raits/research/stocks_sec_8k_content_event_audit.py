from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


DISC_PREFIX = "STOCKS_SEC_8K_CONTENT_EVENT_2026-10-03"
REP_PREFIX = "STOCKS_SEC_8K_CONTENT_EVENT_REPLICATION_2026-10-03"
PREREG = Path("STOCKS_SEC_8K_CONTENT_EVENT_PREREG_2026-10-03.json")
FREEZE = Path("STOCKS_SEC_8K_CONTENT_EVENT_REPLICATION_FROZEN_2026-10-03.json")
FETCH = Path("raits/research/stocks_sec_8k_content_fetch.py")
CLASSIFY = Path("raits/research/stocks_sec_8k_content_classify.py")
DISC_SCRIPT = Path("raits/research/stocks_sec_8k_content_event_map.py")
REP_SCRIPT = Path("raits/research/stocks_sec_8k_content_event_replication.py")
CACHE = Path("raits/data/cache/external_events/sec_8k_content_2018_2021")
CLASSES = ["buyback_authorization", "workforce_reduction", "going_concern_distress",
           "financial_restatement", "cyber_incident", "strategic_alternatives"]
HORIZONS = ["d1", "d5", "d20"]
MIN_EDGE = {"d1": 0.0015, "d5": 0.0040, "d20": 0.0080}


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


def bh_qvalues(values: pd.Series) -> np.ndarray:
    p = values.to_numpy(dtype=float); order = np.argsort(p); ranked = p[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    result = np.empty(len(p)); result[order] = np.minimum(adjusted, 1.0)
    return result


def stats(values: pd.Series) -> tuple[float, float, float, int]:
    x = values.replace([np.inf, -np.inf], np.nan).dropna()
    std = float(x.std()); mean = float(x.mean()) if len(x) else np.nan
    t = mean / std * math.sqrt(len(x)) if len(x) > 1 and std > 0 else np.nan
    return mean, t, normal_pvalue(t), len(x)


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    freeze = json.loads(FREEZE.read_text(encoding="ascii"))
    disc_manifest = json.loads(Path(f"{DISC_PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    rep_manifest = json.loads(Path(f"{REP_PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    disc_class = json.loads((CACHE / "classification_manifest_discovery.json").read_text(encoding="ascii"))
    rep_class = json.loads((CACHE / "classification_manifest_replication.json").read_text(encoding="ascii"))
    disc = pd.read_csv(f"{DISC_PREFIX}_DISCOVERY.csv")
    yearly = pd.read_csv(f"{DISC_PREFIX}_YEARLY.csv")
    events = pd.read_csv(f"{DISC_PREFIX}_EVENTS.csv", parse_dates=["entry_date"])
    rep = pd.read_csv(f"{REP_PREFIX}_RESULT.csv")
    rep_events = pd.read_csv(f"{REP_PREFIX}_EVENTS.csv", parse_dates=["entry_date"])

    check(prereg["fetch_script_hash"] == sha256(FETCH), "fetch script hash")
    check(prereg["classification_script_hash"] == sha256(CLASSIFY), "classifier hash")
    check(prereg["performance_script_hash"] == sha256(DISC_SCRIPT) == disc_manifest["scriptHash"], "discovery script hash")
    check(freeze["scriptHash"] == sha256(REP_SCRIPT) == rep_manifest["scriptHash"], "replication script hash")
    check(len(disc) == 18 and not disc.duplicated(["eventClass", "horizon"]).any(), "18-cell family")
    check(set(disc["eventClass"]) == set(CLASSES) and set(disc["horizon"]) == set(HORIZONS), "family members")
    check(disc_class["plannedAccessions"] == 18892 and disc_class["fetchedAccessions"] == 18827
          and disc_class["explicitFailures"] == 65 and disc_class["unresolvedAccessions"] == 0, "discovery coverage")
    check(rep_class["plannedAccessions"] == 6006 and rep_class["fetchedAccessions"] == 5985
          and rep_class["explicitFailures"] == 21 and rep_class["unresolvedAccessions"] == 0, "replication coverage")
    check(events["entry_date"].dt.year.isin([2018, 2019, 2020]).all(), "discovery dates")
    check(rep_events["entry_date"].dt.year.eq(2021).all(), "replication dates")

    recalculated = []
    for event_class in CLASSES:
        subset = events[events["event_class"].eq(event_class)]
        for horizon in HORIZONS:
            mean, t, p, count = stats(subset[f"resid_{horizon}"])
            annual = {year: stats(subset.loc[subset["entry_date"].dt.year.eq(year), f"resid_{horizon}"])
                      for year in (2018, 2019, 2020)}
            sign = int(np.sign(mean))
            agreeing = sum(int(np.sign(annual[year][0]) == sign) for year in annual)
            min_events = min(annual[year][3] for year in annual)
            recalculated.append({"eventClass": event_class, "horizon": horizon, "mean": mean, "tAudit": t,
                                 "pAudit": p, "eventsAudit": count, "agreeingAudit": agreeing,
                                 "minYearAudit": min_events})
    audit = pd.DataFrame(recalculated)
    joined = disc.merge(audit, on=["eventClass", "horizon"], validate="one_to_one")
    check(np.allclose(joined["meanResidual"], joined["mean"], atol=1e-12), "discovery mean")
    check(np.allclose(joined["t"], joined["tAudit"], atol=1e-12), "discovery t")
    check(np.allclose(joined["p"], joined["pAudit"], atol=1e-12), "discovery p")
    check((joined["events"] == joined["eventsAudit"]).all(), "discovery event count")
    check((joined["agreeingYears"] == joined["agreeingAudit"]).all(), "year sign count")
    check((joined["minYearEvents"] == joined["minYearAudit"]).all(), "year breadth")
    check(np.allclose(disc["q"], bh_qvalues(disc["p"]), atol=1e-12), "BH q")
    coverage = disc["events"].ge(80) & disc["minYearEvents"].ge(15) & disc["agreeingYears"].ge(2)
    development = coverage & disc["q"].le(0.10) & disc["t"].abs().ge(2.0) & disc["meanResidual"].abs().ge(disc["horizon"].map(MIN_EDGE))
    check((coverage == disc["coveragePass"].astype(bool)).all(), "coverage gate")
    check((development == disc["developmentPass"].astype(bool)).all() and int(development.sum()) == 1, "development gate")
    selected = disc[development].iloc[0]
    check(selected["eventClass"] == "buyback_authorization" and selected["horizon"] == "d1" and selected["direction"] == 1, "selected cell")

    mean, t, _, count = stats(rep_events["resid_d1"])
    check(np.isclose(mean, rep.iloc[0]["meanResidual"], atol=1e-12) and np.isclose(t, rep.iloc[0]["t"], atol=1e-12), "replication stats")
    rep_pass = count >= 20 and mean > 0 and t >= 1.0 and abs(mean) >= abs(float(selected["meanResidual"])) * 0.25
    check(not rep_pass and not bool(rep.iloc[0]["replicationPass"]), "replication must fail")
    check(disc_manifest["post2020PerformanceConsumed"] is False and rep_manifest["post2021PerformanceConsumed"] is False, "later boundary")

    payload = {
        "status": "PASS", "checks": 24, "discoveryCells": 18, "developmentPasses": 1,
        "replicationCells": 1, "replicationPasses": 0,
        "discoveryCoverage": {"planned": 18892, "fetched": 18827, "explicitFailures": 65},
        "replicationCoverage": {"planned": 6006, "fetched": 5985, "explicitFailures": 21},
        "scriptHashes": {"fetch": sha256(FETCH), "classify": sha256(CLASSIFY),
                         "discovery": sha256(DISC_SCRIPT), "replication": sha256(REP_SCRIPT)},
        "preregistrationHash": sha256(PREREG), "replicationFreezeHash": sha256(FREEZE),
        "post2021PerformanceConsumed": False,
    }
    Path(f"{DISC_PREFIX}_AUDIT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
