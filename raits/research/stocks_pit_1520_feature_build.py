from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
ELIGIBLE = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
RAW = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
OUTPUT_DIR = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022")
OUTPUT = OUTPUT_DIR / "causal_features_pre1520.parquet"
MANIFEST = OUTPUT_DIR / "causal_features_pre1520_manifest.json"
START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2022-12-30")
TOP_N = 500
MIN_ADV = 10_000_000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "_")


def build_panel() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    daily = pd.read_pickle(DAILY)[
        ["date", "ticker", "open_0930", "prev_close_1555", "gap", "ret20_pre", "ret60_pre", "vol20_pre"]
    ].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[daily["date"].between(START, END)].copy()
    sessions = sorted(daily["date"].drop_duplicates())
    next_session = {date: sessions[i + 1] for i, date in enumerate(sessions[:-1])}
    daily["next_date"] = daily["date"].map(next_session)
    daily = daily[daily["next_date"].notna() & daily["next_date"].le(END)].copy()

    caps = pd.read_csv(CAPS, low_memory=False)
    caps["snapshot_date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["snapshot_date", "market_cap", "ticker"], ascending=[True, False, True])
    caps["rank"] = caps.groupby("snapshot_date")["market_cap"].rank(method="first", ascending=False)
    members = caps[caps["rank"].le(TOP_N)][
        ["snapshot_date", "ticker", "market_cap", "sic_description"]
    ].copy()
    members["sic_description"] = members["sic_description"].fillna("UNKNOWN").astype(str)
    assigned = pd.merge_asof(
        pd.DataFrame({"date": sessions}),
        members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date"),
        left_on="date",
        right_on="snapshot_date",
        direction="backward",
    )
    panel = daily.merge(assigned, on="date", how="inner", validate="many_to_one")
    panel = panel.merge(members, on=["snapshot_date", "ticker"], how="inner", validate="many_to_one")

    eligible = pd.read_parquet(
        ELIGIBLE,
        columns=["date", "ticker", "adv20"],
        filters=[("date", ">=", START.date()), ("date", "<=", END.date()), ("eligible_final", "==", True)],
    )
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    eligible = eligible.groupby(["date", "ticker"], as_index=False)["adv20"].min()
    panel = panel.merge(eligible, on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel[
        panel["adv20"].ge(MIN_ADV)
        & panel["open_0930"].ge(5.0)
        & panel["prev_close_1555"].ge(5.0)
        & panel["gap"].abs().le(0.30)
    ].copy()
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True), sessions


def raw_path(ticker: str, month: str) -> Path:
    safe = safe_symbol(ticker)
    return RAW / safe / f"{safe}_5m_{month}.parquet"


def process_ticker(item: tuple[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, object]]:
    ticker, panel = item
    months = sorted(set(panel["date"].dt.strftime("%Y-%m")) | set(panel["next_date"].dt.strftime("%Y-%m")))
    frames = []
    missing_files = 0
    for month in months:
        path = raw_path(ticker, month)
        if not path.exists() or path.stat().st_size == 0:
            missing_files += 1
            continue
        raw = pd.read_parquet(path, columns=["open", "high", "low", "close", "volume", "vwap", "transactions"]).reset_index()
        raw["date"] = raw["timestamp"].dt.normalize()
        raw["clock"] = raw["timestamp"].dt.strftime("%H:%M")
        frames.append(raw)
    if not frames:
        return pd.DataFrame(), {"ticker": ticker, "planned": len(panel), "built": 0, "missing_files": missing_files}
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(["timestamp"], keep="last")
    raw = raw.sort_values("timestamp").reset_index(drop=True)
    raw["bar_dollar"] = raw["volume"].astype(float) * raw["vwap"].fillna(raw["close"]).astype(float)

    signal = raw[(raw["clock"] >= "09:30") & (raw["clock"] < "15:20")].copy()
    signal["ema20"] = signal.groupby("date", sort=False)["close"].transform(
        lambda values: values.ewm(span=20, adjust=False).mean()
    )
    signal["avg_vol10_prior"] = signal.groupby("date", sort=False)["volume"].transform(
        lambda values: values.rolling(10).mean().shift(1)
    )
    aggregate = signal.groupby("date", as_index=False).agg(
        signal_open_0930=("open", "first"),
        signal_close_1520=("close", "last"),
        signal_dollar=("bar_dollar", "sum"),
        signal_bars=("clock", "size"),
        first_clock=("clock", "first"),
        last_clock=("clock", "last"),
    )
    aggregate = aggregate[aggregate["first_clock"].eq("09:30") & aggregate["last_clock"].eq("15:15")]

    def exact(clock: str, fields: dict[str, str]) -> pd.DataFrame:
        selected = raw[raw["clock"].eq(clock)][["date", *fields]].copy()
        return selected.rename(columns=fields).drop_duplicates("date", keep="last")

    entry = exact("15:20", {"open": "entry_price_1520"})
    late = exact("14:20", {"open": "late_open_1420"})
    pullback = signal[signal["clock"].eq("15:10")][
        ["date", "close", "volume", "ema20", "avg_vol10_prior"]
    ].rename(columns={"close": "pullback_close", "volume": "pullback_volume", "ema20": "ema20_pre1520"})
    resume = signal[signal["clock"].eq("15:15")][["date", "close", "volume"]].rename(
        columns={"close": "resume_close", "volume": "resume_volume"}
    )

    def future_exit(clock: str, price_name: str, clock_name: str, date_name: str) -> pd.DataFrame:
        hour, minute = (int(value) for value in clock.split(":"))
        schedule = panel[["date", "next_date"]].copy()
        schedule["scheduled_timestamp"] = schedule["next_date"] + pd.Timedelta(hours=hour, minutes=minute)
        points = raw[["timestamp", "date", "clock", "open"]].sort_values("timestamp").rename(
            columns={"date": date_name, "clock": clock_name, "open": price_name}
        )
        merged = pd.merge_asof(
            schedule.sort_values("scheduled_timestamp"),
            points,
            left_on="scheduled_timestamp",
            right_on="timestamp",
            direction="forward",
            tolerance=pd.Timedelta(days=5),
        )
        return merged[["date", price_name, clock_name, date_name, "timestamp"]].rename(
            columns={"timestamp": f"{price_name}_timestamp"}
        )

    overnight = future_exit("09:35", "exit_0935", "exit_0935_clock", "exit_0935_date")
    next1520 = future_exit("15:20", "exit_1520_next", "exit_1520_next_clock", "exit_1520_next_date")

    result = panel.merge(aggregate, on="date", how="inner", validate="one_to_one")
    for frame in (entry, late, pullback, resume):
        result = result.merge(frame, on="date", how="inner", validate="one_to_one")
    result = result.merge(overnight, on="date", how="left", validate="one_to_one")
    result = result.merge(next1520, on="date", how="left", validate="one_to_one")
    result["intraday_return"] = result["signal_close_1520"] / result["signal_open_0930"] - 1.0
    result["late_return"] = result["signal_close_1520"] / result["late_open_1420"] - 1.0
    result["volume_ratio"] = result["signal_dollar"] / (result["adv20"] * (70.0 / 78.0))
    result["pullback_distance"] = (result["pullback_close"] - result["ema20_pre1520"]).abs() / result["ema20_pre1520"]
    result["pullback_direction"] = np.where(result["pullback_close"] >= result["ema20_pre1520"], "LONG", "SHORT")
    result["pullback_volume_ratio"] = result["pullback_volume"] / result["avg_vol10_prior"]
    result["resume_volume_ratio"] = result["resume_volume"] / result["avg_vol10_prior"]
    result["persistent_direction"] = (
        np.sign(result["intraday_return"]).eq(np.sign(result["late_return"]))
        & result["late_return"].abs().ge(0.003)
    )
    result["fixed_pullback_resume"] = (
        result["pullback_distance"].le(0.005)
        & result["pullback_volume"].lt(result["avg_vol10_prior"])
        & result["resume_volume"].gt(1.3 * result["avg_vol10_prior"])
        & (((result["pullback_direction"] == "LONG") & result["intraday_return"].gt(0))
           | ((result["pullback_direction"] == "SHORT") & result["intraday_return"].lt(0)))
    )
    return result, {"ticker": ticker, "planned": len(panel), "built": len(result), "missing_files": missing_files}


def main() -> None:
    panel, sessions = build_panel()
    work = [(ticker, group.copy()) for ticker, group in panel.groupby("ticker", sort=True)]
    frames: list[pd.DataFrame] = []
    audit: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        for number, (frame, record) in enumerate(executor.map(process_ticker, work, chunksize=1), start=1):
            if not frame.empty:
                frames.append(frame)
            audit.append(record)
            if number % 50 == 0 or number == len(work):
                print(f"processed_tickers={number}/{len(work)} built_rows={sum(len(x) for x in frames)}", flush=True)
    features = pd.concat(frames, ignore_index=True).sort_values(["date", "ticker"]).reset_index(drop=True)
    if features.empty or features["date"].max() > END or features["next_date"].max() > END:
        raise RuntimeError("Feature coverage or date boundary failure")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT, index=False)
    pd.DataFrame(audit).to_csv(OUTPUT_DIR / "build_audit.csv", index=False)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "script_hash": sha256(Path(__file__)),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in (DAILY, CAPS, ELIGIBLE)},
        "universe": "quarterly PIT market-cap top500 intersected with daily PIT eligibility and ADV20 >= 10m",
        "clock": "features use five-minute bars timestamped before 15:20; exact 15:20 entry open",
        "planned_rows": len(panel),
        "feature_rows": len(features),
        "tickers": int(features["ticker"].nunique()),
        "date_range": [str(features["date"].min().date()), str(features["date"].max().date())],
        "max_next_date": str(features["next_date"].max().date()),
        "missing_month_files": int(pd.DataFrame(audit)["missing_files"].sum()),
        "output": str(OUTPUT).replace("\\", "/"),
        "output_hash": sha256(OUTPUT),
        "old_manual_62_used": False,
        "post2022_consumed": False,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
