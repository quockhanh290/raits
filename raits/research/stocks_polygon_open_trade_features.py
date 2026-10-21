from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


CACHE = Path("raits/data/cache/polygon_stock_trades_open_2018_2022")
STATUS = CACHE / "status.csv"
SOURCE_MANIFEST = CACHE / "manifest.json"
OUTPUT = CACHE / "causal_features_pre0935.parquet"
MANIFEST = CACHE / "causal_features_pre0935_manifest.json"
SIGNAL_START = "09:30:00"
SIGNAL_MID = "09:32:30"
SIGNAL_END = "09:35:00"
OPEN_PRINT_END = "09:30:10"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def clock_ns(date_text: str, clock: str) -> int:
    return int(pd.Timestamp(f"{date_text} {clock}", tz="US/Eastern").tz_convert("UTC").value)


def imbalance(signed_dollar: pd.Series, dollar: pd.Series) -> float:
    total = float(dollar.sum())
    return float(signed_dollar.sum() / total) if total > 0 else np.nan


def build_one(row: pd.Series) -> dict[str, object]:
    date_text, ticker = str(row["date"]), str(row["ticker"])
    path = Path(str(row["path"]))
    available = set(pq.ParquetFile(path).schema_arrow.names)
    wanted = ["sip_timestamp", "price", "size", "sequence_number", "trf_id", "correction"]
    frame = pd.read_parquet(
        path,
        columns=[column for column in wanted if column in available],
    )
    if "correction" not in frame:
        frame["correction"] = 0
    if "trf_id" not in frame:
        frame["trf_id"] = np.nan
    frame["correction"] = pd.to_numeric(frame["correction"], errors="coerce").fillna(0)
    frame = frame[
        frame["correction"].eq(0)
        & pd.to_numeric(frame["price"], errors="coerce").gt(0)
        & pd.to_numeric(frame["size"], errors="coerce").gt(0)
    ].copy()
    frame = frame.sort_values(["sip_timestamp", "sequence_number"], kind="stable")
    price_change = frame["price"].diff()
    tick_sign = np.sign(price_change).replace(0.0, np.nan).ffill().fillna(0.0)
    frame["tick_sign"] = tick_sign
    frame["dollar"] = frame["price"] * frame["size"]
    frame["signed_dollar"] = frame["tick_sign"] * frame["dollar"]

    start_ns = clock_ns(date_text, SIGNAL_START)
    mid_ns = clock_ns(date_text, SIGNAL_MID)
    end_ns = clock_ns(date_text, SIGNAL_END)
    print_end_ns = clock_ns(date_text, OPEN_PRINT_END)
    signal = frame[frame["sip_timestamp"].ge(start_ns) & frame["sip_timestamp"].lt(end_ns)].copy()
    early = signal[signal["sip_timestamp"].lt(mid_ns)]
    late = signal[signal["sip_timestamp"].ge(mid_ns)]
    opening_print = signal[signal["sip_timestamp"].lt(print_end_ns)]
    trf = signal[signal["trf_id"].notna()]
    lit = signal[signal["trf_id"].isna()]

    total_dollar = float(signal["dollar"].sum())
    large_cutoff = float(signal["dollar"].quantile(0.80)) if not signal.empty else np.nan
    large = signal[signal["dollar"].ge(large_cutoff)] if np.isfinite(large_cutoff) else signal.iloc[0:0]
    nonzero_signed = int(signal["tick_sign"].ne(0).sum())
    return {
        "date": date_text,
        "ticker": ticker,
        "raw_trades": int(len(frame)),
        "signal_trades": int(len(signal)),
        "signed_trades": nonzero_signed,
        "signal_dollar": total_dollar,
        "flow_imbalance": imbalance(signal["signed_dollar"], signal["dollar"]),
        "early_flow_imbalance": imbalance(early["signed_dollar"], early["dollar"]),
        "late_flow_imbalance": imbalance(late["signed_dollar"], late["dollar"]),
        "large_flow_imbalance": imbalance(large["signed_dollar"], large["dollar"]),
        "large_trade_dollar_share": float(large["dollar"].sum() / total_dollar) if total_dollar > 0 else np.nan,
        "trf_flow_imbalance": imbalance(trf["signed_dollar"], trf["dollar"]),
        "lit_flow_imbalance": imbalance(lit["signed_dollar"], lit["dollar"]),
        "trf_dollar_share": float(trf["dollar"].sum() / total_dollar) if total_dollar > 0 else np.nan,
        "opening_print_dollar_share": float(opening_print["dollar"].sum() / total_dollar) if total_dollar > 0 else np.nan,
        "late_vs_early_trade_rate": float(len(late) / len(early)) if len(early) > 0 else np.nan,
        "signal_vwap": float((signal["price"] * signal["size"]).sum() / signal["size"].sum()) if signal["size"].sum() > 0 else np.nan,
        "first_signal_price": float(signal.iloc[0]["price"]) if not signal.empty else np.nan,
        "last_signal_price": float(signal.iloc[-1]["price"]) if not signal.empty else np.nan,
        "max_signal_sip_timestamp": int(signal["sip_timestamp"].max()) if not signal.empty else 0,
        "signal_end_ns": end_ns,
    }


def main() -> None:
    status = pd.read_csv(STATUS, dtype={"date": str, "ticker": str})
    status = status.drop_duplicates(["date", "ticker"], keep="last")
    status = status[status["status"].eq("OK")].sort_values(["date", "ticker"]).reset_index(drop=True)
    if len(status) != 32_176 or status["date"].max() > "2022-12-30":
        raise RuntimeError("Unexpected fetch coverage or post-2022 data")

    with ThreadPoolExecutor(max_workers=16) as executor:
        rows = list(executor.map(build_one, [row for _, row in status.iterrows()]))
    features = pd.DataFrame(rows).sort_values(["date", "ticker"]).reset_index(drop=True)
    features["date"] = pd.to_datetime(features["date"])
    if features.duplicated(["date", "ticker"]).any():
        raise RuntimeError("Duplicate feature keys")
    if features["max_signal_sip_timestamp"].ge(features["signal_end_ns"]).any():
        raise RuntimeError("Feature cache contains post-signal records")
    if features["signal_trades"].le(0).any():
        raise RuntimeError("Feature cache contains empty signal windows")

    tmp = OUTPUT.with_name(f"{OUTPUT.name}.tmp")
    features.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(OUTPUT)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "script_hash": sha256(Path(__file__)),
        "source_manifest": str(SOURCE_MANIFEST).replace("\\", "/"),
        "source_manifest_hash": sha256(SOURCE_MANIFEST),
        "status_hash": sha256(STATUS),
        "output": str(OUTPUT).replace("\\", "/"),
        "output_hash": sha256(OUTPUT),
        "rows": len(features),
        "tickers": int(features["ticker"].nunique()),
        "date_range": [str(features["date"].min().date()), str(features["date"].max().date())],
        "feature_clock": "all signal features use SIP arrivals in [09:30:00,09:35:00) ET; tick sign warmup begins at 09:25",
        "trade_filter": "correction == 0, finite positive price and size",
        "signing": "causal tick rule; zero-price-change trades carry the last nonzero sign; unresolved initial trades have sign zero",
        "large_trade_definition": "top 20% by trade dollar value within the completed pre-09:35 signal window",
        "post2022_consumed": False,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))
    print(features.describe(include="all").to_string())


if __name__ == "__main__":
    main()
