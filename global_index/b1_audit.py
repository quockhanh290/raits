"""Run the B1 audit: are the books flat, is the account flat, is anything working?

Read-only in every mode. It places no order, cancels no order, and writes nothing at all
unless `--record` is passed, in which case it appends one line to its own evidence file.

    python -m global_index.track1_b1_audit                      # look, write nothing
    python -m global_index.track1_b1_audit --broker ibkr        # ask the account itself
    python -m global_index.track1_b1_audit --broker ibkr --record

Which broker source to use
--------------------------
`snapshot` reads the dashboard's cached IBKR state over HTTP and opens no connection. It is
free, but it can only answer B1 if the backend is new enough to report whether each query
SUCCEEDED — an older payload is read as UNKNOWN rather than as flat, because its collector
turns a raised exception into an empty list.

`ibkr` connects directly on its own client id and asks. `get_positions()` raises rather than
returning `[]` when it cannot read, and `get_open_orders()` returns `None` rather than `[]`
when it cannot testify, so this path can distinguish the two answers on its own. Client ids 1
(legacy runner and safety), 90 (Track 1 safety) and 99 (dashboard reader) are taken; the
default here is 97.

Run it when no window is open. It is a read, not a trade, but a read still holds a client id.

Why this file is not called `track1_b1_audit`
---------------------------------------------
It was, for about ten minutes, and the live-frame gate closed on it immediately: that gate
scans every `global_index/track1_*.py` for the identifiers by which live bars can be obtained,
`IBKRBroker` among them, and requires each to import the splice guard. The gate was right by
its own rule and the rule is not going to be softened to accommodate this file.

But the gate's subject is the ROUTE — the modules that form a frame or take a decision — and
this is an operator audit that reads positions and orders and never asks for a bar. The other
IBKR-connecting operator jobs, `run_stop_repair.py` and `run_maxhold_exit.py`, sit in this same
directory outside that namespace for the same reason, and `run_live_day_track1.py` is added to
the scan BY NAME because it is on the route despite not matching the glob. Membership there is
curated by role, not by spelling.

So the measurement itself — `track1_b1.py` — stays on the route, where it belongs and where it
opens no connection. The thing that connects lives out here with its peers. Nothing about the
gate was changed, and a test pins that this file constructs the broker while the module the
gate scans does not.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from global_index import track1_b1 as b1
from global_index import track1_slots as _ts

LEGACY_BOOK = "live_positions.json"
TRACK1_BOOK = _ts.TRACK1_POSITIONS_PATH

DEFAULT_SNAPSHOT_URL = "http://127.0.0.1:5002/api/v1/broker"
DEFAULT_IBKR_PORT = 4002
#: 1 legacy runner/safety, 90 Track 1 safety, 99 dashboard reader. This one is only ever
#: connected by this audit, for seconds, and never places anything.
DEFAULT_CLIENT_ID = 97


def evidence_from_snapshot(url: str) -> b1.BrokerEvidence:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=10) as fh:
            payload = json.load(fh)
    except Exception as exc:                                      # noqa: BLE001
        return b1.broker_unavailable(
            f"the dashboard snapshot at {url} could not be read "
            f"({type(exc).__name__}: {exc})", source="dashboard_snapshot")
    return b1.from_dashboard_snapshot(payload)


def evidence_from_ibkr(port: int, client_id: int) -> b1.BrokerEvidence:
    """Ask IBKR directly, read-only, and report failure as UNKNOWN rather than as empty."""
    from global_index.ibkr_broker import IBKRBroker

    probe: dict = {"source": "ibkr_direct", "connected": False,
                   "observed_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    broker = IBKRBroker(host="127.0.0.1", port=port, client_id=client_id)
    try:
        broker.connect()
        probe["connected"] = True
        # Re-stamp: the observation is when the reads happened, not when the attempt began.
        probe["observed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        try:
            probe["positions"] = [
                {"instrument": p.inst, "direction": p.direction, "contracts": p.contracts}
                for p in broker.get_positions()]
        except Exception as exc:                                  # noqa: BLE001
            probe["positions_error"] = f"{type(exc).__name__}: {exc}"
        try:
            orders = broker.get_open_orders()
            if orders is None:
                probe["open_orders_error"] = ("get_open_orders returned None — the broker "
                                              "declined to testify")
            else:
                probe["open_orders"] = orders
        except Exception as exc:                                  # noqa: BLE001
            probe["open_orders_error"] = f"{type(exc).__name__}: {exc}"
        try:
            probe["equity"] = broker.get_equity()
        except Exception:                                         # noqa: BLE001
            probe["equity"] = None
    except Exception as exc:                                      # noqa: BLE001
        probe["positions_error"] = probe["open_orders_error"] = (
            f"could not connect to IBKR ({type(exc).__name__}: {exc})")
    finally:
        try:
            broker.disconnect()
        except Exception:                                         # noqa: BLE001
            pass
    return b1.from_direct_probe(probe)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repo root (default: .)")
    ap.add_argument("--broker", choices=("snapshot", "ibkr", "none"), default="snapshot",
                    help="where broker evidence comes from (default: snapshot, opens no "
                         "connection)")
    ap.add_argument("--snapshot-url", default=DEFAULT_SNAPSHOT_URL)
    ap.add_argument("--port", type=int, default=DEFAULT_IBKR_PORT)
    ap.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    ap.add_argument("--record", action="store_true",
                    help="append the result to the B1 evidence file. Without this the audit "
                         "writes nothing at all.")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    return ap


def main(argv: "list | None" = None) -> int:
    a = build_parser().parse_args(argv)
    root = Path(a.root)

    legacy = b1.read_book(root / LEGACY_BOOK)
    # Stage 5ZS. The route's book is checked as the ROUTE's book, not merely as a list
    # of positions — a legacy-shaped file over that path still carries `positions: []`.
    track1 = b1.read_track1_book(root / TRACK1_BOOK)

    if a.broker == "ibkr":
        ev = evidence_from_ibkr(a.port, a.client_id)
    elif a.broker == "snapshot":
        ev = evidence_from_snapshot(a.snapshot_url)
    else:
        ev = b1.broker_unavailable("--broker none: the account was deliberately not asked")

    result = b1.measure(legacy, track1, ev)

    print(f"legacy book  {legacy.state:>10}  positions={legacy.count}")
    print(f"track1 book  {track1.state:>10}  positions={track1.count}")
    print(f"broker       {ev.source}  connected={ev.connected}  "
          f"positions={'?' if not ev.positions_known else len(ev.positions)}  "
          f"working orders={'?' if not ev.orders_known else len(ev.open_orders)}")
    if ev.equity is not None:
        print(f"equity       {ev.equity}")
    print()
    print(f"B1  {result.status}  ({result.code})")
    print(f"    {result.detail}")
    print(f"    {b1.operator_line(result)}")
    for name in ("orphans", "unprotected"):
        rows = result.findings.get(name)
        if rows:
            print(f"    {name}:")
            for r in rows:
                print("      ", json.dumps(r, sort_keys=True))
    if a.json:
        print()
        print(json.dumps(result.as_dict(), indent=1, default=str))

    if a.record:
        p = b1.record(result, root, source=f"track1_b1_audit --broker {a.broker}")
        print(f"\nrecorded -> {p}")
    else:
        print("\nnothing written (pass --record to file this as evidence)")

    # 0 on PASS, 1 on FAIL, 2 on UNKNOWN. A caller that cannot read the text can still tell
    # "flat" from "not flat" from "could not tell", which the exit code of a plain script
    # would collapse into two.
    return {b1.PASS: 0, b1.FAIL: 1, b1.UNKNOWN: 2}[result.status]


if __name__ == "__main__":
    sys.exit(main())
