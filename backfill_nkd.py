import sys, logging
from pathlib import Path
sys.path.insert(0, '.')
import pandas as pd
import ib_insync as ibi

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s — %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("backfill_nkd")

PARQUET  = Path("global_index/data/NKD_continuous_1m_8y.parquet")
END_DT   = "20260719 18:00:00"
DURATION = "7 D"

ib = ibi.IB()
ib.connect("127.0.0.1", 4002, clientId=3)
log.info("Connected.")

contract = ibi.Future("NKD", lastTradeDateOrContractMonth="20260910", exchange="CME")
ib.qualifyContracts(contract)
log.info("Fetching NKD endDateTime=%s duration=%s ...", END_DT, DURATION)

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
    log.warning("No bars returned.")
    ib.disconnect()
    sys.exit(1)

new_df = ibi.util.df(bars).set_index("date")
new_df.index = pd.to_datetime(new_df.index)
if new_df.index.tz is not None:
    new_df.index = new_df.index.tz_convert("America/New_York").tz_localize(None)
new_df.columns = [c.lower() for c in new_df.columns]
keep = [c for c in ["open", "high", "low", "close", "volume"] if c in new_df.columns]
new_df = new_df[keep].sort_index()
log.info("Fetched %d bars  %s → %s", len(new_df), new_df.index[0], new_df.index[-1])

old_df = pd.read_parquet(PARQUET)
if old_df.index.tz is not None:
    old_df.index = old_df.index.tz_convert("America/New_York").tz_localize(None)

combined = pd.concat([old_df, new_df[~new_df.index.isin(old_df.index)]]).sort_index()
log.info("Gap filled: +%d bars → %d total", len(combined) - len(old_df), len(combined))

combined.to_parquet(PARQUET)
log.info("Saved %s", PARQUET.name)

ib.disconnect()
log.info("Done.")
