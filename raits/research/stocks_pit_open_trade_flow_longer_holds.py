from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_open_trade_flow as prior


PREREG = Path("STOCKS_PIT_OPEN_TRADE_FLOW_LONGER_HOLDS_PREREG_2026-10-01.json")
PREFIX = "STOCKS_PIT_OPEN_TRADE_FLOW_LONGER_HOLDS_2026-10-01"
EXIT_CLOCKS = {"30m": "10:10", "60m": "10:40", "eod": "15:55"}
EXIT_FALLBACKS = {
    horizon: pd.date_range(f"2000-01-01 {clock}", "2000-01-01 16:00", freq="5min").strftime("%H:%M").tolist()
    for horizon, clock in EXIT_CLOCKS.items()
}
VARIANTS = {
    "xs_flow_30m": ("xs_flow", "30m"),
    "xs_late_flow_60m": ("xs_late_flow", "60m"),
    "xs_large_flow_eod": ("xs_large_flow", "eod"),
    "trf_lit_spread_60m": ("trf_lit_spread", "60m"),
    "flow_price_rank_divergence_eod": ("flow_price_rank_divergence", "eod"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def candidates_for_variant(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    family, _ = VARIANTS[variant]
    out = panel[
        panel["signal_entry_complete"]
        & panel["rvol930"].ge(1.5)
        & panel["first5_ret"].abs().ge(0.003)
        & panel["signal_trades"].ge(100)
        & panel["signal_dollar"].ge(1_000_000.0)
    ].copy()
    if family == "xs_flow":
        out["flow_score"] = out["flow_imbalance"]
        out = out[out["flow_score"].abs().ge(0.15)].copy()
    elif family == "xs_late_flow":
        out["flow_score"] = out["late_flow_imbalance"]
        out = out[out["flow_score"].abs().ge(0.20)].copy()
    elif family == "xs_large_flow":
        out["flow_score"] = out["large_flow_imbalance"]
        out = out[out["flow_score"].abs().ge(0.20) & out["large_trade_dollar_share"].ge(0.70)].copy()
    elif family == "trf_lit_spread":
        out["flow_score"] = out["trf_flow_imbalance"] - out["lit_flow_imbalance"]
        out = out[out["trf_dollar_share"].ge(0.10) & out["flow_score"].abs().ge(0.30)].copy()
    elif family == "flow_price_rank_divergence":
        out["flow_rank"] = out.groupby("date")["flow_imbalance"].rank(pct=True, method="average")
        out["price_rank"] = out.groupby("date")["first5_ret"].rank(pct=True, method="average")
        out["flow_score"] = out["flow_rank"] - out["price_rank"]
        out = out[out["flow_score"].abs().ge(0.50)].copy()
    else:
        raise ValueError(family)
    out["side"] = np.sign(out["flow_score"])
    out["event_score"] = (
        out["flow_score"].abs()
        * np.sqrt(out["rvol930"].clip(upper=10.0))
        * np.sqrt((out["first5_ret"].abs() / 0.003).clip(upper=5.0))
    )
    return out[out["side"].ne(0)].copy()


def select_side(group: pd.DataFrame, side: int) -> pd.DataFrame:
    selected: list[int] = []
    sic_counts: defaultdict[str, int] = defaultdict(int)
    ordered = group[group["side"].eq(side)].sort_values(
        ["event_score", "adv20", "ticker"], ascending=[False, False, True]
    )
    for row in ordered.itertuples():
        sic = str(row.sic_description)
        if sic_counts[sic] >= 1:
            continue
        selected.append(row.Index)
        sic_counts[sic] += 1
        if len(selected) == 3:
            break
    return group.loc[selected].copy() if selected else group.iloc[0:0].copy()


def build_trades(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    family, horizon = VARIANTS[variant]
    candidates = candidates_for_variant(panel, variant)
    rows: list[pd.DataFrame] = []
    exit_columns = [f"open_{clock.replace(':', '')}" for clock in EXIT_FALLBACKS[horizon]]
    for date, group in candidates.groupby("date", sort=True):
        longs, shorts = select_side(group, 1), select_side(group, -1)
        if len(longs) != 3 or len(shorts) != 3:
            continue
        selected = pd.concat([longs, shorts], ignore_index=True)
        selected["target_weight"] = np.where(selected["side"].gt(0), 1.0 / 6.0, -1.0 / 6.0)
        selected["entry_price"] = selected["open_0940"]
        available = selected[exit_columns].notna()
        if not available.any(axis=1).all():
            missing = selected.loc[~available.any(axis=1), "ticker"].tolist()
            raise RuntimeError(f"No same-session exit for {variant} {date.date()}: {missing}")
        selected["exit_price"] = selected[exit_columns].bfill(axis=1).iloc[:, 0]
        selected["exit_clock"] = available.idxmax(axis=1).str.removeprefix("open_").str.replace(
            r"^(\d{2})(\d{2})$", r"\1:\2", regex=True
        )
        selected["exit_delay_minutes"] = [
            (pd.Timestamp(f"2000-01-01 {clock}") - pd.Timestamp(f"2000-01-01 {EXIT_CLOCKS[horizon]}")).seconds / 60
            for clock in selected["exit_clock"]
        ]
        selected["hold_minutes"] = [
            (pd.Timestamp(f"2000-01-01 {clock}") - pd.Timestamp(f"2000-01-01 {prior.ENTRY_CLOCK}")).seconds / 60
            for clock in selected["exit_clock"]
        ]
        selected["raw_return"] = selected["exit_price"] / selected["entry_price"] - 1.0
        selected["signed_return"] = selected["target_weight"] * selected["raw_return"]
        selected["variant"] = variant
        selected["family"] = family
        selected["horizon"] = horizon
        rows.append(selected)
    return pd.concat(rows, ignore_index=True) if rows else candidates.iloc[0:0].copy()


def run_scope(panel: pd.DataFrame, sessions: list[pd.Timestamp], start: pd.Timestamp, end: pd.Timestamp,
              scope: str, variants: list[str]) -> dict[str, pd.DataFrame]:
    scoped_panel = panel[panel["date"].between(start, end)].copy()
    scoped_sessions = [date for date in sessions if start <= date <= end]
    trade_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    contrib_frames: list[pd.DataFrame] = []
    summary_rows: list[dict[str, object]] = []
    for variant in variants:
        trades = build_trades(scoped_panel, variant)
        trades["scope"] = scope
        trade_frames.append(trades)
        base_daily = pd.DataFrame()
        base_contrib = pd.DataFrame()
        stress_pnl = np.nan
        for cost_bps in (prior.BASE_COST_BPS_PER_SIDE, prior.STRESS_COST_BPS_PER_SIDE):
            daily, contrib = prior.simulate(variant, trades, scoped_sessions, cost_bps, scope)
            daily_frames.append(daily)
            contrib_frames.append(contrib)
            if cost_bps == prior.BASE_COST_BPS_PER_SIDE:
                base_daily, base_contrib = daily, contrib
            else:
                stress_pnl = prior.metrics(daily)["pnl"]
        result = prior.metrics(base_daily)
        gross_edge = ((trades["target_weight"] * trades["raw_return"]).groupby(trades["date"]).sum().mean() * 10_000.0
                      if not trades.empty else np.nan)
        summary_rows.append({"variant": variant, "family": VARIANTS[variant][0], "horizon": VARIANTS[variant][1],
            "grossEdgeBpsPerActiveDay": gross_edge, "stressPnl": stress_pnl, **result, **prior.concentration(base_contrib)})
    return {"summary": pd.DataFrame(summary_rows), "trades": pd.concat(trade_frames, ignore_index=True),
        "daily": pd.concat(daily_frames, ignore_index=True), "contrib": pd.concat(contrib_frames, ignore_index=True)}


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash mismatch")
    panel, sessions = prior.load_panel()
    dev = run_scope(panel, sessions, prior.START, prior.DEV_END, "development", list(VARIANTS))
    development = dev["summary"].copy()
    development["developmentPass"] = (
        development["activeDays"].ge(100) & development["tradeLegs"].ge(600)
        & development["cagr"].ge(0.05) & development["sharpe"].ge(0.8)
        & development["ddPct"].ge(-0.12) & development["positiveYears"].ge(3)
        & development["grossEdgeBpsPerActiveDay"].ge(12.0) & development["stressPnl"].gt(0)
        & development["top10PositiveShare"].le(0.50)
    )
    development = development.sort_values(
        ["developmentPass", "sharpe", "cagr", "variant"], ascending=[False, False, False, True]
    )
    passing = development[development["developmentPass"]]
    validation = pd.DataFrame()
    outputs = dev
    if passing.empty:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "selectedVariant": None,
                     "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"])
        val = run_scope(panel, sessions, prior.VAL_START, prior.VAL_END, "validation", [selected])
        validation = val["summary"].copy()
        validation["validationPass"] = (
            validation["activeDays"].ge(20) & validation["pnl"].gt(0) & validation["sharpe"].ge(0.5)
            & validation["ddPct"].ge(-0.10) & validation["stressPnl"].gt(0)
            & validation["top10PositiveShare"].le(0.60)
        )
        passed = bool(validation.iloc[0]["validationPass"])
        selection = {"status": "CONTINUE_AUDIT" if passed else "KILL_VALIDATION_FAIL", "selectedVariant": selected,
                     "validationOpened": True, "validationPass": passed, "productionPassAllowed": False}
        outputs = {key: pd.concat([dev[key], val[key]], ignore_index=True) if key != "summary" else dev[key]
                   for key in ("summary", "trades", "daily", "contrib")}

    daily, contrib = outputs["daily"], outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(
        ["variant", "scope", "cost_bps", "year"], as_index=False
    ).agg(pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"),
          borrowCost=("borrow_cost", "sum"), activeDays=("trade_legs", lambda x: int(x.gt(0).sum())), tradeLegs=("trade_legs", "sum"))
    qa_rows: list[dict[str, object]] = []
    for (variant, scope, cost_bps), group in daily.groupby(["variant", "scope", "cost_bps"]):
        matching = contrib[(contrib["variant"].eq(variant)) & (contrib["scope"].eq(scope)) & (contrib["cost_bps"].eq(cost_bps))]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - prior.INITIAL_EQUITY)
        qa_rows.append({"variant": variant, "scope": scope, "cost_bps": cost_bps,
            "dailyPnl": group["daily_pnl"].sum(), "endingDelta": ending, "contribPnl": matching["net_pnl"].sum(),
            "dailyMinusEnding": group["daily_pnl"].sum() - ending,
            "dailyMinusContrib": group["daily_pnl"].sum() - matching["net_pnl"].sum()})
    qa = pd.DataFrame(qa_rows)

    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False)
    validation.to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    outputs["trades"].to_csv(f"{PREFIX}_TRADES.csv", index=False)
    daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "featureCache": str(prior.FEATURES).replace("\\", "/"), "featureCacheHash": sha256(prior.FEATURES),
        "exactClock": str(prior.EXACT_CLOCK), "exactClockHash": sha256(prior.EXACT_CLOCK), "selection": selection,
        "development": [str(prior.START.date()), str(prior.DEV_END.date())],
        "validation": [str(prior.VAL_START.date()), str(prior.VAL_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False, "post2022Consumed": False, "productionPassAllowed": False,
        "causality": "features use SIP arrivals strictly before 09:35 ET; exact 09:40 entry; fixed 10:10/10:40/15:55 exits with causal same-session fallback"}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False))
    print(validation.to_string(index=False))
    print(json.dumps(selection, indent=2))
    print(qa.to_string(index=False))


if __name__ == "__main__":
    main()
