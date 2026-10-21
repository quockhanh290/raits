from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_medium_horizon_replay as medium
import stocks_pit_multivariate_interaction_map as outcome_helpers


PREREG = Path("STOCKS_SEC_8K_CONTENT_EVENT_PREREG_2026-10-03.json")
CACHE = Path("raits/data/cache/external_events/sec_8k_content_2018_2021")
LABELS = CACHE / "labels_discovery.csv"
CLASSIFICATION_MANIFEST = CACHE / "classification_manifest_discovery.json"
PREFIX = "STOCKS_SEC_8K_CONTENT_EVENT_2026-10-03"
CLASSES = [
    "buyback_authorization", "workforce_reduction", "going_concern_distress",
    "financial_restatement", "cyber_incident", "strategic_alternatives",
]
HORIZONS = ["d1", "d5", "d20"]
MIN_EDGE = {"d1": 0.0015, "d5": 0.0040, "d20": 0.0080}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normal_pvalue(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0)) if np.isfinite(t_value) else 1.0


def bh_qvalues(pvalues: pd.Series) -> np.ndarray:
    values = pvalues.to_numpy(dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    result = np.empty(len(values)); result[order] = np.minimum(adjusted, 1.0)
    return result


def assign_sessions(labels: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    accepted = pd.to_datetime(labels["acceptance_datetime"].astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    accepted = accepted.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    cutoffs = pd.DatetimeIndex(
        [date.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15) for date in sessions]
    )
    indices = np.searchsorted(cutoffs.asi8, accepted.astype("int64").to_numpy(), side="right")
    valid = accepted.notna().to_numpy() & (indices < len(sessions))
    output = labels.loc[valid].copy()
    output["accepted_et"] = accepted.loc[valid].astype(str).to_numpy()
    output["entry_date"] = sessions.to_numpy()[indices[valid]]
    return output


def build_panel() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    panel, prices, session_list = medium.load_data()
    sessions = pd.DatetimeIndex(session_list)
    x = panel.rename(columns={"date": "entry_date"}).copy()
    x = outcome_helpers.add_outcome(x, prices, sessions, "d5", "open_0935")
    x = x.rename(columns={"target_date": "target_date_d5", "exit_fallback": "exit_fallback_d5",
                          "exit_writeoff": "exit_writeoff_d5"})
    x = outcome_helpers.add_outcome(x, prices, sessions, "d20", "open_0935")
    x = x.rename(columns={"target_date": "target_date_d20", "exit_fallback": "exit_fallback_d20",
                          "exit_writeoff": "exit_writeoff_d20"})
    x["ret_d1"] = x["close_1555"] / x["open_0935"] - 1.0
    x["exit_fallback_d1"] = False
    x["exit_writeoff_d1"] = x["ret_d1"].isna()
    x.loc[x["exit_writeoff_d1"], "ret_d1"] = -1.0
    for horizon in HORIZONS:
        target = f"ret_{horizon}"
        groups = x.groupby(["entry_date", "sic_description"])[target]
        count = groups.transform("count")
        sector = groups.transform("median")
        market = x.groupby("entry_date")[target].transform("median")
        x[f"control_{horizon}"] = sector.where(count.ge(5), market)
        x[f"resid_{horizon}"] = x[target] - x[f"control_{horizon}"]
    return x, sessions


def summarize(values: pd.Series) -> dict[str, float]:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna()
    std = float(clean.std())
    t_value = float(clean.mean() / std * math.sqrt(len(clean))) if len(clean) > 1 and std > 0 else np.nan
    return {"meanResidual": float(clean.mean()) if len(clean) else np.nan, "t": t_value,
            "p": normal_pvalue(t_value), "events": int(len(clean))}


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if prereg["performance_script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("performance preregistration hash mismatch")
    classification = json.loads(CLASSIFICATION_MANIFEST.read_text(encoding="ascii"))
    if not classification["complete"] if "complete" in classification else classification["unresolvedAccessions"] != 0:
        raise RuntimeError("classification coverage incomplete")
    if classification["labelsHash"] != sha256(LABELS):
        raise RuntimeError("label hash mismatch")

    labels = pd.read_csv(LABELS, dtype={"cik": str, "accession_number": str})
    panel, sessions = build_panel()
    assigned = assign_sessions(labels, sessions)
    long = assigned.melt(
        id_vars=["cik", "ticker", "accession_number", "filing_date", "accepted_et", "entry_date"],
        value_vars=CLASSES, var_name="event_class", value_name="is_event",
    )
    long = long[long["is_event"].astype(bool)].copy()
    long = long.sort_values(["entry_date", "cik", "event_class", "accession_number"])
    long = long.drop_duplicates(["entry_date", "cik", "event_class"], keep="first")
    events = long.merge(panel, on=["entry_date", "ticker"], how="inner", validate="many_to_one")
    events = events[events["entry_date"].between(pd.Timestamp("2018-01-01"), pd.Timestamp("2020-12-31"))].copy()

    rows = []
    yearly_rows = []
    for event_class in CLASSES:
        subset = events[events["event_class"].eq(event_class)]
        for horizon in HORIZONS:
            summary = summarize(subset[f"resid_{horizon}"])
            rows.append({"eventClass": event_class, "horizon": horizon, **summary})
            for year in (2018, 2019, 2020):
                year_values = subset.loc[subset["entry_date"].dt.year.eq(year), f"resid_{horizon}"]
                yearly_rows.append({"eventClass": event_class, "horizon": horizon, "year": year,
                                    **summarize(year_values)})
    results = pd.DataFrame(rows)
    yearly = pd.DataFrame(yearly_rows)
    results["q"] = bh_qvalues(results["p"])
    year_count = yearly.pivot(index=["eventClass", "horizon"], columns="year", values="events")
    year_mean = yearly.pivot(index=["eventClass", "horizon"], columns="year", values="meanResidual")
    keys = pd.MultiIndex.from_frame(results[["eventClass", "horizon"]])
    signs = np.sign(results["meanResidual"].to_numpy())
    agreeing_years = np.zeros(len(results), dtype=int)
    min_year_events = np.zeros(len(results), dtype=int)
    for index, key in enumerate(keys):
        agreeing_years[index] = int((np.sign(year_mean.loc[key, [2018, 2019, 2020]].to_numpy()) == signs[index]).sum())
        min_year_events[index] = int(year_count.loc[key, [2018, 2019, 2020]].min())
    results["agreeingYears"] = agreeing_years
    results["minYearEvents"] = min_year_events
    results["coveragePass"] = results["events"].ge(80) & results["minYearEvents"].ge(15) & results["agreeingYears"].ge(2)
    results["developmentPass"] = (
        results["coveragePass"] & results["q"].le(0.10) & results["t"].abs().ge(2.0)
        & results["meanResidual"].abs().ge(results["horizon"].map(MIN_EDGE))
    )
    results["direction"] = np.sign(results["meanResidual"]).astype(int)

    results.to_csv(f"{PREFIX}_DISCOVERY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    events[["entry_date", "ticker", "cik", "accession_number", "event_class", *[f"resid_{h}" for h in HORIZONS],
            *[f"exit_fallback_{h}" for h in HORIZONS], *[f"exit_writeoff_{h}" for h in HORIZONS]]].to_csv(
        f"{PREFIX}_EVENTS.csv", index=False
    )
    selection = {
        "cells": len(results), "coveragePasses": int(results["coveragePass"].sum()),
        "developmentPasses": int(results["developmentPass"].sum()),
        "replicationContentFetchAllowed": bool(results["developmentPass"].any()),
        "productionPassAllowed": False,
    }
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "labels": str(LABELS).replace("\\", "/"), "labelsHash": sha256(LABELS),
        "classificationManifestHash": sha256(CLASSIFICATION_MANIFEST), "selection": selection,
        "oldManual62Used": False, "post2020PerformanceConsumed": False,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(results.to_string(index=False)); print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
