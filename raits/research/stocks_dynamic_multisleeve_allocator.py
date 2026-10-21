from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_final_costaware_four_sleeve_grid as base


PREREG = Path("STOCKS_DYNAMIC_MULTISLEEVE_ALLOCATOR_PREREG_2026-09-24.json")
PREFIX = "STOCKS_DYNAMIC_MULTISLEEVE_ALLOCATOR_2026-09-24"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def capped_normalize(raw: pd.Series, cap: float) -> pd.Series:
    raw = raw.clip(lower=0.0).fillna(0.0)
    if raw.sum() <= 0:
        raw[:] = 1.0
    weights = raw / raw.sum()
    fixed = pd.Series(False, index=weights.index)
    for _ in range(len(weights)):
        over = (~fixed) & weights.gt(cap)
        if not over.any():
            break
        weights.loc[over] = cap
        fixed.loc[over] = True
        remaining = 1.0 - float(weights.loc[fixed].sum())
        free = ~fixed
        if not free.any():
            break
        basis = raw.loc[free]
        weights.loc[free] = remaining * (basis / basis.sum() if basis.sum() > 0 else 1.0 / free.sum())
    return weights / weights.sum()


def source_net_returns(wide: pd.DataFrame) -> pd.DataFrame:
    gross_ret = wide["gross_ret"][base.SOURCE_ORDER]
    turnover = wide["turnover"][base.SOURCE_ORDER]
    gross = wide["gross_exposure"][base.SOURCE_ORDER]
    short = wide["short_gross"][base.SOURCE_ORDER]
    return gross_ret - turnover * 4.0 / 10_000.0 - short * 0.01 / 252.0 - (gross - 1.0).clip(lower=0.0) * 0.025 / 252.0


def allocation_path(wide: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    dates = wide.index
    allowed = list(spec["sources"])
    result = pd.DataFrame(0.0, index=dates, columns=base.SOURCE_ORDER)
    if spec["method"] == "equal":
        result.loc[:, allowed] = 1.0 / len(allowed)
        return result
    net = source_net_returns(wide)
    current = pd.Series(0.0, index=base.SOURCE_ORDER)
    current.loc[allowed] = 1.0 / len(allowed)
    previous_period = None
    for date in dates:
        period = (date.year, date.month) if spec["rebalance"] == "monthly" else (date.year, (date.month - 1) // 3)
        if period != previous_period:
            history = net.loc[net.index < date, allowed].tail(int(spec["lookback"]))
            if len(history) >= int(spec["min_history"]):
                vol = history.std().replace(0.0, np.nan)
                inverse = (1.0 / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
                allocated = capped_normalize(inverse, float(spec["cap"]))
                current[:] = 0.0
                current.loc[allowed] = allocated
            previous_period = period
        result.loc[date] = current
    return result


def replay_dynamic(wide: pd.DataFrame, weights: pd.DataFrame, scale: float, begin: pd.Timestamp, finish: pd.Timestamp) -> pd.DataFrame:
    x = wide.loc[begin:finish]
    w = weights.loc[begin:finish, base.SOURCE_ORDER] * scale
    gross_ret = (x["gross_ret"][base.SOURCE_ORDER] * w).sum(axis=1)
    source_turnover = (x["turnover"][base.SOURCE_ORDER] * w).sum(axis=1)
    gross = (x["gross_exposure"][base.SOURCE_ORDER] * w).sum(axis=1)
    short = (x["short_gross"][base.SOURCE_ORDER] * w).sum(axis=1)
    prior_w = weights.shift(1).reindex(x.index).fillna(weights.reindex(x.index)) * scale
    prior_gross = wide["gross_exposure"][base.SOURCE_ORDER].shift(1).reindex(x.index).fillna(0.0)
    average_gross = (x["gross_exposure"][base.SOURCE_ORDER] + prior_gross) / 2.0
    allocator_turnover = ((w - prior_w).abs() * average_gross).sum(axis=1)
    turnover = source_turnover + allocator_turnover
    trade_ret = turnover * 4.0 / 10_000.0
    borrow_ret = short * 0.01 / 252.0
    financing_ret = (gross - 1.0).clip(lower=0.0) * 0.025 / 252.0
    net_ret = gross_ret - trade_ret - borrow_ret - financing_ret
    equity = base.START_CAPITAL * (1.0 + net_ret).cumprod()
    prior = equity.shift(1, fill_value=base.START_CAPITAL)
    return pd.DataFrame({"date": x.index, "gross_ret": gross_ret.to_numpy(), "net_ret": net_ret.to_numpy(),
        "prior_equity": prior.to_numpy(), "daily_pnl": (prior * net_ret).to_numpy(), "equity": equity.to_numpy(),
        "turnover": turnover.to_numpy(), "source_turnover": source_turnover.to_numpy(), "allocator_turnover": allocator_turnover.to_numpy(),
        "gross_exposure": gross.to_numpy(), "short_gross": short.to_numpy(), "trade_cost": (prior * trade_ret).to_numpy(),
        "borrow_cost": (prior * borrow_ret).to_numpy(), "financing_cost": (prior * financing_ret).to_numpy()})


def ticker_dynamic(tickers: pd.DataFrame, path: pd.DataFrame, weights: pd.DataFrame, scale: float) -> pd.DataFrame:
    long_weights = weights.stack().rename("allocator_weight").rename_axis(["date", "source"]).reset_index()
    active = tickers.merge(long_weights, on=["date", "source"], how="inner")
    active = active[active["allocator_weight"].gt(0)].copy()
    active["weighted_ret"] = active["ticker_gross_ret"] * active["allocator_weight"] * scale
    combined = active.groupby(["date", "ticker"], as_index=False)["weighted_ret"].sum()
    combined = combined.merge(path[["date", "prior_equity", "trade_cost", "borrow_cost", "financing_cost"]], on="date", how="inner")
    combined["gross_pnl"] = combined["prior_equity"] * combined["weighted_ret"]
    absolute = combined.groupby("date")["gross_pnl"].transform(lambda x: x.abs().sum())
    total_cost = combined["trade_cost"] + combined["borrow_cost"] + combined["financing_cost"]
    combined["allocated_cost"] = np.where(absolute > 0, combined["gross_pnl"].abs() / absolute * total_cost, 0.0)
    zero_dates = combined.loc[absolute.eq(0), "date"].drop_duplicates()
    for date in zero_dates:
        mask = combined["date"].eq(date)
        spy = mask & combined["ticker"].eq("SPY")
        target = combined.index[spy][0] if spy.any() else combined.index[mask][0]
        combined.loc[target, "allocated_cost"] = float(total_cost.loc[target])
    combined["pnl"] = combined["gross_pnl"] - combined["allocated_cost"]
    return combined


def concentration(ticker: pd.DataFrame) -> dict[str, object]:
    by = ticker.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(by.sum())
    positive = by[by > 0]
    basis = positive if positive.sum() > 0 else by.abs()
    weights = basis / basis.sum() if basis.sum() else basis
    row: dict[str, object] = {"tickers": len(by), "effectiveTickerCount": 1.0 / weights.pow(2).sum() if len(weights) else 0.0,
        "topTicker": by.index[0] if len(by) else "", "spyPnl": float(by.get("SPY", 0.0)),
        "spyNetPnlShare": float(by.get("SPY", 0.0)) / total if total else np.nan}
    denominator = total if total > 0 else float(by.abs().sum())
    for n in (1, 3, 5, 10):
        value = float(by.head(n).sum())
        row[f"top{n}Pnl"], row[f"top{n}Share"] = value, value / denominator if denominator else np.nan
    return row


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_performance") or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    wide, tickers = base.load_inputs()
    lead_weights = pd.DataFrame({name: 0.0 for name in base.SOURCE_ORDER}, index=wide.index)
    lead_weights["pairs"], lead_weights["calendar"] = 0.75, 0.25
    lead_path = replay_dynamic(wide, lead_weights, 1.0, base.START, base.DEV_END)
    lead_stats = base.stats(lead_path)
    lead_conc = concentration(ticker_dynamic(tickers[tickers["date"].between(base.START, base.DEV_END)], lead_path, lead_weights.loc[base.START:base.DEV_END], 1.0))
    lead_calmar = lead_stats["cagr"] / abs(lead_stats["ddPct"])

    allocation_paths = {spec["name"]: allocation_path(wide, spec) for spec in prereg["variants"]}
    rows = []
    for spec in prereg["variants"]:
        name = spec["name"]
        path = replay_dynamic(wide, allocation_paths[name], 1.0, base.START, base.DEV_END)
        result = base.stats(path)
        tc = ticker_dynamic(tickers[tickers["date"].between(base.START, base.DEV_END)], path, allocation_paths[name].loc[base.START:base.DEV_END], 1.0)
        conc = concentration(tc)
        calmar = result["cagr"] / abs(result["ddPct"])
        passed = bool(result["cagr"] >= 0.08 and result["ddPct"] >= -0.10 and result["positiveYears"] >= 4 and conc["spyNetPnlShare"] <= 0.65 and calmar > lead_calmar)
        reasons = []
        if result["cagr"] < 0.08: reasons.append("cagr<8%")
        if result["ddPct"] < -0.10: reasons.append("dd<-10%")
        if result["positiveYears"] < 4: reasons.append("positiveYears<4")
        if conc["spyNetPnlShare"] > 0.65: reasons.append("spyShare>65%")
        if calmar <= lead_calmar: reasons.append("calmar<=lead")
        rows.append({"variant": name, "developmentPass": passed, "calmar": calmar, **result, **conc, "rejectionReason": "|".join(reasons)})
    candidates = pd.DataFrame(rows).sort_values(["developmentPass", "calmar", "cagr", "sharpe", "variant"], ascending=[False, False, False, False, True])
    passing = candidates[candidates["developmentPass"].eq(True)]
    lead_row = {"variant": "fixed_lead_75pairs_25calendar", "calmar": lead_calmar, **lead_stats, **lead_conc}

    if passing.empty:
        selection = {"selectedVariant": None, "status": "KILL_NO_DEVELOPMENT_IMPROVEMENT", "validationOpened": False, "productionPassAllowed": False}
        summary = yearly = daily_all = ticker_selected = concentrations = allocation_selected = pd.DataFrame()
    else:
        selected = str(passing.iloc[0]["variant"])
        alloc = allocation_paths[selected]
        summary_rows, yearly_rows, daily_frames, ticker_frames, concentration_rows = [], [], [], [], []
        for scale in prereg["selected_scale_audit"]:
            for stage, begin, finish in (("development", base.START, base.DEV_END), ("validation_touched", base.VAL_START, base.END), ("full_touched", base.START, base.END)):
                path = replay_dynamic(wide, alloc, scale, begin, finish)
                result = base.stats(path)
                path["scale"], path["stage"], path["variant"] = scale, stage, selected
                daily_frames.append(path)
                tc = ticker_dynamic(tickers[tickers["date"].between(begin, finish)], path, alloc.loc[begin:finish], scale)
                tc["scale"], tc["stage"], tc["variant"] = scale, stage, selected
                ticker_frames.append(tc)
                conc = concentration(tc)
                summary_rows.append({"variant": selected, "scale": scale, "stage": stage, **result, **conc})
                concentration_rows.append({"variant": selected, "scale": scale, "stage": stage, **conc})
                for year, group in path.assign(year=path["date"].dt.year).groupby("year"):
                    yearly_rows.append({"variant": selected, "scale": scale, "stage": stage, "year": year, "pnl": group["daily_pnl"].sum(), "tradeCost": group["trade_cost"].sum(), "borrowCost": group["borrow_cost"].sum(), "financingCost": group["financing_cost"].sum()})
        summary, yearly = pd.DataFrame(summary_rows), pd.DataFrame(yearly_rows)
        daily_all, ticker_selected = pd.concat(daily_frames, ignore_index=True), pd.concat(ticker_frames, ignore_index=True)
        concentrations = pd.DataFrame(concentration_rows)
        allocation_selected = alloc.reset_index().rename(columns={"index": "date"})
        val = summary[(summary["scale"].eq(1.0)) & summary["stage"].eq("validation_touched")].iloc[0]
        val_years = yearly[(yearly["scale"].eq(1.0)) & yearly["stage"].eq("validation_touched")]["pnl"]
        validation_pass = bool(val["cagr"] > 0 and val["ddPct"] >= -0.12 and val_years.gt(0).all() and val["spyNetPnlShare"] <= 0.80)
        selection = {"selectedVariant": selected, "developmentRank": 1, "validationPass": validation_pass,
            "status": "CONTINUE_DIAGNOSTIC" if validation_pass else "KILL_VALIDATION", "productionPassAllowed": False}

    candidates.to_csv(f"{PREFIX}_DEVELOPMENT_CANDIDATES.csv", index=False)
    pd.DataFrame([lead_row]).to_csv(f"{PREFIX}_LEAD_BENCHMARK.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    summary.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    daily_all.to_csv(f"{PREFIX}_SELECTED_DAILY.csv", index=False)
    ticker_selected.to_csv(f"{PREFIX}_TICKER_ATTRIBUTION.csv", index=False)
    concentrations.to_csv(f"{PREFIX}_CONCENTRATION.csv", index=False)
    allocation_selected.to_csv(f"{PREFIX}_SELECTED_WEIGHTS_DAILY.csv", index=False)
    inputs = [spec[key] for spec in base.SOURCES.values() for key in ("daily", "ticker")] + [base.CALENDAR_DAILY, PREREG]
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in inputs}, "leadBenchmark": lead_row,
        "candidateCount": len(candidates), "developmentPassCount": int(candidates["developmentPass"].sum()),
        "selection": selection, "oos2025_2026Consumed": False, "productionPassAllowed": False,
        "ruleSelectionEffect": "One dynamic rule selected by frozen development Calmar gates; validation cannot replace it.",
        "tradeSelectionEffect": "Underlying sleeve trades are unchanged; only lagged allocator weights change capital assigned to them."}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(pd.DataFrame([lead_row]).to_string(index=False), flush=True)
    print(candidates.to_string(index=False), flush=True)
    print(json.dumps(selection, indent=2), flush=True)
    print(summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
