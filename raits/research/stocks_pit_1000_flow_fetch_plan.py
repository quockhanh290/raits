from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pandas as pd


DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
ELIGIBLE = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
RAW = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
PLAN = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv")
EXACT = Path("STOCKS_PIT_1000_FLOW_EXACT_CLOCK_ROWS_2026-10-02.csv")
MANIFEST = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.json")
START = pd.Timestamp("2018-01-02")
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


def build_panel() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY)[
        ["date", "ticker", "open_0930", "prev_close_1555", "prev_dayret", "gap", "vol20_pre"]
    ].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[daily["date"].between(START, END)].copy()

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
    sessions = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(
        sessions,
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
        & (panel["prev_dayret"].le(-0.05) | panel["gap"].ge(0.02))
    ].copy()
    panel["yday_precandidate"] = panel["prev_dayret"].le(-0.05)
    panel["gapup_precandidate"] = panel["gap"].ge(0.02)
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True)


def raw_file_path(ticker: str, month: str) -> Path:
    safe = safe_symbol(ticker)
    return RAW / safe / f"{safe}_5m_{month}.parquet"


def extract_exact(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = panel[["date", "ticker"]].drop_duplicates().copy()
    keys["month"] = keys["date"].dt.strftime("%Y-%m")
    requested = {(row.ticker, row.date) for row in keys.itertuples(index=False)}
    file_keys = list(keys[["ticker", "month"]].drop_duplicates().itertuples(index=False, name=None))
    clocks = {"09:30", "09:55", "10:00", "10:05", "15:55", "16:00"}

    def read_one(item: tuple[str, str]) -> tuple[pd.DataFrame | None, dict[str, object]]:
        ticker, month = item
        path = raw_file_path(str(ticker), str(month))
        record = {"ticker": ticker, "month": month, "path": str(path).replace("\\", "/"),
                  "exists": path.exists(), "size": path.stat().st_size if path.exists() else 0}
        if not path.exists() or path.stat().st_size <= 0:
            return None, {**record, "selected_rows": 0}
        raw = pd.read_parquet(path, columns=["open", "high", "low", "close", "volume", "transactions"]).reset_index()
        raw["date"] = raw["timestamp"].dt.normalize()
        raw["clock"] = raw["timestamp"].dt.strftime("%H:%M")
        raw = raw[raw["clock"].isin(clocks) & raw["date"].map(lambda date: (ticker, date) in requested)].copy()
        raw["ticker"] = ticker
        keep = raw[["date", "clock", "ticker", "open", "high", "low", "close", "volume", "transactions"]]
        return (keep if not keep.empty else None), {**record, "selected_rows": len(keep)}

    rows: list[pd.DataFrame] = []
    inventory: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        for selected, record in executor.map(read_one, file_keys):
            if selected is not None:
                rows.append(selected)
            inventory.append(record)
    exact = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    exact = exact.drop_duplicates(["date", "clock", "ticker"], keep="last").sort_values(["date", "ticker", "clock"])
    return exact, pd.DataFrame(inventory)


def main() -> None:
    panel = build_panel()
    if panel.empty or panel["date"].max() > END:
        raise RuntimeError("Empty or post-2022 fetch plan")
    exact, inventory = extract_exact(panel)
    signal = exact[exact["clock"].eq("09:55")][["date", "ticker", "close"]].rename(columns={"close": "signal_price_1000"})
    entry = exact[exact["clock"].eq("10:05")][["date", "ticker", "open"]].rename(columns={"open": "entry_price_1005"})
    plan = panel.merge(signal, on=["date", "ticker"], how="left", validate="one_to_one")
    plan = plan.merge(entry, on=["date", "ticker"], how="left", validate="one_to_one")
    plan["signal_complete"] = plan["signal_price_1000"].notna()
    plan["entry_complete"] = plan["entry_price_1005"].notna()
    plan.to_csv(PLAN, index=False)
    exact.to_csv(EXACT, index=False)
    inventory_path = PLAN.with_name(PLAN.stem + "_RAW_FILE_INVENTORY.csv")
    inventory.to_csv(inventory_path, index=False)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "script_hash": sha256(Path(__file__)),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in (DAILY, CAPS, ELIGIBLE)},
        "universe": "quarterly PIT market-cap top500 intersected with daily PIT eligibility and ADV20 >= 10m",
        "precandidates": "prev_dayret <= -5% OR opening gap >= +2%; price >= 5; absolute gap <= 30%",
        "selection_note": "No reclaim, flow, entry availability, or future exit availability is used to form ticker-date keys",
        "date_range": [str(panel["date"].min().date()), str(panel["date"].max().date())],
        "ticker_days": len(panel),
        "tickers": int(panel["ticker"].nunique()),
        "yday_precandidates": int(panel["yday_precandidate"].sum()),
        "gapup_precandidates": int(panel["gapup_precandidate"].sum()),
        "signal_complete": int(plan["signal_complete"].sum()),
        "entry_complete": int(plan["entry_complete"].sum()),
        "raw_files": len(inventory),
        "raw_files_missing": int((~inventory["exists"]).sum()),
        "plan": str(PLAN),
        "plan_hash": sha256(PLAN),
        "exact_clock_rows": str(EXACT),
        "exact_clock_rows_hash": sha256(EXACT),
        "old_manual_62_used": False,
        "post2022_consumed": False,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
