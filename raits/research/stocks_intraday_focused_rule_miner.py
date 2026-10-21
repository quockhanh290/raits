from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


CAPITAL = 50_000.0
COST = 0.0004
GROSS = 0.8
YEARS = range(2020, 2025)

OUT = Path("STOCKS_INTRADAY_FOCUSED_RULES_WFO_CAUSEQA_2026-09-10.csv")
TRADES = Path("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_CAUSEQA_2026-09-10.csv")
CHOSEN = Path("STOCKS_INTRADAY_FOCUSED_RULES_CHOSEN_CAUSEQA_2026-09-10.csv")
WFO_COLUMNS = [
    "N",
    "days",
    "pnl",
    "pf",
    "wr",
    "dd",
    "negYears",
    "minYear",
    "y2020",
    "y2021",
    "y2022",
    "y2023",
    "y2024",
    "topTicker",
    "topPnl",
    "topShare",
    "rmTop50",
    "rmTop100",
    "dropSet",
    "dropCount",
]
TRADE_COLUMNS = [
    "date",
    "ticker",
    "year",
    "entry",
    "target",
    "prev_dayret",
    "spy_prev_dayret",
    "gap",
    "first5_ret",
    "rvol",
    "ret3_pre_clean",
    "ret5_pre_clean",
    "ret10_pre_clean",
    "ret20_pre_clean",
    "rule",
    "side",
    "slots",
    "ret",
    "chosen_year",
    "train_score",
    "dropSet",
]


@dataclass(frozen=True)
class Rule:
    entry: str
    name: str
    side: str
    slots: int
    kind: str
    a: float
    b: float | None = None


def add_clean_daily_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values(["ticker", "date"]).copy()
    g = d.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    for n in [3, 5, 10, 20]:
        d[f"ret{n}_pre_clean"] = prev_close / g["close_1555"].shift(n + 1) - 1
    return d


def build_panels() -> pd.DataFrame:
    daily = pd.read_pickle("raits/data/cache/stocks_clean_daily_features_CAUSEQA_2026-09-10.pkl")
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
        "gap",
    ]

    p935 = pd.read_pickle("raits/data/cache/stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl")
    p935["date"] = pd.to_datetime(p935["date"])
    p935 = p935.merge(daily[keep], on=["date", "ticker"], how="left")
    p935 = p935.rename(columns={"ret935_eod": "target", "rvol930": "rvol"})
    p935["entry"] = "0935"

    p1000 = pd.read_pickle("raits/data/cache/stocks_gap_rvol30_features_CAUSEQA_2026-09-10.pkl")
    p1000["date"] = pd.to_datetime(p1000["date"])
    p1000 = p1000.merge(daily[keep], on=["date", "ticker"], how="left")
    if "gap_x" in p1000.columns:
        p1000["gap"] = p1000["gap_x"]
    p1000 = p1000.rename(columns={"ret1000_eod": "target", "rvol30": "rvol"})
    p1000["entry"] = "1000"
    p1000["first5_ret"] = np.nan

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
        "rvol",
        "ret3_pre_clean",
        "ret5_pre_clean",
        "ret10_pre_clean",
        "ret20_pre_clean",
    ]
    return pd.concat([p935[cols], p1000[cols]], ignore_index=True)


def build_rules() -> list[Rule]:
    rules: list[Rule] = []
    slots_set = [20, 10, 5]
    for slots in slots_set:
        for entry in ["0935", "1000"]:
            rules.append(Rule(entry, "gapup_ge_0.03_short", "short", slots, "gapup", 0.03))
            rules.append(Rule(entry, "prevdown_-0.05_spy_down_long", "long", slots, "prevdown_spy", -0.05))
            for rvol in [1.5, 2.0, 3.0, 5.0]:
                for gap in [0.005, 0.01, 0.02]:
                    rules.append(Rule(entry, f"rvol{rvol:g}_gapup{gap:g}_short", "short", slots, "rvol_gapup", rvol, gap))
    return rules


def apply_rule(df: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    x = df[df["entry"].eq(rule.entry)].copy()
    if rule.kind == "gapup":
        x = x[x["gap"] >= rule.a]
        x = x.sort_values(["date", "gap"], ascending=[True, False])
    elif rule.kind == "prevdown_spy":
        x = x[(x["prev_dayret"] <= rule.a) & (x["spy_prev_dayret"] <= 0.0)]
        x = x.sort_values(["date", "prev_dayret"], ascending=[True, True])
    elif rule.kind == "rvol_gapup":
        x = x[(x["rvol"] >= rule.a) & (x["gap"] >= float(rule.b))]
        x = x.sort_values(["date", "gap"], ascending=[True, False])
    else:
        raise ValueError(rule.kind)
    if x.empty:
        return x
    out = x.groupby("date", sort=True, group_keys=False).head(rule.slots).copy()
    out["ret"] = out["target"] if rule.side == "long" else -out["target"]
    out["rule"] = rule.name
    out["side"] = rule.side
    out["slots"] = rule.slots
    out["entry"] = rule.entry
    return out


def metric(tr: pd.DataFrame) -> dict[str, float]:
    if tr.empty:
        return {"N": 0, "days": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0, "negYears": 0, "minYear": 0.0}
    tr = tr.sort_values(["date", "rule", "ticker"]).copy()
    tr["pnl"] = CAPITAL * GROSS / tr.groupby("date")["ticker"].transform("count") * (tr["ret"] - COST)
    pnl = float(tr["pnl"].sum())
    gp = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    gl = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
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
    top = tr.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    pnl = float(tr["pnl"].sum())
    return {
        "topTicker": str(top.index[0]),
        "topPnl": float(top.iloc[0]),
        "topShare": float(top.iloc[0] / pnl) if pnl > 0 else np.nan,
        "rmTop50": pnl - float(tr.nlargest(min(50, len(tr)), "pnl")["pnl"].sum()),
        "rmTop100": pnl - float(tr.nlargest(min(100, len(tr)), "pnl")["pnl"].sum()),
    }


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
            tr = apply_rule(train, rule)
            if len(tr) < 300:
                continue
            st = metric(tr)
            if st["pf"] < 1.08 or st["pnl"] <= 0:
                continue
            score = st["pnl"] / max(1.0, abs(st["dd"])) * np.log1p(st["N"])
            scored.append((score, rule, st))
        tie_preference = {10: 2, 20: 1, 5: 0}
        scored.sort(key=lambda x: (round(float(x[0]), 12), tie_preference.get(x[1].slots, 0)), reverse=True)
        for score, rule, st in scored[:3]:
            tt = apply_rule(test, rule)
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
        trades = trades.sort_values(["date", "rule", "ticker"]).copy()
        trades["pnl"] = CAPITAL * GROSS / trades.groupby("date")["ticker"].transform("count") * (trades["ret"] - COST)
        row = {"dropSet": "+".join(drop) if drop else "FULL", "dropCount": len(drop), **st, **concentration(trades)}
        summaries.append(row)
        all_trades.append(trades.assign(dropSet=row["dropSet"]))
        print(row, flush=True)

    pd.DataFrame(summaries)[WFO_COLUMNS].to_csv(OUT, index=False)
    if all_trades:
        pd.concat(all_trades, ignore_index=True)[TRADE_COLUMNS].to_csv(TRADES, index=False)
    pd.DataFrame(chosen_rows).to_csv(CHOSEN, index=False)
    print("WROTE", OUT, TRADES, CHOSEN)


if __name__ == "__main__":
    main()
