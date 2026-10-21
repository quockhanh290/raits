from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_ALL_RESULTS_SLEEVE_GRID_PREREG_2026-09-24.json")
BENCHMARK_FILE = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
PREFIX = "STOCKS_ALL_RESULTS_SLEEVE_GRID_2026-09-24"
START_CAPITAL = 100_000.0
DEV_START = pd.Timestamp("2018-04-27")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
VAL_END = pd.Timestamp("2024-12-31")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def metrics(returns: pd.Series) -> dict[str, float | int]:
    returns = returns.fillna(0.0).astype(float)
    equity = START_CAPITAL * (1.0 + returns).cumprod()
    prior = equity.shift(1, fill_value=START_CAPITAL)
    daily_pnl = equity - prior
    peak = pd.concat([pd.Series([START_CAPITAL]), equity.reset_index(drop=True)], ignore_index=True).cummax()
    curve = pd.concat([pd.Series([START_CAPITAL]), equity.reset_index(drop=True)], ignore_index=True)
    years = max((returns.index.max() - returns.index.min()).days / 365.25, 1e-9)
    yearly_returns = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
    return {
        "days": int(len(returns)),
        "pnl": float(equity.iloc[-1] - START_CAPITAL),
        "cagr": float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252))
        if returns.std() > 0
        else float("nan"),
        "ddDollar": float((curve - peak).min()),
        "ddPct": float((curve / peak - 1.0).min()),
        "positiveYears": int(yearly_returns.gt(0).sum()),
        "endingEquity": float(equity.iloc[-1]),
        "dailyPnlSum": float(daily_pnl.sum()),
    }


def daily_return(frame: pd.DataFrame) -> pd.Series:
    pnl = pd.to_numeric(frame["daily_pnl"], errors="coerce")
    equity = pd.to_numeric(frame["equity"], errors="coerce")
    prior = equity - pnl
    result = pnl / prior.replace(0.0, np.nan)
    result.index = pd.to_datetime(frame["date"]).dt.normalize()
    return result.replace([np.inf, -np.inf], np.nan)


def rejection_reason(row: dict[str, object]) -> str:
    reasons = []
    if float(row["coverage"]) < 0.95:
        reasons.append("coverage<95%")
    if float(row["cagr"]) <= 0.0:
        reasons.append("cagr<=0")
    if not np.isfinite(float(row["sharpe"])) or float(row["sharpe"]) < 0.2:
        reasons.append("sharpe<0.2")
    if int(row["positiveYears"]) < 3:
        reasons.append("positiveYears<3")
    if float(row["ddPct"]) < -0.25:
        reasons.append("ddPct<-25%")
    return "|".join(reasons)


def load_sources(
    source_files: list[str], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    rows: list[dict[str, object]] = []
    series: dict[str, pd.Series] = {}
    dev_calendar = calendar[(calendar >= DEV_START) & (calendar <= DEV_END)]
    for source_file in source_files:
        path = Path(source_file)
        frame = pd.read_csv(path)
        if "daily_pnl" not in frame.columns or "equity" not in frame.columns:
            rows.append(
                {
                    "sourceFile": source_file,
                    "scenario": "",
                    "sourceId": f"{source_file}::",
                    "eligible": False,
                    "rejectionReason": "missing_daily_pnl_or_equity",
                }
            )
            continue
        scenario_column = "scenario" if "scenario" in frame.columns else "variant"
        frame[scenario_column] = frame[scenario_column].astype(str)
        for scenario, group in frame.groupby(scenario_column, sort=True):
            source_id = f"{source_file}::{scenario}"
            if scenario.endswith("_cost8"):
                rows.append(
                    {
                        "sourceFile": source_file,
                        "scenario": scenario,
                        "sourceId": source_id,
                        "eligible": False,
                        "rejectionReason": "stress_cost8_excluded",
                    }
                )
                continue
            raw = daily_return(group)
            duplicate_dates = int(raw.index.duplicated().sum())
            if duplicate_dates:
                rows.append(
                    {
                        "sourceFile": source_file,
                        "scenario": scenario,
                        "sourceId": source_id,
                        "eligible": False,
                        "rejectionReason": f"duplicate_dates={duplicate_dates}",
                    }
                )
                continue
            aligned = raw.reindex(calendar)
            coverage = float(aligned.loc[dev_calendar].notna().mean())
            filled = aligned.fillna(0.0)
            dev_metrics = metrics(filled.loc[dev_calendar])
            row = {
                "sourceFile": source_file,
                "scenario": scenario,
                "sourceId": source_id,
                "coverage": coverage,
                **dev_metrics,
            }
            reason = rejection_reason(row)
            row["eligible"] = not reason
            row["rejectionReason"] = reason
            rows.append(row)
            series[source_id] = filled
    return pd.DataFrame(rows), series


def select_representatives(
    catalog: pd.DataFrame, series: dict[str, pd.Series]
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    eligible = catalog[catalog["eligible"].eq(True)].copy()
    eligible = eligible.sort_values(
        ["sourceFile", "sharpe", "cagr", "ddPct", "scenario"],
        ascending=[True, False, False, False, True],
    )
    family = eligible.drop_duplicates("sourceFile", keep="first").copy()
    family = family.sort_values(
        ["sharpe", "cagr", "ddPct", "sourceId"],
        ascending=[False, False, False, True],
    )
    retained: list[str] = []
    decisions = []
    dev_index = series[next(iter(series))].index
    dev_index = dev_index[(dev_index >= DEV_START) & (dev_index <= DEV_END)]
    for row in family.itertuples(index=False):
        source_id = row.sourceId
        max_corr = 0.0
        correlated_to = ""
        for prior in retained:
            corr = float(series[source_id].loc[dev_index].corr(series[prior].loc[dev_index]))
            if abs(corr) > abs(max_corr):
                max_corr = corr
                correlated_to = prior
        keep = len(retained) < 12 and (not retained or abs(max_corr) < 0.97)
        reason = "retained" if keep else ("pool_cap_12" if len(retained) >= 12 else "abs_corr>=0.97")
        decisions.append(
            {
                "sourceId": source_id,
                "sourceFile": row.sourceFile,
                "scenario": row.scenario,
                "developmentSharpe": row.sharpe,
                "developmentCagr": row.cagr,
                "developmentDdPct": row.ddPct,
                "maxAbsCorrelationToRetained": abs(max_corr),
                "correlatedTo": correlated_to,
                "retained": keep,
                "decision": reason,
            }
        )
        if keep:
            retained.append(source_id)
    representative_decisions = pd.DataFrame(decisions)
    retained_returns = pd.DataFrame({source_id: series[source_id].loc[dev_index] for source_id in retained})
    correlation = retained_returns.corr()
    return representative_decisions, correlation, retained


def canonical_weights(ids: list[str], units: tuple[int, ...]) -> str:
    return "|".join(
        f"{ids[index]}={unit / 4:.2f}" for index, unit in enumerate(units) if unit > 0
    )


def run_grid(
    retained: list[str], series: dict[str, pd.Series], calendar: pd.DatetimeIndex
) -> tuple[pd.DataFrame, tuple[int, ...] | None]:
    dev_index = calendar[(calendar >= DEV_START) & (calendar <= DEV_END)]
    matrix = np.column_stack([series[source_id].loc[dev_index].to_numpy() for source_id in retained])
    rows = []
    for picks in itertools.combinations_with_replacement(range(len(retained)), 4):
        units = tuple(picks.count(index) for index in range(len(retained)))
        weights = np.asarray(units, dtype=float) / 4.0
        result = metrics(pd.Series(matrix @ weights, index=dev_index))
        weight_string = canonical_weights(retained, units)
        passed = bool(
            result["cagr"] >= 0.05
            and result["sharpe"] >= 0.6
            and result["positiveYears"] >= 4
            and result["ddPct"] >= -0.15
        )
        rows.append(
            {
                "weights": weight_string,
                "nonzeroSleeves": int(np.count_nonzero(weights)),
                "effectiveSleeveCount": float(1.0 / np.square(weights[weights > 0]).sum()),
                "developmentPass": passed,
                **result,
                "weightUnits": json.dumps(units),
            }
        )
    grid = pd.DataFrame(rows).sort_values(
        ["developmentPass", "sharpe", "cagr", "ddPct", "weights"],
        ascending=[False, False, False, False, True],
    )
    passing = grid[grid["developmentPass"].eq(True)]
    if passing.empty:
        return grid, None
    selected_units = tuple(json.loads(passing.iloc[0]["weightUnits"]))
    return grid, selected_units


def portfolio_path(
    retained: list[str],
    units: tuple[int, ...],
    series: dict[str, pd.Series],
    index: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights = np.asarray(units, dtype=float) / 4.0
    source_returns = pd.DataFrame(
        {source_id: series[source_id].loc[index] for source_id in retained}, index=index
    )
    combined_return = source_returns.to_numpy() @ weights
    equity = START_CAPITAL
    daily_rows = []
    attribution_rows = []
    for row_number, date in enumerate(index):
        prior_equity = equity
        contributions = prior_equity * weights * source_returns.iloc[row_number].to_numpy()
        daily_pnl = float(contributions.sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "date": date,
                "dailyReturn": float(combined_return[row_number]),
                "dailyPnl": daily_pnl,
                "equity": equity,
            }
        )
        for source_id, weight, contribution in zip(retained, weights, contributions):
            if weight > 0:
                attribution_rows.append(
                    {
                        "date": date,
                        "sourceId": source_id,
                        "weight": weight,
                        "pnl": float(contribution),
                    }
                )
    return pd.DataFrame(daily_rows), pd.DataFrame(attribution_rows)


def yearly_path(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in daily.assign(year=daily["date"].dt.year).groupby("year", sort=True):
        start_equity = float(group.iloc[0]["equity"] - group.iloc[0]["dailyPnl"])
        curve = pd.concat([pd.Series([start_equity]), group["equity"].reset_index(drop=True)], ignore_index=True)
        peak = curve.cummax()
        returns = group["dailyReturn"]
        rows.append(
            {
                "year": int(year),
                "pnl": float(group["dailyPnl"].sum()),
                "return": float(group.iloc[-1]["equity"] / start_equity - 1.0),
                "ddDollar": float((curve - peak).min()),
                "ddPct": float((curve / peak - 1.0).min()),
                "sharpe": float(returns.mean() / returns.std() * math.sqrt(252))
                if returns.std() > 0
                else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_grid_performance"):
        raise RuntimeError("Grid preregistration is not frozen")
    source_files = list(prereg["source_files"])
    forbidden = [name for name in source_files if any(token in name for token in ("OOS", "INVALID", "POLYGON62"))]
    if forbidden:
        raise RuntimeError(f"Forbidden source file in preregistration: {forbidden}")

    benchmark = pd.read_csv(BENCHMARK_FILE, parse_dates=["date"])
    calendar = pd.DatetimeIndex(
        benchmark[
            benchmark["variant"].eq("broad_pit_equal_weight")
            & benchmark["date"].between(DEV_START, VAL_END)
        ]["date"].sort_values().unique()
    )
    catalog, series = load_sources(source_files, calendar)
    decisions, correlation, retained = select_representatives(catalog, series)
    grid, selected_units = run_grid(retained, series, calendar)

    catalog.to_csv(f"{PREFIX}_SOURCE_CATALOG.csv", index=False)
    decisions.to_csv(f"{PREFIX}_REPRESENTATIVES.csv", index=False)
    correlation.to_csv(f"{PREFIX}_DEV_CORRELATION.csv")
    grid.to_csv(f"{PREFIX}_GRID.csv", index=False)

    selection: dict[str, object]
    summary_rows = []
    if selected_units is None:
        selection = {
            "selectedWeights": None,
            "familyStatus": "KILL_NO_DEVELOPMENT_COMBINATION",
            "validationOpened": False,
        }
        daily = pd.DataFrame()
        attribution = pd.DataFrame()
        yearly = pd.DataFrame()
    else:
        dev_index = calendar[(calendar >= DEV_START) & (calendar <= DEV_END)]
        val_index = calendar[(calendar >= VAL_START) & (calendar <= VAL_END)]
        dev_daily, dev_attribution = portfolio_path(retained, selected_units, series, dev_index)
        val_daily, val_attribution = portfolio_path(retained, selected_units, series, val_index)
        dev_result = metrics(dev_daily.set_index("date")["dailyReturn"])
        val_result = metrics(val_daily.set_index("date")["dailyReturn"])
        val_yearly_returns = (
            (1.0 + val_daily.set_index("date")["dailyReturn"])
            .groupby(val_daily["date"].dt.year.to_numpy())
            .prod()
            - 1.0
        )
        validation_pass = bool(
            val_result["pnl"] > 0
            and len(val_yearly_returns) == 2
            and val_yearly_returns.gt(0).all()
            and val_result["sharpe"] >= 0.4
            and val_result["ddPct"] >= -0.12
        )
        weight_string = canonical_weights(retained, selected_units)
        selection = {
            "selectedWeights": weight_string,
            "developmentPass": True,
            "validationPass": validation_pass,
            "familyStatus": "CONTINUE_DIAGNOSTIC" if validation_pass else "KILL_VALIDATION",
            "productionPassAllowed": False,
        }
        for stage, result in (("development", dev_result), ("validation", val_result)):
            summary_rows.append({"stage": stage, "weights": weight_string, **result})
        dev_daily["stage"] = "development"
        val_daily["stage"] = "validation"
        dev_attribution["stage"] = "development"
        val_attribution["stage"] = "validation"
        daily = pd.concat([dev_daily, val_daily], ignore_index=True)
        attribution = pd.concat([dev_attribution, val_attribution], ignore_index=True)
        yearly = yearly_path(daily)

    benchmark_rows = []
    for variant in prereg["benchmarks"]:
        source_id = f"{BENCHMARK_FILE.name}::{variant}"
        for stage, start, end in (
            ("development", DEV_START, DEV_END),
            ("validation", VAL_START, VAL_END),
        ):
            index = calendar[(calendar >= start) & (calendar <= end)]
            benchmark_rows.append(
                {"variant": variant, "stage": stage, **metrics(series[source_id].loc[index])}
            )

    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    pd.DataFrame(summary_rows).to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    pd.DataFrame(benchmark_rows).to_csv(f"{PREFIX}_BENCHMARKS.csv", index=False)
    daily.to_csv(f"{PREFIX}_SELECTED_DAILY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_SELECTED_YEARLY.csv", index=False)
    attribution.to_csv(f"{PREFIX}_SOURCE_ATTRIBUTION_DAILY.csv", index=False)
    if not attribution.empty:
        attribution.groupby(["stage", "sourceId", "weight"], as_index=False)["pnl"].sum().to_csv(
            f"{PREFIX}_SOURCE_ATTRIBUTION.csv", index=False
        )
    else:
        pd.DataFrame(columns=["stage", "sourceId", "weight", "pnl"]).to_csv(
            f"{PREFIX}_SOURCE_ATTRIBUTION.csv", index=False
        )

    manifest = {
        "script": "raits/research/stocks_all_results_sleeve_grid.py",
        "preregistration": str(PREREG),
        "adaptiveMetaSearch": True,
        "oos_2025_2026_consumed": False,
        "sourceFiles": source_files,
        "sourceHashes": {source_file: sha256(Path(source_file)) for source_file in source_files},
        "sourceScenarioCount": int(len(catalog)),
        "eligibleScenarioCount": int(catalog["eligible"].eq(True).sum()),
        "retainedRepresentatives": retained,
        "gridRows": int(len(grid)),
        "selection": selection,
        "tickerLevelSharedReplay": False,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
