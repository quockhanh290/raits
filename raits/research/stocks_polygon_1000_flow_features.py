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
OUTPUT = CACHE / "causal_features_pre1000.parquet"
MANIFEST = CACHE / "causal_features_pre1000_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def clock_ns(date_text: str, clock: str) -> int:
    return int(pd.Timestamp(f"{date_text} {clock}", tz="US/Eastern").tz_convert("UTC").value)


def imbalance(frame: pd.DataFrame) -> float:
    total = float(frame["dollar"].sum())
    return float(frame["signed_dollar"].sum() / total) if total > 0 else np.nan


def build_one(row: pd.Series) -> dict[str, object]:
    date_text, ticker, path = str(row["date"]), str(row["ticker"]), Path(str(row["path"]))
    available = set(pq.ParquetFile(path).schema_arrow.names)
    wanted = ["sip_timestamp", "price", "size", "sequence_number", "trf_id", "correction"]
    frame = pd.read_parquet(path, columns=[column for column in wanted if column in available])
    if "correction" not in frame:
        frame["correction"] = 0
    if "trf_id" not in frame:
        frame["trf_id"] = np.nan
    frame["correction"] = pd.to_numeric(frame["correction"], errors="coerce").fillna(0)
    frame = frame[frame["correction"].eq(0) & frame["price"].gt(0) & frame["size"].gt(0)].copy()
    frame = frame.sort_values(["sip_timestamp", "sequence_number"], kind="stable")
    frame["tick_sign"] = np.sign(frame["price"].diff()).replace(0.0, np.nan).ffill().fillna(0.0)
    frame["dollar"] = frame["price"] * frame["size"]
    frame["signed_dollar"] = frame["tick_sign"] * frame["dollar"]

    t930, t935 = clock_ns(date_text, "09:30:00"), clock_ns(date_text, "09:35:00")
    t955, t1000 = clock_ns(date_text, "09:55:00"), clock_ns(date_text, "10:00:00")
    signal = frame[frame["sip_timestamp"].ge(t930) & frame["sip_timestamp"].lt(t1000)].copy()
    first5 = signal[signal["sip_timestamp"].lt(t935)]
    middle20 = signal[signal["sip_timestamp"].ge(t935) & signal["sip_timestamp"].lt(t955)]
    last5 = signal[signal["sip_timestamp"].ge(t955)]
    trf = signal[signal["trf_id"].notna()]
    lit = signal[signal["trf_id"].isna()]
    total_dollar = float(signal["dollar"].sum())
    large_cutoff = float(signal["dollar"].quantile(0.80)) if not signal.empty else np.nan
    large = signal[signal["dollar"].ge(large_cutoff)] if np.isfinite(large_cutoff) else signal.iloc[0:0]
    return {
        "date": date_text, "ticker": ticker, "raw_trades": len(frame), "signal_trades": len(signal),
        "signal_dollar": total_dollar, "flow_imbalance_30m": imbalance(signal),
        "flow_imbalance_first5": imbalance(first5), "flow_imbalance_middle20": imbalance(middle20),
        "flow_imbalance_last5": imbalance(last5),
        "flow_acceleration": imbalance(last5) - imbalance(first5),
        "large_flow_imbalance": imbalance(large),
        "large_trade_dollar_share": float(large["dollar"].sum() / total_dollar) if total_dollar > 0 else np.nan,
        "trf_flow_imbalance": imbalance(trf), "lit_flow_imbalance": imbalance(lit),
        "trf_dollar_share": float(trf["dollar"].sum() / total_dollar) if total_dollar > 0 else np.nan,
        "last5_dollar_share": float(last5["dollar"].sum() / total_dollar) if total_dollar > 0 else np.nan,
        "last5_vs_first5_trade_rate": float(len(last5) / len(first5)) if len(first5) else np.nan,
        "signal_vwap": float((signal["price"] * signal["size"]).sum() / signal["size"].sum()) if signal["size"].sum() else np.nan,
        "first_signal_price": float(signal.iloc[0]["price"]) if len(signal) else np.nan,
        "last_signal_price": float(signal.iloc[-1]["price"]) if len(signal) else np.nan,
        "max_signal_sip_timestamp": int(signal["sip_timestamp"].max()) if len(signal) else 0,
        "signal_end_ns": t1000,
    }


def main() -> None:
    status = pd.read_csv(STATUS, dtype={"date": str, "ticker": str}).drop_duplicates(["date", "ticker"], keep="last")
    status = status[status["status"].eq("OK")].sort_values(["date", "ticker"]).reset_index(drop=True)
    if len(status) != 28_225 or status["date"].max() > "2022-12-30":
        raise RuntimeError("Unexpected fetch coverage")
    with ThreadPoolExecutor(max_workers=16) as executor:
        rows = list(executor.map(build_one, [row for _, row in status.iterrows()]))
    features = pd.DataFrame(rows).sort_values(["date", "ticker"]).reset_index(drop=True)
    features["date"] = pd.to_datetime(features["date"])
    if features.duplicated(["date", "ticker"]).any() or features["signal_trades"].le(0).any():
        raise RuntimeError("Duplicate keys or empty signal window")
    if features["max_signal_sip_timestamp"].ge(features["signal_end_ns"]).any():
        raise RuntimeError("Post-10:00 trade entered features")
    tmp = OUTPUT.with_name(OUTPUT.name + ".tmp")
    features.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(OUTPUT)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"), "script_hash": sha256(Path(__file__)),
        "source_manifest": str(SOURCE_MANIFEST).replace("\\", "/"), "source_manifest_hash": sha256(SOURCE_MANIFEST),
        "status_hash": sha256(STATUS), "output": str(OUTPUT).replace("\\", "/"), "output_hash": sha256(OUTPUT),
        "rows": len(features), "tickers": int(features["ticker"].nunique()),
        "date_range": [str(features["date"].min().date()), str(features["date"].max().date())],
        "clock": "tick sign warmup 09:25; signal features use SIP arrivals [09:30,10:00) only",
        "windows": {"first5": "[09:30,09:35)", "middle20": "[09:35,09:55)", "last5": "[09:55,10:00)"},
        "post1000_records_used": False, "post2022_consumed": False,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))
    print(features.describe(include="all").to_string())


if __name__ == "__main__":
    main()
