from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


CACHE = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022")
STATUS = CACHE / "status.csv"
SOURCE_MANIFEST = CACHE / "manifest.json"
CONDITION_MAP = Path("raits/data/cache/external_equity_context/polygon_2018_2024/reference/trade_conditions.parquet")
OUTPUT = CACHE / "causal_tape_features_pre1000.parquet"
MANIFEST = CACHE / "causal_tape_features_pre1000_manifest.json"
OPEN_CODES = {16, 17, 25, 55}
ODD_LOT_CODE = 37
SWEEP_CODE = 14
CROSS_CODE = 9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def clock_ns(date_text: str, clock: str) -> int:
    return int(pd.Timestamp(f"{date_text} {clock}", tz="America/New_York").tz_convert("UTC").value)


def has_code(value: object, codes: set[int]) -> bool:
    if value is None:
        return False
    if isinstance(value, np.ndarray):
        values = value.tolist()
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return False
    return any(int(item) in codes for item in values if item is not None)


def weighted_share(frame: pd.DataFrame, mask: pd.Series) -> float:
    total = float(frame["dollar"].sum())
    return float(frame.loc[mask, "dollar"].sum() / total) if total > 0 else np.nan


def imbalance(frame: pd.DataFrame) -> float:
    total = float(frame["dollar"].sum())
    return float(frame["signed_dollar"].sum() / total) if total > 0 else np.nan


def weighted_hhi(frame: pd.DataFrame, column: str) -> float:
    total = float(frame["dollar"].sum())
    if total <= 0:
        return np.nan
    shares = frame.groupby(column, dropna=False)["dollar"].sum() / total
    return float(shares.pow(2).sum())


def build_one(row: pd.Series) -> dict[str, object]:
    date_text, ticker, path = str(row["date"]), str(row["ticker"]), Path(str(row["path"]))
    available = set(pq.ParquetFile(path).schema_arrow.names)
    wanted = ["sip_timestamp", "participant_timestamp", "price", "size", "exchange", "sequence_number",
              "trf_id", "correction", "conditions"]
    frame = pd.read_parquet(path, columns=[column for column in wanted if column in available])
    for column, default in (("correction", 0), ("trf_id", np.nan), ("exchange", np.nan),
                            ("participant_timestamp", np.nan), ("conditions", None)):
        if column not in frame:
            frame[column] = default
    frame["correction"] = pd.to_numeric(frame["correction"], errors="coerce").fillna(0)
    frame = frame[frame["correction"].eq(0) & frame["price"].gt(0) & frame["size"].gt(0)].copy()
    frame = frame.sort_values(["sip_timestamp", "sequence_number"], kind="stable")
    start_ns, end_ns = clock_ns(date_text, "09:30:00"), clock_ns(date_text, "10:00:00")
    signal = frame[frame["sip_timestamp"].ge(start_ns) & frame["sip_timestamp"].lt(end_ns)].copy()
    if signal.empty:
        return {"date": date_text, "ticker": ticker, "signal_trades": 0, "signal_end_ns": end_ns,
                "max_signal_sip_timestamp": 0}
    signal["dollar"] = signal["price"] * signal["size"]
    signal["tick_sign"] = np.sign(signal["price"].diff()).replace(0.0, np.nan).ffill().fillna(0.0)
    signal["signed_dollar"] = signal["tick_sign"] * signal["dollar"]
    participant = pd.to_numeric(signal["participant_timestamp"], errors="coerce")
    latency = (signal["sip_timestamp"] - participant) / 1000.0
    latency = latency[latency.ge(0) & latency.le(10_000_000)]
    arrivals = signal["sip_timestamp"].diff().dropna() / 1000.0
    arrivals = arrivals[arrivals.ge(0)]
    condition = signal["conditions"]
    open_mask = condition.map(lambda value: has_code(value, OPEN_CODES))
    odd_condition_mask = condition.map(lambda value: has_code(value, {ODD_LOT_CODE}))
    sweep_mask = condition.map(lambda value: has_code(value, {SWEEP_CODE}))
    cross_mask = condition.map(lambda value: has_code(value, {CROSS_CODE}))
    large = signal[signal["dollar"].ge(100_000.0)]
    large_lit = large[large["trf_id"].isna()]
    official = signal[open_mask]
    signal_vwap = float((signal["price"] * signal["size"]).sum() / signal["size"].sum())
    official_vwap = float((official["price"] * official["size"]).sum() / official["size"].sum()) if len(official) else np.nan
    second = (signal["sip_timestamp"] // 1_000_000_000).value_counts()
    return {
        "date": date_text, "ticker": ticker, "signal_trades": int(len(signal)),
        "signal_dollar": float(signal["dollar"].sum()),
        "unique_exchanges": int(signal["exchange"].nunique(dropna=True)),
        "exchange_dollar_hhi": weighted_hhi(signal, "exchange"),
        "trf_dollar_share": weighted_share(signal, signal["trf_id"].notna()),
        "lit_flow_imbalance": imbalance(signal[signal["trf_id"].isna()]),
        "large_lit_flow_imbalance": imbalance(large_lit),
        "large_trade_dollar_share_fixed100k": weighted_share(signal, signal["dollar"].ge(100_000.0)),
        "block_dollar_share_size1000": weighted_share(signal, signal["size"].ge(1000.0)),
        "sub100_share_dollar_share": weighted_share(signal, signal["size"].lt(100.0)),
        "odd_lot_condition_dollar_share": weighted_share(signal, odd_condition_mask),
        "odd_lot_flow_imbalance": imbalance(signal[odd_condition_mask]),
        "sweep_dollar_share": weighted_share(signal, sweep_mask),
        "cross_dollar_share": weighted_share(signal, cross_mask),
        "official_open_dollar_share": weighted_share(signal, open_mask),
        "official_open_discount_to_signal_vwap": official_vwap / signal_vwap - 1.0 if np.isfinite(official_vwap) else np.nan,
        "median_trade_dollar": float(signal["dollar"].median()),
        "p90_trade_dollar": float(signal["dollar"].quantile(0.90)),
        "median_sip_latency_us": float(latency.median()) if len(latency) else np.nan,
        "p90_sip_latency_us": float(latency.quantile(0.90)) if len(latency) else np.nan,
        "median_interarrival_us": float(arrivals.median()) if len(arrivals) else np.nan,
        "p90_interarrival_us": float(arrivals.quantile(0.90)) if len(arrivals) else np.nan,
        "max_trades_per_second": int(second.max()) if len(second) else 0,
        "burst_share_top_second": float(second.max() / len(signal)) if len(second) else np.nan,
        "max_signal_sip_timestamp": int(signal["sip_timestamp"].max()), "signal_end_ns": end_ns,
    }


def main() -> None:
    conditions = pd.read_parquet(CONDITION_MAP)
    observed = set(pd.to_numeric(conditions["id"], errors="coerce").dropna().astype(int))
    required = OPEN_CODES | {ODD_LOT_CODE, SWEEP_CODE, CROSS_CODE}
    if not required.issubset(observed):
        raise RuntimeError(f"Condition map missing required codes: {sorted(required - observed)}")
    status = pd.read_csv(STATUS, dtype={"date": str, "ticker": str}).drop_duplicates(["date", "ticker"], keep="last")
    status = status[status["status"].eq("OK")].sort_values(["date", "ticker"]).reset_index(drop=True)
    if len(status) != 28_225 or status["date"].max() > "2022-12-30":
        raise RuntimeError("Unexpected raw trade coverage")
    with ThreadPoolExecutor(max_workers=16) as executor:
        rows = list(executor.map(build_one, [row for _, row in status.iterrows()]))
    features = pd.DataFrame(rows)
    features["date"] = pd.to_datetime(features["date"])
    features = features.sort_values(["date", "ticker"]).reset_index(drop=True)
    if features.duplicated(["date", "ticker"]).any() or features["signal_trades"].le(0).any():
        raise RuntimeError("Duplicate keys or empty signal windows")
    if features["max_signal_sip_timestamp"].ge(features["signal_end_ns"]).any():
        raise RuntimeError("Post-10:00 record entered tape features")
    tmp = OUTPUT.with_name(OUTPUT.name + ".tmp")
    features.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(OUTPUT)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "sourceManifest": str(SOURCE_MANIFEST).replace("\\", "/"), "sourceManifestHash": sha256(SOURCE_MANIFEST),
        "statusHash": sha256(STATUS), "conditionMap": str(CONDITION_MAP).replace("\\", "/"),
        "conditionMapHash": sha256(CONDITION_MAP), "output": str(OUTPUT).replace("\\", "/"),
        "outputHash": sha256(OUTPUT), "rows": len(features), "tickers": int(features["ticker"].nunique()),
        "dateRange": [str(features["date"].min().date()), str(features["date"].max().date())],
        "clock": "all features use SIP arrivals in [09:30,10:00) ET; no record at or after 10:00",
        "openingProxy": "condition codes 16,17,25,55 identify opening-related prints; not auction imbalance",
        "largeTrade": "fixed as-printed trade dollar >= 100000; no outcome-trained quantile",
        "post2022Consumed": False,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
