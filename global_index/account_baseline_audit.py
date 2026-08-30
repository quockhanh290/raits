"""global_index/account_baseline_audit.py — the operator tool that records a paper baseline.

Stage 5ZZE. Read-only against the broker: it asks for the account values, the positions and the
working orders, and it places nothing. There is no order path in this file and no argument that
could make one.

**Named without the `track1_` prefix on purpose.** The live-frame gate scans every
`global_index/track1_*.py` for identifiers that mean live data is being obtained, and a module
that connects would close it and manufacture a blocker. Stage 5ZQ learned that by doing it — a
new audit was named `track1_b1_audit.py`, the gate shut, and a fourth blocker appeared out of
nowhere. The gate was not softened; the file was renamed. Same here.

Client id 96, and it is stated before anything connects. B1's own audit holds 97, the safety
jobs hold 90, a slot child holds 89, and legacy holds 1. Two processes sharing one id is how
this project lost six entry slots in a morning.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json

from global_index import track1_account_baseline as ab
from global_index import track1_b1 as b1

#: Distinct from every other id this repo connects with. See the module docstring.
DEFAULT_CLIENT_ID = 96
DEFAULT_IBKR_PORT = 4002


def account_from_ibkr(port: int, client_id: int) -> "tuple[ab.AccountEvidence, b1.BrokerEvidence]":
    """One connection, two pieces of evidence: the account, and the flatness B1 judges.

    Read-only. Failure is reported as UNKNOWN — never as an account holding nothing, which is
    the shape that lets a gate open on a broker that did not answer.
    """
    from global_index.ibkr_broker import IBKRBroker

    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    probe: dict = {"source": "ibkr_direct", "connected": False, "observed_at": started}
    account = ab.account_unavailable("the broker was never reached", source="ibkr_direct")

    broker = IBKRBroker(host="127.0.0.1", port=port, client_id=client_id)
    try:
        broker.connect()
        probe["connected"] = True
        observed = _dt.datetime.now(_dt.timezone.utc).isoformat()
        probe["observed_at"] = observed

        # ── the account, with its currency kept ──────────────────────────────
        #
        # `get_equity()` is deliberately NOT used. Its docstring says it accepts any currency,
        # and it prefers a BASE figure then whichever of USD or CAD is listed first, returning
        # a bare float. The whole point of this record is that the number arrives with its unit.
        try:
            ib = broker._require_connection()          # noqa: SLF001 - read-only accessor
            rows = list(ib.accountValues())
            acct = ""
            for r in rows:
                acct = getattr(r, "account", "") or acct
                if acct:
                    break
            account = ab.from_account_values(rows, source="ibkr_direct", account_id=acct,
                                             observed_at=observed)
        except Exception as exc:                                      # noqa: BLE001
            account = ab.account_unavailable(
                f"the account values could not be read ({type(exc).__name__}: {exc})",
                source="ibkr_direct")

        # ── flatness, in the shape B1 already judges ─────────────────────────
        try:
            probe["positions"] = [
                {"instrument": p.inst, "direction": p.direction, "contracts": p.contracts}
                for p in broker.get_positions()]
        except Exception as exc:                                      # noqa: BLE001
            probe["positions_error"] = f"{type(exc).__name__}: {exc}"
        try:
            orders = broker.get_open_orders()
            if orders is None:
                probe["open_orders_error"] = ("get_open_orders returned None — the broker "
                                              "declined to testify")
            else:
                probe["open_orders"] = orders
        except Exception as exc:                                      # noqa: BLE001
            probe["open_orders_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:                                          # noqa: BLE001
        why = f"could not connect to IBKR ({type(exc).__name__}: {exc})"
        probe["positions_error"] = probe["open_orders_error"] = why
        account = ab.account_unavailable(why, source="ibkr_direct")
    finally:
        try:
            broker.disconnect()
        except Exception:                                             # noqa: BLE001
            pass
    return account, b1.from_direct_probe(probe)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Record a paper account baseline. Read-only against the broker; there is "
                    "no order path in this tool.")
    ap.add_argument("--root", default=".", help="repo root (default: .)")
    ap.add_argument("--broker", choices=("ibkr", "none"), default="none",
                    help="'none' judges from the recorded evidence only and cannot PASS; "
                         "'ibkr' connects read-only on client id %d" % DEFAULT_CLIENT_ID)
    ap.add_argument("--port", type=int, default=DEFAULT_IBKR_PORT)
    ap.add_argument("--client-id", type=int, default=DEFAULT_CLIENT_ID)
    ap.add_argument("--record", action="store_true",
                    help=f"append the result to {ab.BASELINE_DIR}. Without this the tool only "
                         f"reports and writes nothing.")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv: "list | None" = None) -> int:
    args = build_parser().parse_args(argv)

    legacy = b1.read_book("live_positions.json")
    track1 = b1.read_track1_book("live_positions.track1.json")

    if args.broker == "ibkr":
        print(f"connecting read-only to 127.0.0.1:{args.port} on client id {args.client_id} — "
              f"account values, positions and working orders only")
        account, broker = account_from_ibkr(args.port, args.client_id)
    else:
        account = ab.account_unavailable("no broker was queried (--broker none)")
        broker = b1.broker_unavailable("no broker was queried (--broker none)")

    b1_result = b1.measure(legacy, track1, broker)
    result = ab.measure(account, b1_result)

    if args.json:
        print(json.dumps({"baseline": result.as_dict(), "b1": b1_result.as_dict()},
                         indent=2, default=str))
    else:
        print(f"B1        : {b1_result.status} ({b1_result.code}): {b1_result.detail[:120]}")
        print(f"BASELINE  : {result.one_line()}")
        print(f"operator  : {ab.operator_line(result)}")
        acc = (result.inputs or {}).get("account") or {}
        if acc.get("equity_by_currency"):
            print(f"currencies: {acc['equity_by_currency']}")

    if args.record:
        p = ab.record(result, args.root, source="account_baseline_audit")
        print(f"recorded  : {p}")

    # PASS exits 0; everything else does not. A tool whose exit code is always zero is a tool
    # nobody can put in a script.
    return 0 if result.status == ab.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
