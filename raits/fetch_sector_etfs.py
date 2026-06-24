"""
Fetch sector ETF 5-min data for IS period (2017-2022) + OOS (2023-2024).
Run after the PE_EXPANSION/META fetch completes, or in a separate terminal.
"""
import sys, os, importlib.util
sys.path.insert(0, r'd:\raits')

spec = importlib.util.spec_from_file_location('cfg', r'd:\raits\config_private.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

from raits.data.raits_polygon_fetcher import PolygonDataFetcher
import pandas as pd

SECTOR_ETFS = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]

FETCH = {
    'SECTOR_ETF_IS':  (SECTOR_ETFS, '2017-01-03', '2022-12-31'),
    'SECTOR_ETF_OOS': (SECTOR_ETFS, '2023-01-01', '2024-12-31'),
}

fetcher = PolygonDataFetcher(
    api_key=m.POLYGON_API_KEY,
    use_cache=True,
    cache_dir=r'd:\raits\raits\data\cache',
    rate_limit_calls_per_minute=100,
)

for label, (tickers, start, end) in FETCH.items():
    days = pd.bdate_range(start, end)
    print(f'\n--- {label}: {len(tickers)} tickers x {len(days)} days ---')
    for ticker in tickers:
        errors = 0
        for day in days:
            try:
                fetcher.fetch_intraday_bars(
                    ticker=ticker,
                    date=day.to_pydatetime(),
                    interval_minutes=5,
                    use_cache=True,
                )
            except Exception:
                errors += 1
        print(f'  {ticker} done' + (f' ({errors} errors)' if errors else ''))

print('\nAll done. Run window_debug.py --rebuild to reload cache.')
