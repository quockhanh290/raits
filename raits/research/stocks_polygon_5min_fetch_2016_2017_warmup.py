from __future__ import annotations

import sys
from pathlib import Path

import stocks_polygon_5min_fetch_2018_2024 as fetch


OUT_DIR = Path("raits/data/cache/polygon_5min_2016_2017_warmup_62")
DEFAULT_START = "2016-09-01"
DEFAULT_END = "2017-12-31"


def main() -> None:
    fetch.OUT_DIR = OUT_DIR
    fetch.STATUS_CSV = OUT_DIR / "status.csv"
    fetch.MANIFEST_JSON = OUT_DIR / "manifest.json"
    if "--start" not in sys.argv:
        sys.argv.extend(["--start", DEFAULT_START])
    if "--end" not in sys.argv:
        sys.argv.extend(["--end", DEFAULT_END])
    fetch.main()


if __name__ == "__main__":
    main()
