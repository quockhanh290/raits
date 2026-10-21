from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_quality_universe_gate_nowarmup as qgate


OUT_PREFIX = "STOCKS_PIT_FULL_PROFILE62_YDAY_PATH_AUDIT_NOWARMUP_2026-09-14"
RULES_OUT = Path(f"{OUT_PREFIX}_RULES.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")

RESTRICTED_YDAY = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_YDAY_TRADES.csv")


def load_daily_with_mask(variant: str) -> tuple[pd.DataFrame, pd.Series]:
    daily = pd.read_pickle(qgate.base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = qgate.add_quality(daily)
    params = qgate.profile_params(daily)
    mask = qgate.quality_mask(daily, qgate.VARIANTS[variant], params)
    return daily, mask


def infer_restricted_rules() -> pd.DataFrame:
    y = pd.read_csv(RESTRICTED_YDAY, parse_dates=["date"])
    y = y[y["wfo_mode"].eq("rolling3")].copy()
    out = (
        y.groupby(y["date"].dt.year)["rule"]
        .agg(lambda s: s.value_counts().index[0])
        .reset_index()
        .rename(columns={"date": "year", "rule": "restricted_rule"})
    )
    return out


def run_profile_rules(variant: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], pd.DataFrame]:
    daily, mask = load_daily_with_mask(variant)
    dq = daily[mask].copy()
    pe = qgate.base.yday_gen.build_pe_signals(dq, set())
    signal_by_rule = {rule.name: qgate.base.yday_gen.apply_rule(dq, rule) for rule in qgate.base.yday_gen.DECLARED_RULE_POOL}
    choices, trades, curve = qgate.base.yday_gen.run_wfo(
        signal_by_rule,
        pe,
        mode="rolling3",
        test_years=qgate.base.yday_gen.DEFAULT_TEST_YEARS,
        include_pe=False,
        start_capital=qgate.base.yday_gen.START_CAPITAL,
        position_pct=0.80,
        max_positions=1,
        cost_bps=qgate.base.yday_gen.DEFAULT_COST_BPS,
    )
    choices["variant"] = variant
    trades["variant"] = variant
    return choices, signal_by_rule, trades


def simulate_frozen_rules(variant: str, signal_by_rule: dict[str, pd.DataFrame], rules: pd.DataFrame) -> pd.DataFrame:
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
            tr["variant"] = variant
            tr["frozen_rule_from_restricted62"] = rule
            outputs.append(tr)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def summarize(label: str, trades: pd.DataFrame) -> dict[str, object]:
    if trades.empty:
        return {"label": label, "trades": 0, "pnl": 0.0, "y2023": 0.0, "y2024": 0.0, "win_rate": np.nan}
    return {
        "label": label,
        "trades": int(len(trades)),
        "pnl": float(trades["pnl"].sum()),
        "y2023": float(trades.loc[trades["date"].dt.year.eq(2023), "pnl"].sum()),
        "y2024": float(trades.loc[trades["date"].dt.year.eq(2024), "pnl"].sum()),
        "win_rate": float((trades["pnl"] > 0).mean()),
        "avg_pnl": float(trades["pnl"].mean()),
    }


def main() -> None:
    restricted_rules = infer_restricted_rules()
    all_rules = [restricted_rules.assign(variant="restricted62_inferred")]
    summaries = []
    trade_outputs = []
    for variant in ["profile62_score_top50", "profile62_score_top62", "profile62_score_top100", "profile62_train_q25"]:
        choices, signal_by_rule, trades = run_profile_rules(variant)
        frozen = simulate_frozen_rules(variant, signal_by_rule, restricted_rules)
        all_rules.append(choices.rename(columns={"chosen_rule": "profile_chosen_rule"}))
        summaries.append(summarize(f"{variant}_wfo", trades))
        summaries.append(summarize(f"{variant}_frozen_restricted_rules", frozen))
        if not trades.empty:
            trade_outputs.append(trades.assign(path="wfo"))
        if not frozen.empty:
            trade_outputs.append(frozen.assign(path="frozen_restricted_rules"))
    pd.concat(all_rules, ignore_index=True, sort=False).to_csv(RULES_OUT, index=False)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    if trade_outputs:
        pd.concat(trade_outputs, ignore_index=True, sort=False).to_csv(TRADES_OUT, index=False)
    print("RULES")
    print(pd.concat(all_rules, ignore_index=True, sort=False).to_string(index=False))
    print("SUMMARY")
    print(pd.DataFrame(summaries).to_string(index=False))
    print("WROTE", RULES_OUT, SUMMARY_OUT, TRADES_OUT, flush=True)


if __name__ == "__main__":
    main()
