from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


CAPITAL = 50_000.0
COST = 0.0004
GROSS = 0.8
YEARS = range(2020, 2025)
OUT = Path("STOCKS_INTRADAY_RULE_MINER_WFO_2026-09-08.csv")
TRADES = Path("STOCKS_INTRADAY_RULE_MINER_TRADES_2026-09-08.csv")


@dataclass(frozen=True)
class Rule:
    entry: str
    name: str
    side: str
    slots: int
    conds: tuple[tuple[str, str, float], ...]
    rank: tuple[str, str]


def add_clean_daily_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values(["ticker", "date"]).copy()
    g = d.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    for n in [3, 5, 10, 20]:
        d[f"ret{n}_pre_clean"] = prev_close / g["close_1555"].shift(n + 1) - 1
    return d


def op_mask(s: pd.Series, op: str, val: float) -> pd.Series:
    if op == "<=":
        return s <= val
    if op == ">=":
        return s >= val
    raise ValueError(op)


def apply_rule(df: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    for col, op, val in rule.conds:
        m &= op_mask(df[col], op, val)
    x = df.loc[m].copy()
    if x.empty:
        return x
    col, direction = rule.rank
    asc = direction == "asc"
    picks = []
    for _, g in x.groupby("date", sort=True):
        picks.append(g.sort_values(col, ascending=asc).head(rule.slots))
    if not picks:
        return x.iloc[0:0].copy()
    out = pd.concat(picks, ignore_index=True)
    out["ret"] = out["target"] if rule.side == "long" else -out["target"]
    out["rule"] = rule.name
    out["side"] = rule.side
    out["slots"] = rule.slots
    out["entry"] = rule.entry
    return out


def metric(tr: pd.DataFrame, compound: bool = False) -> dict[str, float]:
    if tr.empty:
        return {
            "N": 0,
            "days": 0,
            "pnl": 0.0,
            "pf": 0.0,
            "wr": 0.0,
            "dd": 0.0,
            "negYears": 0,
            "minYear": 0.0,
        }
    tr = tr.sort_values(["date", "rule", "ticker"]).copy()
    if compound:
        cap = CAPITAL
        pnl_parts = []
        for _, g in tr.groupby("date", sort=True):
            weights = GROSS / len(g)
            p = cap * weights * (g["ret"].to_numpy() - COST)
            pnl_parts.extend(p.tolist())
            cap += float(p.sum())
        tr["pnl"] = pnl_parts
    else:
        tr["pnl"] = CAPITAL * GROSS / tr.groupby("date")["ticker"].transform("count") * (tr["ret"] - COST)
    pnl = float(tr["pnl"].sum())
    gp = float(tr.loc[tr.pnl > 0, "pnl"].sum())
    gl = float(-tr.loc[tr.pnl < 0, "pnl"].sum())
    eq = CAPITAL + tr.groupby("date")["pnl"].sum().cumsum()
    years = tr.assign(year=tr["date"].dt.year).groupby("year")["pnl"].sum()
    return {
        "N": int(len(tr)),
        "days": int(tr["date"].nunique()),
        "pnl": pnl,
        "pf": gp / gl if gl > 0 else np.inf,
        "wr": float((tr["pnl"] > 0).mean()),
        "dd": float((eq - eq.cummax()).min()),
        "negYears": int((years < 0).sum()),
        "minYear": float(years.min()) if len(years) else 0.0,
        "y2020": float(years.get(2020, 0.0)),
        "y2021": float(years.get(2021, 0.0)),
        "y2022": float(years.get(2022, 0.0)),
        "y2023": float(years.get(2023, 0.0)),
        "y2024": float(years.get(2024, 0.0)),
    }


def concentration(tr: pd.DataFrame) -> dict[str, float | str]:
    if tr.empty:
        return {"topTicker": "", "topPnl": 0.0, "topShare": np.nan, "rmTop50": 0.0, "rmTop100": 0.0}
    top = tr.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    pnl = float(tr["pnl"].sum())
    return {
        "topTicker": str(top.index[0]),
        "topPnl": float(top.iloc[0]),
        "topShare": float(top.iloc[0] / pnl) if pnl > 0 else np.nan,
        "rmTop50": pnl - float(tr.nlargest(min(50, len(tr)), "pnl")["pnl"].sum()),
        "rmTop100": pnl - float(tr.nlargest(min(100, len(tr)), "pnl")["pnl"].sum()),
    }


def build_panels() -> pd.DataFrame:
    daily = pd.read_pickle("raits/data/cache/stocks_clean_daily_features_2026-09-08.pkl")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = add_clean_daily_features(daily)
    keep = [
        "date",
        "ticker",
        "prev_dayret",
        "spy_prev_dayret",
        "ret3_pre_clean",
        "ret5_pre_clean",
        "ret10_pre_clean",
        "ret20_pre_clean",
        "vol20_pre",
        "gap",
    ]
    intraday = pd.read_pickle("raits/data/cache/stocks_intraday_0935_features_2026-09-08.pkl")
    intraday["date"] = pd.to_datetime(intraday["date"])
    p935 = intraday.merge(daily[keep], on=["date", "ticker"], how="left")
    p935 = p935.rename(columns={"ret935_eod": "target"})
    p935["entry"] = "0935"
    p935["rvol30"] = np.nan

    p1000 = pd.read_pickle("raits/data/cache/stocks_gap_rvol30_features_2026-09-08.pkl")
    p1000["date"] = pd.to_datetime(p1000["date"])
    p1000 = p1000.merge(daily[keep], on=["date", "ticker"], how="left")
    if "gap_x" in p1000.columns:
        p1000["gap"] = p1000["gap_x"]
    p1000 = p1000.rename(columns={"ret1000_eod": "target"})
    p1000["entry"] = "1000"
    p1000["first5_ret"] = np.nan
    p1000["rvol930"] = np.nan

    cols = [
        "date",
        "ticker",
        "year",
        "entry",
        "target",
        "prev_dayret",
        "spy_prev_dayret",
        "gap",
        "first5_ret",
        "rvol930",
        "rvol30",
        "ret3_pre_clean",
        "ret5_pre_clean",
        "ret10_pre_clean",
        "ret20_pre_clean",
        "vol20_pre",
    ]
    return pd.concat([p935[cols], p1000[cols]], ignore_index=True)


def build_rules() -> list[Rule]:
    rules: list[Rule] = []
    thresholds = {
        "prev_dayret": [-0.05, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.05],
        "gap": [-0.03, -0.02, -0.01, -0.005, 0.005, 0.01, 0.02, 0.03],
        "first5_ret": [-0.02, -0.01, -0.005, 0.005, 0.01, 0.02],
        "rvol930": [1.5, 2.0, 3.0, 5.0],
        "rvol30": [1.5, 2.0, 3.0, 5.0],
        "spy_prev_dayret": [-0.01, -0.005, 0.0, 0.005, 0.01],
        "ret5_pre_clean": [-0.08, -0.05, -0.03, 0.03, 0.05, 0.08],
    }
    slots_set = [5, 10, 20]

    for entry in ["0935", "1000"]:
        entry_rvol = "rvol930" if entry == "0935" else "rvol30"
        entry_rank_cols = ["prev_dayret", "gap", "ret5_pre_clean", entry_rvol]
        if entry == "0935":
            entry_rank_cols.append("first5_ret")
        for slots in slots_set:
            for side in ["long", "short"]:
                for col, vals in thresholds.items():
                    if col == "first5_ret" and entry != "0935":
                        continue
                    if col == "rvol930" and entry != "0935":
                        continue
                    if col == "rvol30" and entry != "1000":
                        continue
                    for val in vals:
                        ops = ["<=", ">="] if val != 0 else ["<=", ">="]
                        for op in ops:
                            for rank_col in entry_rank_cols:
                                for rank_dir in ["asc", "desc"]:
                                    name = f"{entry}_{side}_{slots}_{col}{op}{val:g}_rank{rank_col}_{rank_dir}"
                                    rules.append(Rule(entry, name, side, slots, ((col, op, val),), (rank_col, rank_dir)))

                # Two-condition panic/confirmation shapes.
                for gap_op, gap_val in [("<=", -0.01), ("<=", -0.02), (">=", 0.01), (">=", 0.02)]:
                    for spy_op, spy_val in [("<=", 0.0), ("<=", -0.005), (">=", 0.0)]:
                        for rank_col in entry_rank_cols:
                            name = f"{entry}_{side}_{slots}_gap{gap_op}{gap_val:g}_spy{spy_op}{spy_val:g}_rank{rank_col}_asc"
                            rules.append(
                                Rule(entry, name, side, slots, (("gap", gap_op, gap_val), ("spy_prev_dayret", spy_op, spy_val)), (rank_col, "asc"))
                            )
                if entry == "0935":
                    for fop, fval in [("<=", -0.005), ("<=", -0.01), (">=", 0.005), (">=", 0.01)]:
                        for gap_op, gap_val in [("<=", -0.005), (">=", 0.005)]:
                            for rank_col in ["first5_ret", "gap", "prev_dayret"]:
                                name = f"{entry}_{side}_{slots}_f5{fop}{fval:g}_gap{gap_op}{gap_val:g}_rank{rank_col}_asc"
                                rules.append(
                                    Rule(entry, name, side, slots, (("first5_ret", fop, fval), ("gap", gap_op, gap_val)), (rank_col, "asc"))
                                )
    return rules


def run(drop: tuple[str, ...]) -> tuple[list[dict[str, object]], pd.DataFrame]:
    panel = build_panels()
    panel = panel[~panel["ticker"].isin(drop)].dropna(subset=["target", "prev_dayret", "spy_prev_dayret", "gap"])
    rules = build_rules()
    out_trades = []
    chosen = []
    for year in YEARS:
        train = panel[(panel["year"] >= 2017) & (panel["year"] <= year - 1)]
        test = panel[panel["year"] == year]
        scored = []
        for rule in rules:
            tr = apply_rule(train[train["entry"] == rule.entry], rule)
            if len(tr) < 300 or tr["date"].nunique() < 120:
                continue
            st = metric(tr)
            if st["pf"] < 1.08 or st["pnl"] <= 0:
                continue
            score = st["pnl"] / max(1.0, abs(st["dd"])) * np.log1p(st["N"])
            scored.append((score, rule, st))
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, rule, st in scored[:3]:
            tt = apply_rule(test[test["entry"] == rule.entry], rule)
            if tt.empty:
                continue
            tt["chosen_year"] = year
            tt["train_score"] = score
            out_trades.append(tt)
            chosen.append(
                {
                    "dropSet": "+".join(drop) if drop else "FULL",
                    "year": year,
                    "rule": rule.name,
                    "entry": rule.entry,
                    "side": rule.side,
                    "slots": rule.slots,
                    "trainN": st["N"],
                    "trainPnl": st["pnl"],
                    "trainPf": st["pf"],
                    "trainDd": st["dd"],
                    "trainScore": score,
                }
            )
    if not out_trades:
        return chosen, pd.DataFrame()
    trades = pd.concat(out_trades, ignore_index=True)
    # Deduplicate cases where top WFO rules select the same ticker/day/entry/side.
    trades = trades.sort_values(["date", "ticker", "entry", "side", "train_score"], ascending=[True, True, True, True, False])
    trades = trades.drop_duplicates(["date", "ticker", "entry", "side"])
    return chosen, trades


def main() -> None:
    drops = [
        (),
        ("META", "TSLA", "NVDA", "AMD", "BA", "NFLX"),
        ("META", "TSLA", "NVDA", "AMD", "BA", "NFLX", "DE", "CVX", "ADBE", "PYPL"),
    ]
    summaries = []
    all_trades = []
    chosen_rows = []
    for drop in drops:
        chosen, trades = run(drop)
        chosen_rows.extend(chosen)
        if trades.empty:
            continue
        st = metric(trades)
        # attach p&l using fixed-cap per-day aggregation for concentration.
        trades = trades.sort_values(["date", "rule", "ticker"]).copy()
        trades["pnl"] = CAPITAL * GROSS / trades.groupby("date")["ticker"].transform("count") * (trades["ret"] - COST)
        conc = concentration(trades)
        row = {"dropSet": "+".join(drop) if drop else "FULL", "dropCount": len(drop), **st, **conc}
        summaries.append(row)
        all_trades.append(trades.assign(dropSet=row["dropSet"]))
        print(row)

    summary = pd.DataFrame(summaries)
    summary.to_csv(OUT, index=False)
    if all_trades:
        pd.concat(all_trades, ignore_index=True).to_csv(TRADES, index=False)
    pd.DataFrame(chosen_rows).to_csv("STOCKS_INTRADAY_RULE_MINER_CHOSEN_2026-09-08.csv", index=False)
    print("WROTE", OUT, TRADES)


if __name__ == "__main__":
    main()
