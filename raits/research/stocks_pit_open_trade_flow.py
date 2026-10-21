from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_opening_10m15m_price_volume as base


PREREG = Path("STOCKS_PIT_OPEN_TRADE_FLOW_PREREG_2026-10-01.json")
FEATURES = Path("raits/data/cache/polygon_stock_trades_open_2018_2022/causal_features_pre0935.parquet")
FEATURE_MANIFEST = Path("raits/data/cache/polygon_stock_trades_open_2018_2022/causal_features_pre0935_manifest.json")
EXACT_CLOCK = Path("STOCKS_PIT_OPENING_10M15M_PRICE_VOLUME_2026-10-01_EXACT_CLOCK_ROWS.csv")
PREFIX = "STOCKS_PIT_OPEN_TRADE_FLOW_2026-10-01"
START = pd.Timestamp("2018-05-24")
DEV_END = pd.Timestamp("2021-12-31")
VAL_START = pd.Timestamp("2022-01-01")
VAL_END = pd.Timestamp("2022-12-30")
INITIAL_EQUITY = 100_000.0
BASE_COST_BPS_PER_SIDE = 4.0
STRESS_COST_BPS_PER_SIDE = 8.0
BORROW_ANNUAL = 0.01
ENTRY_CLOCK = "09:40"
VARIANTS = {
    "flow_confirmation_15m": ("flow_confirmation", "15m"),
    "flow_divergence_10m": ("flow_divergence", "10m"),
    "late_flow_flip_10m": ("late_flow_flip", "10m"),
    "large_trade_confirmation_15m": ("large_trade_confirmation", "15m"),
    "trf_divergence_10m": ("trf_divergence", "10m"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_panel() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    panel, sessions = base.load_signal_panel(VAL_END)
    preliminary = base.preliminary_candidates(
        panel, {"residual_reversal", "residual_continuation", "gap_rejection", "gap_confirmation"}
    )
    exact = pd.read_csv(EXACT_CLOCK, parse_dates=["date"])
    exact["date"] = exact["date"].dt.normalize()
    exact_panel = base.attach_exact_prices(preliminary, exact)
    features = pd.read_parquet(FEATURES)
    features["date"] = pd.to_datetime(features["date"]).dt.normalize()
    features["ticker"] = features["ticker"].astype(str).str.upper()
    if features["max_signal_sip_timestamp"].ge(features["signal_end_ns"]).any():
        raise RuntimeError("Post-09:35 feature record detected")
    merged = exact_panel.merge(features, on=["date", "ticker"], how="inner", validate="one_to_one")
    if len(merged) != len(features) or len(features) != 32_176:
        raise RuntimeError(f"Feature/panel coverage mismatch: panel={len(exact_panel)} features={len(features)} merged={len(merged)}")
    return merged.sort_values(["date", "ticker"]).reset_index(drop=True), sessions


def candidates_for_family(panel: pd.DataFrame, family: str) -> pd.DataFrame:
    out = panel[
        panel["signal_entry_complete"]
        & panel["rvol930"].ge(1.5)
        & panel["first5_ret"].abs().ge(0.003)
        & panel["signal_trades"].ge(100)
        & panel["signal_dollar"].ge(1_000_000.0)
    ].copy()
    price_side = np.sign(out["first5_ret"])
    if family == "flow_confirmation":
        out = out[out["flow_imbalance"].mul(price_side).ge(0.15)].copy()
        out["side"] = np.sign(out["first5_ret"])
        micro_strength = out["flow_imbalance"].abs()
    elif family == "flow_divergence":
        out = out[out["flow_imbalance"].mul(price_side).le(-0.15)].copy()
        out["side"] = -np.sign(out["first5_ret"])
        micro_strength = out["flow_imbalance"].abs()
    elif family == "late_flow_flip":
        out = out[
            out["early_flow_imbalance"].mul(price_side).ge(0.15)
            & out["late_flow_imbalance"].mul(price_side).le(-0.20)
        ].copy()
        out["side"] = -np.sign(out["first5_ret"])
        micro_strength = out["early_flow_imbalance"].abs() + out["late_flow_imbalance"].abs()
    elif family == "large_trade_confirmation":
        out = out[
            out["large_flow_imbalance"].mul(price_side).ge(0.20)
            & out["large_trade_dollar_share"].ge(0.70)
        ].copy()
        out["side"] = np.sign(out["first5_ret"])
        micro_strength = out["large_flow_imbalance"].abs() * out["large_trade_dollar_share"]
    elif family == "trf_divergence":
        out = out[
            out["trf_dollar_share"].ge(0.15)
            & out["lit_flow_imbalance"].mul(price_side).ge(0.15)
            & out["trf_flow_imbalance"].mul(price_side).le(-0.15)
        ].copy()
        out["side"] = -np.sign(out["first5_ret"])
        micro_strength = out["lit_flow_imbalance"].abs() + out["trf_flow_imbalance"].abs()
    else:
        raise ValueError(family)
    out["event_score"] = out["first5_ret"].abs() * micro_strength * np.sqrt(out["rvol930"].clip(upper=10.0))
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
    candidates = candidates_for_family(panel, family)
    rows: list[pd.DataFrame] = []
    exit_columns = [f"open_{clock.replace(':', '')}" for clock in base.EXIT_FALLBACKS[horizon]]
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
            (pd.Timestamp(f"2000-01-01 {clock}") - pd.Timestamp(f"2000-01-01 {base.EXIT_CLOCKS[horizon]}")).seconds / 60
            for clock in selected["exit_clock"]
        ]
        selected["hold_minutes"] = [
            (pd.Timestamp(f"2000-01-01 {clock}") - pd.Timestamp(f"2000-01-01 {ENTRY_CLOCK}")).seconds / 60
            for clock in selected["exit_clock"]
        ]
        selected["raw_return"] = selected["exit_price"] / selected["entry_price"] - 1.0
        selected["signed_return"] = selected["target_weight"] * selected["raw_return"]
        selected["variant"] = variant
        selected["family"] = family
        selected["horizon"] = horizon
        rows.append(selected)
    return pd.concat(rows, ignore_index=True) if rows else candidates.iloc[0:0].copy()


def simulate(variant: str, trades: pd.DataFrame, sessions: list[pd.Timestamp], cost_bps: float, scope: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_date = {date: group for date, group in trades.groupby("date", sort=True)} if not trades.empty else {}
    equity = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    daily_rows: list[dict[str, object]] = []
    contrib_rows: list[dict[str, object]] = []
    for date in sessions:
        day = by_date.get(date)
        gross_pnl = cost = borrow = gross = max_adv = 0.0
        if day is not None and not day.empty:
            start_equity = equity
            gross = float(day["target_weight"].abs().sum())
            participation = start_equity * day["target_weight"].abs() / day["adv20"]
            max_adv = float(participation.max())
            if max_adv > 0.01 + 1e-12:
                raise RuntimeError(f"ADV breach: {variant} {date.date()} {max_adv}")
            gross_pnl = float(start_equity * day["signed_return"].sum())
            cost = start_equity * gross * 2.0 * cost_bps / 10_000.0
            borrow_by_trade = np.where(
                day["target_weight"].lt(0),
                start_equity * day["target_weight"].abs() * BORROW_ANNUAL * day["hold_minutes"] / (252.0 * 390.0),
                0.0,
            )
            borrow = float(np.sum(borrow_by_trade))
            allocation = day["target_weight"].abs() / gross * cost + borrow_by_trade
            for (_, trade), allocated in zip(day.iterrows(), allocation):
                gross_leg = start_equity * trade["signed_return"]
                contrib_rows.append({"variant": variant, "scope": scope, "cost_bps": cost_bps, "date": date,
                    "ticker": trade["ticker"], "gross_pnl": gross_leg, "cost_and_borrow": allocated,
                    "net_pnl": gross_leg - allocated})
            equity += gross_pnl - cost - borrow
        peak = max(peak, equity)
        daily_rows.append({"variant": variant, "scope": scope, "cost_bps": cost_bps, "date": date,
            "equity": equity, "daily_pnl": gross_pnl - cost - borrow, "gross_pnl": gross_pnl,
            "trading_cost": cost, "borrow_cost": borrow, "gross": gross,
            "trade_legs": 0 if day is None else len(day), "max_order_adv_fraction": max_adv,
            "fallback_exit_legs": 0 if day is None else int(day["exit_delay_minutes"].gt(0).sum()),
            "max_exit_delay_minutes": 0.0 if day is None else float(day["exit_delay_minutes"].max()),
            "dd_dollar": equity - peak, "dd_pct": equity / peak - 1.0})
    return pd.DataFrame(daily_rows), pd.DataFrame(contrib_rows)


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily["daily_pnl"] / (daily["equity"] - daily["daily_pnl"])
    years = max((daily["date"].max() - daily["date"].min()).days / 365.25, 1e-9)
    yearly = (1.0 + returns).groupby(daily["date"].dt.year).prod() - 1.0
    active = daily["trade_legs"].gt(0)
    return {"pnl": float(daily["daily_pnl"].sum()), "grossPnl": float(daily["gross_pnl"].sum()),
        "cagr": float((daily.iloc[-1]["equity"] / INITIAL_EQUITY) ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan,
        "ddDollar": float(daily["dd_dollar"].min()), "ddPct": float(daily["dd_pct"].min()),
        "positiveYears": int(yearly.gt(0).sum()), "activeDays": int(active.sum()),
        "tradeLegs": int(daily["trade_legs"].sum()), "tradingCost": float(daily["trading_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()), "fallbackExitLegs": int(daily["fallback_exit_legs"].sum()),
        "maxExitDelayMinutes": float(daily["max_exit_delay_minutes"].max()),
        "maxOrderAdvFraction": float(daily["max_order_adv_fraction"].max())}


def concentration(contrib: pd.DataFrame) -> dict[str, object]:
    by = contrib.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False) if not contrib.empty else pd.Series(dtype=float)
    positive = by[by.gt(0)]
    total = float(positive.sum())
    row: dict[str, object] = {"tickers": len(by), "topTicker": by.index[0] if len(by) else "",
        "effectiveTickerCount": float(total**2 / positive.pow(2).sum()) if total > 0 else 0.0}
    for count in (1, 3, 5, 10):
        row[f"top{count}PositiveShare"] = float(positive.head(count).sum() / total) if total > 0 else np.nan
    return row


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
        for cost_bps in (BASE_COST_BPS_PER_SIDE, STRESS_COST_BPS_PER_SIDE):
            daily, contrib = simulate(variant, trades, scoped_sessions, cost_bps, scope)
            daily_frames.append(daily)
            contrib_frames.append(contrib)
            if cost_bps == BASE_COST_BPS_PER_SIDE:
                base_daily, base_contrib = daily, contrib
            else:
                stress_pnl = metrics(daily)["pnl"]
        result = metrics(base_daily)
        gross_edge = ((trades["target_weight"] * trades["raw_return"]).groupby(trades["date"]).sum().mean() * 10_000.0
                      if not trades.empty else np.nan)
        summary_rows.append({"variant": variant, "family": VARIANTS[variant][0], "horizon": VARIANTS[variant][1],
            "grossEdgeBpsPerActiveDay": gross_edge, "stressPnl": stress_pnl, **result, **concentration(base_contrib)})
    return {"summary": pd.DataFrame(summary_rows), "trades": pd.concat(trade_frames, ignore_index=True),
        "daily": pd.concat(daily_frames, ignore_index=True), "contrib": pd.concat(contrib_frames, ignore_index=True)}


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash mismatch")
    panel, sessions = load_panel()
    dev = run_scope(panel, sessions, START, DEV_END, "development", list(VARIANTS))
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
        val = run_scope(panel, sessions, VAL_START, VAL_END, "validation", [selected])
        validation = val["summary"].copy()
        validation["validationPass"] = (
            validation["activeDays"].ge(20) & validation["pnl"].gt(0) & validation["sharpe"].ge(0.5)
            & validation["ddPct"].ge(-0.10) & validation["stressPnl"].gt(0)
            & validation["top10PositiveShare"].le(0.60)
        )
        passed = bool(validation.iloc[0]["validationPass"])
        selection = {"status": "CONTINUE_AUDIT" if passed else "KILL_VALIDATION_FAIL", "selectedVariant": selected,
                     "validationOpened": True, "validationPass": passed, "productionPassAllowed": False}
        outputs = {key: pd.concat([dev[key], val[key]], ignore_index=True) if key != "summary" else dev[key] for key in ("summary", "trades", "daily", "contrib")}

    daily, contrib = outputs["daily"], outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(
        ["variant", "scope", "cost_bps", "year"], as_index=False
    ).agg(pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"),
          borrowCost=("borrow_cost", "sum"), activeDays=("trade_legs", lambda x: int(x.gt(0).sum())), tradeLegs=("trade_legs", "sum"))
    qa_rows: list[dict[str, object]] = []
    for (variant, scope, cost_bps), group in daily.groupby(["variant", "scope", "cost_bps"]):
        matching = contrib[(contrib["variant"].eq(variant)) & (contrib["scope"].eq(scope)) & (contrib["cost_bps"].eq(cost_bps))]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - INITIAL_EQUITY)
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
        "featureCache": str(FEATURES).replace("\\", "/"), "featureCacheHash": sha256(FEATURES),
        "featureManifest": str(FEATURE_MANIFEST).replace("\\", "/"), "featureManifestHash": sha256(FEATURE_MANIFEST),
        "exactClock": str(EXACT_CLOCK), "exactClockHash": sha256(EXACT_CLOCK), "selection": selection,
        "development": [str(START.date()), str(DEV_END.date())],
        "validation": [str(VAL_START.date()), str(VAL_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False, "post2022Consumed": False, "productionPassAllowed": False,
        "causality": "features use SIP arrivals strictly before 09:35 ET; exact 09:40 entry; fixed scheduled exits with causal same-session halt fallback"}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False))
    print(validation.to_string(index=False))
    print(json.dumps(selection, indent=2))
    print(qa.to_string(index=False))


if __name__ == "__main__":
    main()
