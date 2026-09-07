"""scratch/stocks_stage0_data_20260826.py — the stock route's data layer. READ-ONLY.

Stage STOCKS-0. Nothing here writes to a production path, connects to a broker, or imports
anything that can place an order.

Why a separate loader rather than `futures._validated_core.load_parquet`
------------------------------------------------------------------------
`load_parquet` reads ONE parquet holding a whole instrument's history and does
`pd.to_datetime(idx, utc=True).tz_convert(ET)`. The equities cache is the opposite shape:
117,533 files, one per (ticker, session), each already carrying ET-NAIVE stamps written by
`raits_polygon_fetcher`. Feeding those through `load_parquet` would re-read naive ET stamps as
UTC and shift every bar by four or five hours. So the stock route reads its own files and
states its own clock rather than borrowing one built for a different file shape.

The cache key is a formula, not a mystery
-----------------------------------------
`DataCache._generate_cache_key` is `md5(f"{ticker}_{start.date()}_{end.date()}_{interval}")`.
Every session file was written with start == end, so the index is REDERIVED rather than
discovered by opening 117,533 files. A file that does not exist is a session that was never
fetched: an absence, not a zero.

Session choice, declared
------------------------
The cached frames carry 04:00-19:55 ET. This route trades and measures on RTH 09:30-15:55
only. That is a stock-specific decision, not a port: extended-hours prints are thin and would
enter the daily ATR, the prior-day range and the slot-volume median without ever being
tradeable at the size this route wants. Futures Track 1 never had to make this choice because
its session is continuous.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE_DATA = ROOT / "raits" / "data" / "cache" / "data"
SPY_CSV = ROOT / "spy_daily_live.csv"

TZ = "America/New_York"
RTH_START = pd.Timestamp("09:30").time()
RTH_END = pd.Timestamp("15:55").time()

#: Vendor identity travels with the data, because "5-minute bars" is not an identity.
DATA_SOURCE = "polygon_5min_split_div_adjusted_ETnaive_rth_0930_1555"

#: Exchange-traded funds inside the cached set. Held separately because a sector ETF and a
#: single name are not the same instrument for a liquidity, borrow or corporate-action
#: question, and one headline number over both hides which of them carried it.
ETFS = frozenset({"SPY", "QQQ", "IWM", "GLD", "XLB", "XLE", "XLF", "XLI", "XLK",
                  "XLP", "XLU", "XLV", "XLY"})


def cache_key(ticker: str, day, interval: str = "5min") -> str:
    d = pd.Timestamp(day).date()
    raw = "{}_{}_{}_{}".format(ticker, d, d, interval)
    return "{}_{}_{}".format(ticker, interval, hashlib.md5(raw.encode()).hexdigest())


def session_path(ticker: str, day) -> Path:
    return CACHE_DATA / (cache_key(ticker, day) + ".parquet")


def universe() -> list:
    """Every ticker with at least one cached 5-minute session, sorted."""
    names = set()
    for p in CACHE_DATA.glob("*_5min_*.parquet"):
        names.add(p.name.split("_5min_")[0])
    return sorted(names)


def calendar(ticker: str = "SPY", start: str = "2017-01-01",
             end: str = "2024-12-31") -> pd.DatetimeIndex:
    """Sessions this route can see, taken from one liquid name's cached files.

    Derived from the files rather than from a holiday library: the tradable calendar for THIS
    backtest is exactly the set of sessions whose bars are on disk, and a session the vendor
    never delivered is not tradeable however open the exchange was.
    """
    days = [d for d in pd.bdate_range(start, end) if session_path(ticker, d).exists()]
    return pd.DatetimeIndex(days)


def load_symbol(ticker: str, days) -> pd.DataFrame:
    """One symbol's RTH 5-minute frame over `days`: ET-naive, sorted, deduplicated.

    A session with no file is skipped; coverage is measured separately by the caller. A
    session whose file exists but holds no RTH bar is dropped, because a session with no 09:30
    bar can neither be entered nor exited by this route's rules.
    """
    frames = []
    for d in days:
        p = session_path(ticker, d)
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p, columns=["open", "high", "low", "close", "volume"])
        except Exception:
            continue
        if df.empty:
            continue
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is not None:
            # Never observed. Refused rather than guessed: a silent tz_convert here is the
            # four-hour shift this loader exists to prevent.
            raise ValueError("{}: expected ET-naive stamps, got tz={}".format(p.name, idx.tz))
        keep = (idx.time >= RTH_START) & (idx.time <= RTH_END)
        df = df[keep]
        if df.empty:
            continue
        frames.append(df)
    cols = ["open", "high", "low", "close", "volume"]
    if not frames:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="timestamp"))
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="first")]
    return out[cols].astype(float)


def daily_from_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Session OHLCV plus dollar volume, from the RTH 5-minute frame itself.

    Deliberately not read from the separate daily parquets: a daily bar fetched by another
    request can disagree with the intraday frame it is supposed to describe, and every
    liquidity and ATR number here has to be a statement about the bars this route trades.
    """
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume",
                                     "dollar_volume"])
    key = df.index.normalize()
    g = df.groupby(key)
    d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                      "low": g["low"].min(), "close": g["close"].last(),
                      "volume": g["volume"].sum()})
    d["dollar_volume"] = (df["close"] * df["volume"]).groupby(key).sum()
    return d


def _true_range(d: pd.DataFrame) -> pd.Series:
    pc = d["close"].shift(1)
    return pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                      (d["low"] - pc).abs()], axis=1).max(axis=1)


def daily_atr_causal(daily: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR(14) on RTH sessions, shifted so the value at day D uses D-1 and earlier only.

    The futures route reads `futures._validated_core.daily_atr_series`, whose value at D is a
    rolling mean ENDING at D and therefore contains D's own high and low. That is harmless for
    a quantity consumed after D closes, and it is not harmless for one consumed at 14:00 on D,
    which is exactly what the Normal-R4 stop basis does. The stock route uses this shifted
    series; the unshifted one is kept below so the difference can be priced rather than argued.
    """
    atr = _true_range(daily).rolling(period).mean().shift(1)
    atr.index = pd.DatetimeIndex(atr.index).normalize()
    return atr.dropna()


def daily_atr_engine(daily: pd.DataFrame, period: int = 14) -> pd.Series:
    """The futures route's definition, reproduced on RTH sessions: the value at D includes D."""
    atr = _true_range(daily).rolling(period).mean()
    atr.index = pd.DatetimeIndex(atr.index).normalize()
    return atr.dropna()


def adv_dollar(daily: pd.DataFrame, window: int = 20) -> pd.Series:
    """Trailing MEDIAN dollar volume over `window` sessions, shifted by one.

    Median rather than mean: one earnings session can lift a 20-day mean enough to carry a name
    over a liquidity floor it does not hold on an ordinary day. Shifted because a floor tested
    at 14:00 on D cannot know D's own volume.
    """
    return (daily["dollar_volume"]
            .rolling(window, min_periods=max(5, window // 2)).median().shift(1))


def spy_daily_close() -> pd.Series:
    b = pd.read_csv(SPY_CSV)
    s = pd.Series(b["close"].values,
                  index=pd.to_datetime(b["date"]).dt.normalize()).sort_index()
    return s.dropna()
