from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_quality_universe_gate_nowarmup as qgate
from stocks_pit_full_profile62_yday_path_audit_nowarmup import infer_restricted_rules


OUT_PREFIX = "STOCKS_PIT_FULL_PROFILE62_FROZEN_YDAY_ENGINE_NOWARMUP_2026-09-14"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")


def build_yday_frozen_restricted_rules(daily: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    dq = daily[mask].copy()
    rules = infer_restricted_rules()
    signal_by_rule = {rule.name: qgate.base.yday_gen.apply_rule(dq, rule) for rule in qgate.base.yday_gen.DECLARED_RULE_POOL}
    equity = qgate.base.yday_gen.START_CAPITAL
    outputs = []
    for _, row in rules.iterrows():
        year = int(row["year"])
        rule = str(row["restricted_rule"])
        if rule not in signal_by_rule:
            continue
        tr, cu = qgate.base.yday_gen.simulate(
            signal_by_rule[rule],
            [year],
            start_capital=equity,
            position_pct=0.80,
            max_positions=1,
            cost_bps=qgate.base.yday_gen.DEFAULT_COST_BPS,
        )
        if not cu.empty:
            equity = float(cu["equity"].iloc[-1])
        if not tr.empty:
            tr = tr.copy()
            tr["wfo_mode"] = "rolling3"
            tr["frozen_rule_from_restricted62"] = rule
            outputs.append(tr)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def yearly_metrics(variant: str, eq: pd.DataFrame) -> list[dict]:
    rows = []
    for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
        curve = group["daily_pnl"].cumsum()
        std = float(group["daily_pnl"].std())
        rows.append(
            {
                "variant": variant,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddSubset": float((curve - curve.cummax()).min()),
                "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
            }
        )
    return rows


def main() -> None:
    qgate.base.configure_poly()
    daily = pd.read_pickle(qgate.base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = qgate.add_quality(daily)
    params = qgate.profile_params(daily)
    intraday = pd.read_pickle(qgate.base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    daily_px = qgate.base.poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    gate = qgate.base.pit_gate.load_pit_gate()
    cfg = qgate.base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]

    rows = []
    years = []
    qa = []
    for variant in ["profile62_score_top100", "profile62_train_q25"]:
        mask = qgate.quality_mask(daily, qgate.VARIANTS[variant], params)
        broad = qgate.build_broad_trades(daily, mask)
        local = qgate.build_local_trades(daily, mask)
        yday = build_yday_frozen_restricted_rules(daily, mask)
        signals = qgate.load_signals(broad, local, yday, daily_px, intraday_px)
        gated_signals, gate_qa, _, _ = qgate.base.pit_gate.apply_pit_gate(signals, gate)
        name = f"B_pit_full_{variant}_frozen_yday_restricted_rules_nowarmup_cap40"
        summary, eq, _ = qgate.base.poly.simulate(name, cfg, gated_signals, daily_px)
        summary["variant"] = variant
        rows.append(summary)
        years.extend(yearly_metrics(variant, eq))
        qa.append(
            {
                "variant": variant,
                "broad_rows": int(len(broad)),
                "local_rows": int(len(local)),
                "yday_rows": int(len(yday)),
                "quality_rows": int(mask.sum()),
                "quality_tickers": int(daily.loc[mask, "ticker"].nunique()),
            }
        )
        print("VARIANT", variant, summary, flush=True)

    pd.DataFrame(rows).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(years).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(qa).to_csv(SIGNAL_QA_OUT, index=False)
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SIGNAL_QA_OUT, flush=True)


if __name__ == "__main__":
    main()
