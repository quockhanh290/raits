"""
Backfill gap Jul 13-19 trong 4 parquet _8y bằng cách fetch từ IBKR
với endDateTime='20260719 18:00:00' và duration='7 D'.
Merge (không chỉ append) vào parquet hiện tại.
"""
import sys, logging
from pathlib import Path
sys.path.insert(0, '.')

import pandas as pd
import ib_insync as ibi

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s — %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("backfill_gap")

JOBS = [
    dict(symbol="MES", expiry="20260918", exchange="CME",  parquet=Path("data/cache/futures/ES_continuous_1m_8y.parquet")),
    dict(symbol="MNQ", expiry="20260918", exchange="CME",  parquet=Path("data/cache/futures/NQ_continuous_1m_8y.parquet")),
    dict(symbol="MYM", expiry="20260918", exchange="CBOT", parquet=Path("data/cache/futures/YM_continuous_1m_8y.parquet")),
    dict(symbol="M2K", expiry="20260918", exchange="CME",  parquet=Path("data/cache/futures/RTY_continuous_1m_8y.parquet")),
]

END_DT   = "20260719 18:00:00"   # fetch ending at gap boundary
DURATION = "7 D"                  # covers Jul 12-19

ib = ibi.IB()
ib.connect("127.0.0.1", 4002, clientId=3)
log.info("Connected.")

for j in JOBS:
    log.info("[%s] Fetching endDateTime=%s duration=%s ...", j["symbol"], END_DT, DURATION)
    contract = ibi.Future(j["symbol"], lastTradeDateOrContractMonth=j["expiry"], exchange=j["exchange"])
    ib.qualifyContracts(contract)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=END_DT,
        durationStr=DURATION,
        barSizeSetting="1 min",
        whatToShow="TRADES",
        useRTH=False,
        formatDate=1,
    )
    if not bars:
        log.warning("[%s] No bars returned.", j["symbol"])
        continue

    new_df = ibi.util.df(bars).set_index("date")
    new_df.index = pd.to_datetime(new_df.index)
    if new_df.index.tz is not None:
        new_df.index = new_df.index.tz_convert("America/New_York").tz_localize(None)
    new_df.columns = [c.lower() for c in new_df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in new_df.columns]
    new_df = new_df[keep].sort_index()
    log.info("[%s] Fetched %d bars  %s → %s", j["symbol"], len(new_df),
             new_df.index[0], new_df.index[-1])

    # Load existing parquet (normalize to ET naive)
    old_df = pd.read_parquet(j["parquet"])
    if old_df.index.tz is not None:
        old_df.index = old_df.index.tz_convert("America/New_York").tz_localize(None)

    # Merge: old + new, drop_duplicates (keep old where overlap to preserve splice)
    combined = pd.concat([old_df, new_df[~new_df.index.isin(old_df.index)]]).sort_index()
    gap_filled = len(combined) - len(old_df)
    log.info("[%s] Gap filled: +%d bars → %d total", j["symbol"], gap_filled, len(combined))

    combined.to_parquet(j["parquet"])
    log.info("[%s] Saved %s", j["symbol"], j["parquet"].name)

ib.disconnect()
log.info("Done.")
