"""
monitor/start_backend.py
=========================
Entry point for the read-only IBKR monitor backend.

Usage (from d:\\raits):
    python monitor/start_backend.py
    python monitor/start_backend.py --ibkr-port 4002 --api-port 5001

If flask is missing:
    pip install flask

Two connections can coexist (paper Gateway 4002):
    runner.py  uses client_id=1  (or whatever run_live_day sets)
    backend    uses client_id=99 (this script)

Dashboard then auto-polls http://localhost:5001/api/all every 8s.
"""
import sys
from pathlib import Path

# Make sure d:\\raits is on sys.path so `monitor` package is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import flask  # noqa: F401
except ImportError:
    print("ERROR: flask not installed.")
    print("  pip install flask")
    sys.exit(1)

from monitor.backend.app import main

if __name__ == "__main__":
    main()
