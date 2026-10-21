from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base
import stocks_databento_daily_xs_mtm_dd_overlay as broad_overlay


OUT_PREFIX = "STOCKS_PIT_FULL_QUALITY_UNIVERSE_GATE_NOWARMUP_2026-09-13"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")
PIT_FILTER = base.pit_gate.PIT_FILTER


VARIANTS = {
    "base_full": {"price": 0.0, "adv": 0.0, "vol20": np.inf, "drop_fallback": False},
    "q_p10_adv50_nofb": {"price": 10.0, "adv": 50_000_000.0, "vol20": np.inf, "drop_fallback": True},
    "q_p15_adv50_nofb": {"price": 15.0, "adv": 50_000_000.0, "vol20": np.inf, "drop_fallback": True},
    "q_p10_adv100_nofb": {"price": 10.0, "adv": 100_000_000.0, "vol20": np.inf, "drop_fallback": True},
    "q_p15_adv100_nofb": {"price": 15.0, "adv": 100_000_000.0, "vol20": np.inf, "drop_fallback": True},
    "q_p10_adv50_vol8_nofb": {"price": 10.0, "adv": 50_000_000.0, "vol20": 0.08, "drop_fallback": True},
    "q_p15_adv50_vol8_nofb": {"price": 15.0, "adv": 50_000_000.0, "vol20": 0.08, "drop_fallback": True},
    "q_p15_adv50_vol6_nofb": {"price": 15.0, "adv": 50_000_000.0, "vol20": 0.06, "drop_fallback": True},
    "q_top100adv_p10_nofb": {"price": 10.0, "adv": 0.0, "vol20": np.inf, "drop_fallback": True, "top_adv": 100},
    "q_top200adv_p10_nofb": {"price": 10.0, "adv": 0.0, "vol20": np.inf, "drop_fallback": True, "top_adv": 200},
    "q_top500adv_p10_nofb": {"price": 10.0, "adv": 0.0, "vol20": np.inf, "drop_fallback": True, "top_adv": 500},
    "profile62_train_q10": {"profile": "train_q10"},
    "profile62_train_q25": {"profile": "train_q25"},
    "profile62_score_top50": {"profile": "score_top50"},
    "profile62_score_top62": {"profile": "score_top62"},
    "profile62_score_top75": {"profile": "score_top75"},
    "profile62_score_top100": {"profile": "score_top100"},
    "profile62_score_top200": {"profile": "score_top200"},
}

POLY62_TRADES = Path("STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024_TRADES.csv")


def append_csv(path: Path, rows: dict | list[dict]) -> None:
    data = rows if isinstance(rows, list) else [rows]
    pd.DataFrame(data).to_csv(path, mode="a", header=not path.exists(), index=False)


def completed_variants() -> set[str]:
    if not SUMMARY_OUT.exists():
        return set()
    done = pd.read_csv(SUMMARY_OUT)
    if "variant" not in done:
        return set()
    return set(done["variant"].astype(str))


def add_quality(daily: pd.DataFrame) -> pd.DataFrame:
    pit = pd.read_parquet(PIT_FILTER, columns=["date", "ticker", "prior_close", "adv20", "liquidity_metric_source"])
    pit["date"] = pd.to_datetime(pit["date"])
    pit = pit.drop_duplicates(["date", "ticker"])
    out = daily.merge(pit, on=["date", "ticker"], how="left")
    out = out.sort_values(["ticker", "date"]).copy()
    out["age_obs"] = out.groupby("ticker").cumcount() + 1
    out["adv_pct"] = out.groupby("date")["adv20"].rank(pct=True)
    out["price_pct"] = out.groupby("date")["prior_close"].rank(pct=True)
    out["vol_pct"] = out.groupby("date")["vol20_pre"].rank(pct=True)
    return out


def poly62_tickers() -> set[str]:
    trades = pd.read_csv(POLY62_TRADES, usecols=["portfolio", "ticker"])
    return set(trades[trades["portfolio"].eq("B_polygon62_no_intraday_cap40_PIT")]["ticker"].astype(str).unique())


def profile_params(daily: pd.DataFrame) -> dict[str, float]:
    train = daily[
        daily["ticker"].astype(str).isin(poly62_tickers())
        & daily["date"].dt.year.between(2018, 2020)
        & daily["liquidity_metric_source"].ne("ticker_fallback")
    ].copy()
    if train.empty:
        raise RuntimeError("empty Polygon-62 profile training set")
    return {
        "adv_q10": float(train["adv_pct"].quantile(0.10)),
        "adv_q25": float(train["adv_pct"].quantile(0.25)),
        "adv_med": float(train["adv_pct"].median()),
        "price_q10": float(train["price_pct"].quantile(0.10)),
        "price_q25": float(train["price_pct"].quantile(0.25)),
        "price_med": float(train["price_pct"].median()),
        "vol_q75": float(train["vol_pct"].quantile(0.75)),
        "vol_q90": float(train["vol_pct"].quantile(0.90)),
        "vol_med": float(train["vol_pct"].median()),
        "age_q10": float(train["age_obs"].quantile(0.10)),
        "age_q25": float(train["age_obs"].quantile(0.25)),
        "age_med": float(train["age_obs"].median()),
    }


def quality_mask(daily: pd.DataFrame, cfg: dict[str, object], params: dict[str, float]) -> pd.Series:
    profile = cfg.get("profile")
    if profile == "train_q10":
        return (
            daily["adv_pct"].ge(params["adv_q10"])
            & daily["price_pct"].ge(params["price_q10"])
            & daily["vol_pct"].le(params["vol_q90"])
            & daily["age_obs"].ge(params["age_q10"])
            & daily["liquidity_metric_source"].ne("ticker_fallback")
        ).fillna(False)
    if profile == "train_q25":
        return (
            daily["adv_pct"].ge(params["adv_q25"])
            & daily["price_pct"].ge(params["price_q25"])
            & daily["vol_pct"].le(params["vol_q75"])
            & daily["age_obs"].ge(params["age_q25"])
            & daily["liquidity_metric_source"].ne("ticker_fallback")
        ).fillna(False)
    if profile in {"score_top50", "score_top62", "score_top75", "score_top100", "score_top200"}:
        top_n = {
            "score_top50": 50,
            "score_top62": 62,
            "score_top75": 75,
            "score_top100": 100,
            "score_top200": 200,
        }[str(profile)]
        age_pct = daily.groupby("date")["age_obs"].rank(pct=True)
        score = (
            (daily["adv_pct"] - params["adv_med"]).abs()
            + (daily["price_pct"] - params["price_med"]).abs()
            + (daily["vol_pct"] - params["vol_med"]).abs()
            + (age_pct - 1.0).abs() * 0.5
        )
        score = score.where(daily["liquidity_metric_source"].ne("ticker_fallback"), np.inf)
        score = score.where(daily["prior_close"].ge(5.0), np.inf)
        rank = score.groupby(daily["date"]).rank(method="first", ascending=True)
        return rank.le(top_n).fillna(False)

    mask = (
        daily["prior_close"].ge(float(cfg["price"]))
        & daily["adv20"].ge(float(cfg["adv"]))
        & daily["vol20_pre"].le(float(cfg["vol20"]))
    )
    if bool(cfg["drop_fallback"]):
        mask &= daily["liquidity_metric_source"].ne("ticker_fallback")
    top_adv = cfg.get("top_adv")
    if top_adv is not None:
        rank = daily.groupby("date")["adv20"].rank(method="first", ascending=False)
        mask &= rank.le(int(top_adv))
    return mask.fillna(False)


def build_broad_trades(daily: pd.DataFrame, qmask: pd.Series) -> pd.DataFrame:
    cfg = broad_overlay.config()
    panel = daily.rename(
        columns={
            "ticker": "symbol",
            "open_0930": "open",
            "close_1555": "close",
            "volume_0930": "volume",
        }
    )[["symbol", "date", "open", "close", "volume"]].copy()
    panel["dollar"] = panel["close"] * panel["volume"]
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = panel.groupby("symbol", sort=False)
    panel["adv20"] = g["dollar"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    prev_close = g["close"].shift(1)
    panel["ret5"] = prev_close / g["close"].shift(6) - 1.0
    for hold in [10, 20, 30]:
        panel[f"exit_date{hold}"] = g["date"].shift(-(hold - 1))
    panel["spy_vol20"] = np.nan
    panel = panel[(panel["date"] >= base.START) & (panel["date"] <= base.END)].replace([np.inf, -np.inf], np.nan)

    key_quality = daily.loc[qmask, ["date", "ticker"]].rename(columns={"ticker": "symbol"}).assign(quality_ok=True)
    panel = panel.merge(key_quality, on=["date", "symbol"], how="left")
    panel.loc[~panel["quality_ok"].fillna(False), "ret5"] = np.nan
    _, trades, _ = broad_overlay.broad.simulate(panel, cfg)
    return trades


def build_local_trades(daily: pd.DataFrame, qmask: pd.Series) -> pd.DataFrame:
    data = daily[daily["ticker"].ne("SPY")].sort_values(["ticker", "date"]).copy()
    data["quality_ok"] = qmask.reindex(data.index).fillna(False).astype(bool)
    g = data.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    data["ret5_pre_clean"] = prev_close / g["close_1555"].shift(6) - 1.0
    data["exit_close"] = g["close_1555"].shift(-19)
    data["ret"] = data["exit_close"] / data["open_0930"] - 1.0
    data = data.dropna(subset=["ret5_pre_clean", "ret", "open_0930", "exit_close"]).copy()
    data = data[(data["date"] >= base.START) & (data["date"] <= base.END) & data["quality_ok"]]
    data = data.sort_values(["date", "ret5_pre_clean", "ticker"])
    data["rank"] = data.groupby("date")["ret5_pre_clean"].rank(method="first", ascending=True)
    picks = data[data["rank"] <= 10].copy()
    picks["pnl"] = 200.0 * (picks["ret"] - 0.0004)
    return picks[["date", "ticker", "ret5_pre_clean", "rank", "ret", "pnl"]].reset_index(drop=True)


def build_yday_trades(daily: pd.DataFrame, qmask: pd.Series) -> pd.DataFrame:
    daily_q = daily[qmask].copy()
    pe_signals = base.yday_gen.build_pe_signals(daily_q, set())
    signal_by_rule = {rule.name: base.yday_gen.apply_rule(daily_q, rule) for rule in base.yday_gen.DECLARED_RULE_POOL}
    outputs = []
    for mode in ("anchored", "rolling3"):
        _, trades, _ = base.yday_gen.run_wfo(
            signal_by_rule,
            pe_signals,
            mode=mode,
            test_years=base.yday_gen.DEFAULT_TEST_YEARS,
            include_pe=False,
            start_capital=base.yday_gen.START_CAPITAL,
            position_pct=0.80,
            max_positions=1,
            cost_bps=base.yday_gen.DEFAULT_COST_BPS,
        )
        if not trades.empty:
            outputs.append(trades.assign(wfo_mode=mode))
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def infer_notional(pnl: pd.Series, ret: pd.Series) -> pd.Series:
    out = (pnl.astype(float) / ret.astype(float).replace(0.0, np.nan)).abs()
    med = float(out.replace([np.inf, -np.inf], np.nan).dropna().median()) if out.notna().any() else 0.0
    return out.replace([np.inf, -np.inf], np.nan).fillna(med)


def load_signals(broad: pd.DataFrame, local: pd.DataFrame, yday: pd.DataFrame, daily_px: pd.DataFrame, intraday_px: pd.DataFrame) -> pd.DataFrame:
    exit20 = base.poly.nth_exit_dates(daily_px, 20)
    signals = []

    b = broad.rename(columns={"entry_date": "date", "symbol": "ticker", "planned_exit_date": "exit_date"}).copy()
    b["sleeve"] = "broad_adv10_g2_dd85"
    b["side"] = 1
    b["hold_days"] = 20
    b["entry_style"] = "daily_open"
    b["exit_style"] = "daily_close"
    b["base_notional"] = b["entry_notional"].astype(float)
    b["raw_strength"] = -b["ret5"].astype(float)
    signals.append(b[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    l = local.merge(exit20, on=["date", "ticker"], how="left").rename(columns={"exit_date_20": "exit_date"}).copy()
    l["sleeve"] = "local_xs_full_s10"
    l["side"] = 1
    l["hold_days"] = 20
    l["entry_style"] = "daily_open"
    l["exit_style"] = "daily_close"
    l["base_notional"] = infer_notional(l["pnl"], l["ret"])
    l["raw_strength"] = -l["ret5_pre_clean"].astype(float)
    signals.append(l[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    y = yday[yday["wfo_mode"].eq("rolling3")].copy()
    y["sleeve"] = "yday_ex6_actual"
    y["side"] = 1
    y["hold_days"] = 0
    y["entry_style"] = np.where(y["entry_time"].astype(str).str.contains("09:35"), "entry935", "open930")
    y["exit_style"] = "exit1555"
    y["exit_date"] = y["date"]
    y["base_notional"] = infer_notional(y["pnl"], y["gross_ret"])
    y["raw_strength"] = 1.0
    signals.append(y[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    sig = pd.concat(signals, ignore_index=True)
    sig["date"] = pd.to_datetime(sig["date"])
    sig["exit_date"] = pd.to_datetime(sig["exit_date"])
    sig = sig[(sig["date"] >= base.START) & (sig["date"] <= base.END)]
    sig = sig.dropna(subset=["exit_date", "base_notional", "raw_strength"])
    sig = sig.drop_duplicates(["date", "ticker", "sleeve", "entry_style", "exit_style"])
    sig["strength"] = sig.groupby(["date", "sleeve"])["raw_strength"].rank(pct=True, method="average").fillna(1.0)
    daily_entry = daily_px.rename(columns={"open": "daily_open", "close": "daily_close"})
    sig = sig.merge(daily_entry, on=["date", "ticker"], how="left").merge(intraday_px, on=["date", "ticker"], how="left")
    sig["entry_price"] = np.nan
    sig.loc[sig["entry_style"].eq("daily_open"), "entry_price"] = sig.loc[sig["entry_style"].eq("daily_open"), "daily_open"]
    sig.loc[sig["entry_style"].eq("entry935"), "entry_price"] = sig.loc[sig["entry_style"].eq("entry935"), "entry935"]
    sig.loc[sig["entry_style"].eq("open930"), "entry_price"] = sig.loc[sig["entry_style"].eq("open930"), "open930"]
    sig["exit_price_same_day"] = sig["exit1555"]
    return sig.dropna(subset=["entry_price"])


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
    base.configure_poly()
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = add_quality(daily)
    params = profile_params(daily)
    intraday = pd.read_pickle(base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    daily_px = base.poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    gate = base.pit_gate.load_pit_gate()
    cfg = base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]
    done = completed_variants()

    for variant, vcfg in VARIANTS.items():
        if variant in done:
            print("SKIP", variant, flush=True)
            continue
        qmask = quality_mask(daily, vcfg, params)
        broad = build_broad_trades(daily, qmask)
        local = build_local_trades(daily, qmask)
        yday = build_yday_trades(daily, qmask)
        signals = load_signals(broad, local, yday, daily_px, intraday_px)
        gated_signals, gate_qa, _, _ = base.pit_gate.apply_pit_gate(signals, gate)
        name = f"B_pit_full_quality_universe_{variant}_nowarmup_cap40"
        summary, eq, _ = base.poly.simulate(name, cfg, gated_signals, daily_px)
        summary["variant"] = variant
        summary["quality_rows"] = int(qmask.sum())
        summary["quality_tickers"] = int(daily.loc[qmask, "ticker"].nunique())
        append_csv(SUMMARY_OUT, summary)
        append_csv(YEARLY_OUT, yearly_metrics(variant, eq))
        append_csv(
            SIGNAL_QA_OUT,
            {
                "variant": variant,
                "quality_rows": int(qmask.sum()),
                "quality_tickers": int(daily.loc[qmask, "ticker"].nunique()),
                "broad_rows": int(len(broad)),
                "local_rows": int(len(local)),
                "yday_rows_all_modes": int(len(yday)),
                "yday_rows_rolling3": int((yday["wfo_mode"].eq("rolling3")).sum()) if "wfo_mode" in yday else 0,
                "gate_allowed": int(gate_qa["allowed"].sum()) if "allowed" in gate_qa else np.nan,
                "gate_blocked": int(gate_qa["blocked"].sum()) if "blocked" in gate_qa else np.nan,
            },
        )
        print("VARIANT", variant, summary, flush=True)

    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SIGNAL_QA_OUT, flush=True)


if __name__ == "__main__":
    main()
