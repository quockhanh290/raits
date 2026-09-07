from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, backtest_swing_tf
from global_index._core import FuturesCost, load_parquet
from global_index.regime import RegimeLabels
from global_index.specs import SPECS


DATA_PATH = "global_index/data/NKD_continuous_1m_8y.parquet"
SPY_CSV = "spy_daily_live.csv"
TRAIN_END = "2018-01-01"
FIT_IS = "2022-12-31"
FIT_OOS = "2024-12-31"
OUT_PREFIX = Path("scratch/calm_nkd_swing_calm_only")


class D1CalmAsNormalLabels:
    """Expose only D-1 Calm days to SwingTF.

    SwingTF's signal generator is not configured to trade the literal "Calm"
    regime. This wrapper keeps the gate causal and Calm-only, then presents
    allowed days as "Normal" so the existing NKD signal can be measured.
    """

    def __init__(self, spy_regime: pd.Series):
        self.base = RegimeLabels(spy_regime, lag_days=1)

    def get(self, day, default=None):
        regime = self.base.get(day, default=None)
        return "Normal" if regime == "Calm" else default


def spy_regime(fit_end: str) -> pd.Series:
    s = pd.Series(label_regimes(benchmark_daily(SPY_CSV), TRAIN_END, 3, fit_end))
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return s.sort_index()


def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "win_rate": 0.0, "maxdd": 0.0, "pos_years": 0, "years": 0}
    df = pd.DataFrame(trades)
    pnl = df["pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    entry_day = pd.to_datetime(df["day"]).dt.tz_localize(None).dt.normalize()
    exit_day = pd.to_datetime(df["exit_day"]).dt.tz_localize(None).dt.normalize()
    daily = df.assign(exit_day_norm=exit_day).groupby("exit_day_norm")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    years = df.assign(entry_year=entry_day.dt.year).groupby("entry_year")["pnl"].sum()
    return {
        "n": int(len(df)),
        "net": float(pnl.sum()),
        "pf": float(wins.sum() / -losses.sum()) if len(losses) else math.inf,
        "avg": float(pnl.mean()),
        "win_rate": float((pnl > 0).mean()),
        "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0,
        "pos_years": int((years > 0).sum()),
        "years": int(len(years)),
    }


def run_window(raw: pd.DataFrame, start: str, end: str, fit_end: str, window: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = SPECS["MNKD"]
    df = raw[
        (raw.index >= pd.Timestamp(start).tz_localize(c.session_tz))
        & (raw.index <= pd.Timestamp(end).tz_localize(c.session_tz) + pd.Timedelta(days=1))
    ]
    labels = D1CalmAsNormalLabels(spy_regime(fit_end))
    cost = FuturesCost(
        point_value=c.point_value,
        tick=c.tick,
        commission_rt=c.commission_rt,
        slippage_ticks_per_side=2.0,
    )
    rows = []
    trades_out = []
    params = [(5, 2.5), (10, 2.0), (10, 2.5), (10, 3.0), (15, 2.5), (20, 2.5)]
    for ema, mult in params:
        variant = f"nkd_swing_d1calm_as_normal_ema{ema}_mult{mult:g}"
        trades = backtest_swing_tf(
            df,
            labels,
            cost,
            ema_period=ema,
            chandelier_atr_mult=mult,
            max_hold_days=5,
            gap_fill=True,
        )
        for trade in trades:
            out = dict(trade)
            out["window"] = window
            out["variant"] = variant
            out["inst"] = "MNKD"
            out["regime_gate"] = "D1_Calm"
            out["outside_exit_bar"] = 0
            out["outside_entry_bar"] = 0
            out["signal_after_entry"] = 0
            trades_out.append(out)
        rows.append({"window": window, "variant": variant, **stats(trades)})
    summary = pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)
    trades_df = pd.DataFrame(trades_out)
    return trades_df, summary


def print_table(title: str, summary: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    for _, r in summary.iterrows():
        print(
            f"{r['variant']:<45} n={int(r['n']):>4} net=${r['net']:>8,.0f} "
            f"pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} wr={100*r['win_rate']:>5.1f}% "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])}"
        )


def main() -> int:
    c = SPECS["MNKD"]
    raw = load_parquet(DATA_PATH).tz_convert(c.session_tz)
    runs = [
        ("2018-01-01", "2024-12-31", FIT_IS, "IS_2018_2024"),
        ("2025-01-01", "2025-12-31", FIT_OOS, "OOS_2025"),
        ("2026-01-01", "2026-08-19", FIT_OOS, "SANITY_2026"),
    ]
    all_trades = []
    all_summaries = []
    for start, end, fit_end, window in runs:
        trades, summary = run_window(raw, start, end, fit_end, window)
        all_trades.append(trades)
        all_summaries.append(summary)
        print_table(window, summary)

    pd.concat(all_summaries, ignore_index=True).to_csv(f"{OUT_PREFIX}_summary.csv", index=False)
    pd.concat(all_trades, ignore_index=True).to_csv(f"{OUT_PREFIX}_trades.csv", index=False)
    print(f"\nwrote {OUT_PREFIX}_summary.csv")
    print(f"wrote {OUT_PREFIX}_trades.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
