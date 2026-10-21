from __future__ import annotations

from pathlib import Path
import hashlib

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine


SUMMARY_IN = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_2026-09-09.csv")
EQUITY_IN = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_EQUITY_2026-09-09.csv")
TRADES_IN = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_TRADES_2026-09-09.csv")
DAILY_PX = Path("raits/data/cache/research_daily/databento_ohlcv1d.parquet")

BASELINE_OUT = Path("STOCKS_ONE_ENGINE_BASELINE_FREEZE_2026-09-10.csv")
REGIME_DAILY_OUT = Path("STOCKS_ONE_ENGINE_REGIME_DAILY_2026-09-10.csv")
REGIME_SUMMARY_OUT = Path("STOCKS_ONE_ENGINE_REGIME_SUMMARY_2026-09-10.csv")
SLEEVE_ATTR_OUT = Path("STOCKS_ONE_ENGINE_SLEEVE_ATTRIBUTION_2026-09-10.csv")

LEAD_PORTFOLIOS = ["A_no_ml_all_cap40", "B_no_ml_all_cap40"]

HASH_FILES = [
    Path("raits/research/stocks_one_engine_mtm_portfolio.py"),
    Path("raits/research/stocks_one_engine_direct_no_ml_verify.py"),
    Path("raits/research/stocks_verify_no_ml_generators.py"),
    Path("raits/research/stocks_feature_cache_builder.py"),
    Path("raits/research/stocks_daily_xs_ret5_bottom_h20_full.py"),
    Path("raits/research/stocks_wfo_clean_retest.py"),
    Path("raits/research/stocks_intraday_focused_rule_miner.py"),
    Path("raits/data/cache/stocks_clean_daily_features_CAUSEQA_2026-09-10.pkl"),
    Path("raits/data/cache/stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl"),
    Path("raits/data/cache/stocks_gap_rvol30_features_CAUSEQA_2026-09-10.pkl"),
    SUMMARY_IN,
    EQUITY_IN,
    TRADES_IN,
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_object(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def max_drawdown(values: pd.Series) -> float:
    curve = values.cumsum()
    return float((curve - curve.cummax()).min()) if len(curve) else 0.0


def metrics(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    for keys, group in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        pnl = group["daily_pnl"].astype(float)
        row = dict(zip(group_cols, keys))
        row.update(
            {
                "days": int(len(group)),
                "pnl": float(pnl.sum()),
                "meanDailyPnl": float(pnl.mean()),
                "medianDailyPnl": float(pnl.median()),
                "winDayPct": float((pnl > 0).mean()),
                "maxDrawdownOnSubsetOrder": max_drawdown(pnl),
                "avgGross": float(group["gross"].mean()),
                "maxGross": float(group["gross"].max()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def load_spy_regimes() -> pd.DataFrame:
    spy = pd.read_parquet(DAILY_PX, columns=["symbol", "date", "open", "close"])
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy[spy["symbol"].astype(str).eq("SPY")].copy()
    spy = spy.sort_values("date")
    spy["spy_ret"] = spy["close"].pct_change()
    spy["spy_intraday_ret"] = spy["close"] / spy["open"] - 1.0
    spy["spy_prev_ret"] = spy["spy_ret"].shift(1)
    spy["spy_vol20"] = spy["spy_ret"].rolling(20, min_periods=10).std()
    spy["spy_prev_vol20"] = spy["spy_vol20"].shift(1)
    spy["spy_ma20"] = spy["close"].rolling(20, min_periods=20).mean()
    spy["spy_ma50"] = spy["close"].rolling(50, min_periods=50).mean()
    spy["spy_prev_close"] = spy["close"].shift(1)
    spy["spy_prev_ma20"] = spy["spy_ma20"].shift(1)
    spy["spy_prev_ma50"] = spy["spy_ma50"].shift(1)

    spy["prevSpyBucket"] = pd.cut(
        spy["spy_prev_ret"],
        bins=[-np.inf, -0.01, 0.0, 0.01, np.inf],
        labels=["prevSpy<=-1%", "-1%<prevSpy<=0", "0<prevSpy<=1%", "prevSpy>1%"],
    ).astype("object").fillna("missing")
    spy["sameDaySpyBucket"] = pd.cut(
        spy["spy_intraday_ret"],
        bins=[-np.inf, -0.01, 0.0, 0.01, np.inf],
        labels=["sameSpy<=-1%", "-1%<sameSpy<=0", "0<sameSpy<=1%", "sameSpy>1%"],
    ).astype("object").fillna("missing")
    spy["prevTrendBucket"] = np.select(
        [
            (spy["spy_prev_close"] >= spy["spy_prev_ma20"]) & (spy["spy_prev_ma20"] >= spy["spy_prev_ma50"]),
            (spy["spy_prev_close"] < spy["spy_prev_ma20"]) & (spy["spy_prev_ma20"] < spy["spy_prev_ma50"]),
        ],
        ["prevUpTrend", "prevDownTrend"],
        default="prevMixedTrend",
    )
    spy["prevVolBucket"] = pd.qcut(
        spy["spy_prev_vol20"].rank(method="first"),
        q=3,
        labels=["prevLowVol", "prevMidVol", "prevHighVol"],
    ).astype("object").fillna("missing")
    return spy[
        [
            "date",
            "spy_ret",
            "spy_intraday_ret",
            "spy_prev_ret",
            "spy_prev_vol20",
            "prevSpyBucket",
            "sameDaySpyBucket",
            "prevTrendBucket",
            "prevVolBucket",
        ]
    ]


def write_baseline(summary: pd.DataFrame) -> None:
    rows = []
    for path in HASH_FILES:
        rows.append(
            {
                "kind": "hash",
                "name": str(path).replace("\\", "/"),
                "exists": path.exists(),
                "sha256": sha256(path) if path.exists() else "",
                "gitBlobSha1": hash_object(path) if path.exists() and path.suffix == ".py" else "",
                "portfolio": "",
                "pnl": np.nan,
                "cagr": np.nan,
                "dd": np.nan,
                "sharpe": np.nan,
                "avgGross": np.nan,
                "maxGross": np.nan,
            }
        )
    for _, row in summary[summary["portfolio"].isin(LEAD_PORTFOLIOS)].iterrows():
        rows.append(
            {
                "kind": "headline",
                "name": "clean_no_ml_research_baseline",
                "exists": True,
                "sha256": "",
                "gitBlobSha1": "",
                "portfolio": row["portfolio"],
                "pnl": row["pnl"],
                "cagr": row["cagr"],
                "dd": row["dd"],
                "sharpe": row["sharpe"],
                "avgGross": row["avgGross"],
                "maxGross": row["maxGross"],
            }
        )
    pd.DataFrame(rows).to_csv(BASELINE_OUT, index=False)


def main() -> None:
    summary = pd.read_csv(SUMMARY_IN)
    equity = pd.read_csv(EQUITY_IN, parse_dates=["date"])
    trades = pd.read_csv(TRADES_IN, parse_dates=["date", "planned_exit_date", "exit_date"])

    write_baseline(summary)

    spy = load_spy_regimes()
    daily = equity[equity["portfolio"].isin(LEAD_PORTFOLIOS)].merge(spy, on="date", how="left")
    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.to_period("M").astype(str)
    daily["quarter"] = daily["date"].dt.to_period("Q").astype(str)
    daily.to_csv(REGIME_DAILY_OUT, index=False)

    parts = []
    for cols, label in [
        (["portfolio", "year"], "year"),
        (["portfolio", "month"], "month"),
        (["portfolio", "quarter"], "quarter"),
        (["portfolio", "prevSpyBucket"], "prev_spy_return_causal"),
        (["portfolio", "prevTrendBucket"], "prev_spy_trend_causal"),
        (["portfolio", "prevVolBucket"], "prev_spy_vol20_causal"),
        (["portfolio", "sameDaySpyBucket"], "same_day_spy_attribution"),
    ]:
        part = metrics(daily, cols)
        part.insert(0, "breakdown", label)
        part = part.rename(columns={cols[-1]: "bucket"})
        parts.append(part)
    pd.concat(parts, ignore_index=True).to_csv(REGIME_SUMMARY_OUT, index=False)

    closed = trades[trades["portfolio"].isin(LEAD_PORTFOLIOS) & trades["pnl"].notna()].copy()
    closed["exitYear"] = closed["exit_date"].dt.year
    closed["exitMonth"] = closed["exit_date"].dt.to_period("M").astype(str)
    sleeve = (
        closed.groupby(["portfolio", "sleeve"], dropna=False)
        .agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            meanTradePnl=("pnl", "mean"),
            winTradePct=("pnl", lambda s: float((s > 0).mean())),
            grossNotional=("entry_notional", "sum"),
        )
        .reset_index()
    )
    total = sleeve.groupby("portfolio")["pnl"].transform("sum")
    sleeve["pnlShare"] = sleeve["pnl"] / total
    sleeve.to_csv(SLEEVE_ATTR_OUT, index=False)

    print("WROTE", BASELINE_OUT)
    print("WROTE", REGIME_DAILY_OUT)
    print("WROTE", REGIME_SUMMARY_OUT)
    print("WROTE", SLEEVE_ATTR_OUT)


if __name__ == "__main__":
    main()
