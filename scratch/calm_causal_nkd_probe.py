from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes
from global_index._core import load_parquet
from global_index.specs import SPECS


DATA_PATH = Path("global_index/data/NKD_continuous_1m_8y.parquet")
SPY_CSV = "spy_daily_live.csv"
TZ = "Asia/Tokyo"
TRAIN_END = "2018-01-01"
FIT_IS = "2022-12-31"
FIT_OOS = "2024-12-31"
OUT_PREFIX = Path("scratch/calm_causal_nkd_probe")


def cost_per_round_turn(slippage_ticks_per_side: float = 2.0) -> float:
    c = SPECS["MNKD"]
    return c.commission_rt + 2.0 * slippage_ticks_per_side * c.tick_value


def nkd_day_sessions(df: pd.DataFrame) -> pd.DataFrame:
    local = df.tz_convert(TZ).copy()
    day_bars = local.between_time("09:00", "15:59").copy()
    day_bars["day"] = pd.to_datetime(day_bars.index.date)
    rows: list[dict] = []

    for day, g in day_bars.groupby("day", sort=True):
        if g.empty:
            continue
        at_0900 = g[g.index.time >= pd.Timestamp("09:00").time()]
        at_1000 = g[g.index.time >= pd.Timestamp("10:00").time()]
        at_1400 = g[g.index.time >= pd.Timestamp("14:00").time()]
        at_1555 = g[g.index.time >= pd.Timestamp("15:55").time()]
        if at_0900.empty or at_1000.empty or at_1400.empty or at_1555.empty:
            continue

        o = float(at_0900.iloc[0]["open"])
        h = float(g["high"].max())
        l = float(g["low"].min())
        c = float(g.iloc[-1]["close"])
        rng = h - l
        rows.append(
            {
                "day": pd.Timestamp(day).normalize(),
                "session_start": at_0900.index[0],
                "entry_1000_ts": at_1000.index[0],
                "entry_1000_price": float(at_1000.iloc[0]["open"]),
                "entry_1400_ts": at_1400.index[0],
                "entry_1400_price": float(at_1400.iloc[0]["open"]),
                "exit_1555_ts": at_1555.index[0],
                "exit_1555_price": float(at_1555.iloc[0]["open"]),
                "rth_open": o,
                "rth_high": h,
                "rth_low": l,
                "rth_close": c,
                "rth_ret": c / o - 1.0 if o else np.nan,
                "rth_range_pct": rng / o if o else np.nan,
                "body_to_range": abs(c - o) / rng if rng > 0 else np.nan,
                "close_loc": (c - l) / rng if rng > 0 else np.nan,
            }
        )

    out = pd.DataFrame(rows).sort_values("day").reset_index(drop=True)
    for col in [
        "day",
        "rth_open",
        "rth_high",
        "rth_low",
        "rth_close",
        "rth_ret",
        "rth_range_pct",
        "body_to_range",
        "close_loc",
    ]:
        out[f"prev_{col}"] = out[col].shift(1)

    denom = out["prev_rth_high"] - out["prev_rth_low"]
    out["gap_from_prev_rth_close"] = out["rth_open"] / out["prev_rth_close"] - 1.0
    out["open_loc_prev_range"] = (out["rth_open"] - out["prev_rth_low"]) / denom
    return out.dropna(subset=["prev_day", "prev_rth_close", "prev_close_loc"]).copy()


def causal_regime_map(fit_end: str) -> pd.DataFrame:
    bench = benchmark_daily(SPY_CSV)
    labels = pd.Series(label_regimes(bench, TRAIN_END, 3, fit_end), name="regime")
    idx = pd.DatetimeIndex(labels.index)
    labels.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    closes = pd.DatetimeIndex(
        [pd.Timestamp(d).tz_localize("America/New_York") + pd.Timedelta(hours=16) for d in labels.index]
    )
    return pd.DataFrame({"spy_day": labels.index, "spy_close_ts": closes, "regime": labels.to_numpy()})


def add_causal_regime(sessions: pd.DataFrame, fit_end: str) -> pd.DataFrame:
    regimes = causal_regime_map(fit_end)
    close_ts = regimes["spy_close_ts"].to_numpy()
    spy_days = regimes["spy_day"].to_numpy()
    labels = regimes["regime"].to_numpy()
    regime_feature_days = []
    regime_vals = []
    violations = []

    for ts in sessions["session_start"]:
        ts_et = pd.Timestamp(ts).tz_convert("America/New_York")
        pos = np.searchsorted(close_ts, ts_et, side="right") - 1
        if pos < 0:
            regime_feature_days.append(pd.NaT)
            regime_vals.append(None)
            violations.append(1)
            continue
        regime_feature_days.append(pd.Timestamp(spy_days[pos]).normalize())
        regime_vals.append(labels[pos])
        violations.append(1 if pd.Timestamp(close_ts[pos]) > ts_et else 0)

    out = sessions.copy()
    out["regime_feature_day"] = regime_feature_days
    out["regime"] = regime_vals
    out["regime_after_entry"] = violations
    return out.dropna(subset=["regime"]).copy()


def trade_rows(sessions: pd.DataFrame, entry: str, direction: str, mask: pd.Series, variant: str) -> pd.DataFrame:
    entry_ts_col = f"entry_{entry}_ts"
    entry_px_col = f"entry_{entry}_price"
    side = 1.0 if direction == "LONG" else -1.0
    c = SPECS["MNKD"]
    cost = cost_per_round_turn(2.0)
    rows = []
    for _, r in sessions[mask.fillna(False)].iterrows():
        entry_ts = pd.Timestamp(r[entry_ts_col])
        exit_ts = pd.Timestamp(r["exit_1555_ts"])
        signal_last_ts = pd.Timestamp(r["session_start"])
        gross = side * (float(r["exit_1555_price"]) - float(r[entry_px_col])) * c.point_value
        rows.append(
            {
                "variant": variant,
                "day": pd.Timestamp(r["day"]).date().isoformat(),
                "year": int(pd.Timestamp(r["day"]).year),
                "inst": "MNKD",
                "direction": direction,
                "entry_time": entry_ts.isoformat(),
                "entry_price": float(r[entry_px_col]),
                "exit_time": exit_ts.isoformat(),
                "exit_price": float(r["exit_1555_price"]),
                "gross_pnl": gross,
                "pnl": gross - cost,
                "regime": r["regime"],
                "regime_feature_day": pd.Timestamp(r["regime_feature_day"]).date().isoformat(),
                "prev_session_day": pd.Timestamp(r["prev_day"]).date().isoformat(),
                "prev_rth_ret": float(r["prev_rth_ret"]),
                "prev_close_loc": float(r["prev_close_loc"]),
                "gap_from_prev_rth_close": float(r["gap_from_prev_rth_close"]),
                "open_loc_prev_range": float(r["open_loc_prev_range"]),
                "outside_exit_bar": 0,
                "outside_entry_bar": 0,
                "signal_after_entry": 1 if signal_last_ts >= entry_ts else 0,
                "regime_after_entry": int(r["regime_after_entry"]),
            }
        )
    return pd.DataFrame(rows)


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "win_rate": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return {
        "n": int(len(df)),
        "days": int(df["day"].nunique()),
        "net": float(pnl.sum()),
        "pf": float(wins.sum() / -losses.sum()) if len(losses) else math.inf,
        "avg": float(pnl.mean()),
        "win_rate": float((pnl > 0).mean()),
        "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0,
    }


def summarize(trades: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    if trades.empty:
        return pd.DataFrame()
    for variant, g in trades.groupby("variant", sort=True):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        audit = int(g[["outside_exit_bar", "outside_entry_bar", "signal_after_entry", "regime_after_entry"]].sum().sum())
        rows.append(
            {
                "window": window,
                "variant": variant,
                **st,
                "pos_years": int((by_year > 0).sum()),
                "years": int(len(by_year)),
                "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and len(by_year) else 1.0,
                "audit": audit,
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def build_variants(sessions: pd.DataFrame) -> pd.DataFrame:
    calm = sessions["regime"].eq("Calm")
    rows = []

    base_bottom_down = calm & (sessions["prev_close_loc"] <= (1.0 / 3.0)) & (sessions["prev_rth_ret"] < 0)
    base_openloc = calm & (sessions["open_loc_prev_range"] <= (1.0 / 3.0))
    neg_gap = calm & (sessions["gap_from_prev_rth_close"] > -0.010) & (sessions["gap_from_prev_rth_close"] <= -0.001)
    not_deep = sessions["gap_from_prev_rth_close"] >= -0.010

    specs = [
        ("lagcalm_nkd_pcloc_bottom_down_long_e1000_x1555", "1000", "LONG", base_bottom_down),
        ("lagcalm_nkd_pcloc_bottom_down_long_e1000_x1555__not_deep_gap", "1000", "LONG", base_bottom_down & not_deep),
        ("lagcalm_nkd_pcloc_bottom_down_long_e1400_x1555", "1400", "LONG", base_bottom_down),
        ("lagcalm_nkd_pcloc_bottom_down_long_e1400_x1555__not_deep_gap", "1400", "LONG", base_bottom_down & not_deep),
        ("lagcalm_nkd_pcloc_bottom_down_short_e1000_x1555", "1000", "SHORT", base_bottom_down),
        ("lagcalm_nkd_pcloc_bottom_down_short_e1000_x1555__not_deep_gap", "1000", "SHORT", base_bottom_down & not_deep),
        ("lagcalm_nkd_pcloc_bottom_down_short_e1400_x1555", "1400", "SHORT", base_bottom_down),
        ("lagcalm_nkd_pcloc_bottom_down_short_e1400_x1555__not_deep_gap", "1400", "SHORT", base_bottom_down & not_deep),
        ("lagcalm_nkd_openloc_bottom_long_e1000_x1555", "1000", "LONG", base_openloc),
        ("lagcalm_nkd_openloc_bottom_long_e1000_x1555__not_deep_gap", "1000", "LONG", base_openloc & not_deep),
        ("lagcalm_nkd_openloc_bottom_short_e1000_x1555", "1000", "SHORT", base_openloc),
        ("lagcalm_nkd_openloc_bottom_short_e1000_x1555__not_deep_gap", "1000", "SHORT", base_openloc & not_deep),
        ("lagcalm_nkd_neg_gap_fade_long_e1000_x1555", "1000", "LONG", neg_gap),
        ("lagcalm_nkd_neg_gap_fade_long_e1400_x1555", "1400", "LONG", neg_gap),
        ("lagcalm_nkd_neg_gap_break_short_e1000_x1555", "1000", "SHORT", neg_gap),
        ("lagcalm_nkd_neg_gap_break_short_e1400_x1555", "1400", "SHORT", neg_gap),
    ]
    for name, entry, direction, mask in specs:
        rows.append(trade_rows(sessions, entry, direction, mask, name))
    return pd.concat([r for r in rows if not r.empty], ignore_index=True) if rows else pd.DataFrame()


def window_run(df: pd.DataFrame, start: str, end: str, fit_end: str, name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sessions = nkd_day_sessions(df)
    sessions = sessions[(sessions["day"] >= pd.Timestamp(start)) & (sessions["day"] <= pd.Timestamp(end))].copy()
    sessions = add_causal_regime(sessions, fit_end)
    trades = build_variants(sessions)
    trades["window"] = name
    summary = summarize(trades, name)
    return trades, summary


def print_table(title: str, summary: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if summary.empty:
        print("NO TRADES")
        return
    for _, r in summary.iterrows():
        print(
            f"{r['variant']:<62} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"wr={100*r['win_rate']:>5.1f}% dd=${r['maxdd']:>7,.0f} "
            f"posY={int(r['pos_years'])}/{int(r['years'])} audit={int(r['audit'])}"
        )


def main() -> int:
    df = load_parquet(str(DATA_PATH))
    is_trades, is_summary = window_run(df, "2018-01-01", "2024-12-31", FIT_IS, "IS_2018_2024")
    print_table("NKD Calm IS 2018-2024", is_summary)

    selected = is_summary[
        (is_summary["n"] >= 80)
        & (is_summary["net"] >= 1500)
        & (is_summary["pf"] >= 1.15)
        & (is_summary["pos_years"] >= 4)
        & (is_summary["audit"] == 0)
    ]["variant"].head(4).tolist()
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))

    o25_trades, o25_summary = window_run(df, "2025-01-01", "2025-12-31", FIT_OOS, "OOS_2025")
    o26_trades, o26_summary = window_run(df, "2026-01-01", "2026-08-19", FIT_OOS, "SANITY_2026")
    if selected:
        print_table("NKD Calm 2025 selected", o25_summary[o25_summary["variant"].isin(selected)])
        print_table("NKD Calm 2026 selected", o26_summary[o26_summary["variant"].isin(selected)])
    else:
        print_table("NKD Calm 2025 top", o25_summary.head(8))
        print_table("NKD Calm 2026 top", o26_summary.head(8))

    all_trades = pd.concat([is_trades, o25_trades, o26_trades], ignore_index=True)
    all_summary = pd.concat([is_summary, o25_summary, o26_summary], ignore_index=True)
    all_trades.to_csv(f"{OUT_PREFIX}_trades.csv", index=False)
    all_summary.to_csv(f"{OUT_PREFIX}_summary.csv", index=False)
    if selected:
        pd.concat([is_trades, o25_trades, o26_trades], ignore_index=True).query("variant in @selected").to_csv(
            f"{OUT_PREFIX}_selected_trades.csv", index=False
        )
    print(f"\nwrote {OUT_PREFIX}_trades.csv")
    print(f"wrote {OUT_PREFIX}_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
