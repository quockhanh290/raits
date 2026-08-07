"""global_index/reconcile_statement.py — check trade_log against IBKR's statement.

The runner writes trade_log, so it can only be as right as the runner was. Every gap
found this week came from a different failure and none of them were visible from inside:

  2026-08-03  three filled OPENs read back as Cancelled → no fill price logged, and one
              whole trade (M2K SHORT 2988.00 → 2993.20) left no trace anywhere local.
  2026-08-05  a stop fired. The runner sends no order for that, so nothing wrote a CLOSE.
  2026-08-06  the same again.

A statement is the one account the runner did not author. This compares the two and
reports the difference; --backfill writes the missing trades into trade_log.

Pairing comes from global_index.statement, the same code the reconcile uses, so a
backfilled trade and a checked trade can never mean different things.

    python -X utf8 global_index/reconcile_statement.py --csv <statement.csv>
    python -X utf8 global_index/reconcile_statement.py --csv <statement.csv> --backfill

Exit code 0 = the log agrees with the statement, 1 = it does not.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from global_index.statement import pair_fifo, parse_transactions

# Positions the runner opened before it started recording cluster reliably. The
# statement cannot supply this — IBKR has no idea what a cluster is — and the whole
# analytics side of the dashboard is keyed on it. Recorded in TASK.md for 2026-08-03.
_KNOWN_CLUSTER = {
    ("MES", "2026-08-03"): "roska4_swing",
    ("MYM", "2026-08-03"): "roska4_swing",
    ("M2K", "2026-08-03"): "roska4_swing",
}
_DEFAULT_CLUSTER = "roska4_swing"


def _load_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _log_closed(records: list[dict]) -> dict:
    """{(inst, entry_day, exit_day): record} for what the log calls a closed trade."""
    return {(r["inst"], r.get("entry_day"), r.get("exit_day")): r
            for r in records if r.get("type") == "CLOSE"}


def _log_opens(records: list[dict]) -> dict:
    return {(r["inst"], r.get("entry_day")): r
            for r in records if r.get("type") == "OPEN"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True, help="IBKR Transaction History CSV")
    ap.add_argument("--log", default=str(_ROOT / "trade_log.jsonl"))
    ap.add_argument("--backfill", action="store_true",
                    help="write the trades the statement has and the log does not")
    a = ap.parse_args()

    log_path = Path(a.log)
    records = _load_log(log_path)
    trades, cash = parse_transactions(a.csv)
    closed, open_lots = pair_fifo(trades)

    have_closed, have_opens = _log_closed(records), _log_opens(records)

    print(f"statement: {len(trades)} fills → {len(closed)} closed, {len(open_lots)} open")
    print(f"trade_log: {len(records)} records → {len(have_closed)} closed\n")

    print(f"{'inst':<5} {'dir':<6} {'entry':<12} {'exit':<12} {'in':>10} {'out':>10} "
          f"{'P&L':>10}  verdict")
    print("-" * 88)

    missing, mismatched, total = [], [], 0.0
    for c in sorted(closed, key=lambda x: (x["exit_day"], x["inst"])):
        key = (c["inst"], c["entry_day"], c["exit_day"])
        rec = have_closed.get(key)
        op = have_opens.get((c["inst"], c["entry_day"]))
        total += c["pnl"] or 0.0
        if rec is None:
            verdict = "MISSING from log"
            missing.append(c)
        elif abs((rec.get("fill_price") or 0) - c["exit_price"]) > 1e-6:
            verdict = f"PRICE MISMATCH log={rec.get('fill_price')}"
            mismatched.append((c, rec))
        elif op is None:
            verdict = "entry price missing from log"
            missing.append(c)
        else:
            verdict = "ok"
        print(f"{c['inst']:<5} {c['direction']:<6} {c['entry_day']:<12} {c['exit_day']:<12} "
              f"{c['entry_price']:>10.2f} {c['exit_price']:>10.2f} "
              f"{(c['pnl'] if c['pnl'] is not None else 0):>+10.2f}  {verdict}")
    print("-" * 88)
    print(f"{'':<58}realised: {total:>+10.2f} USD")

    for lot in open_lots:
        print(f"  still open: {lot['inst']:<5} "
              f"{'LONG' if lot['signed'] > 0 else 'SHORT':<5} @ {lot['price']:.2f} "
              f"({lot['date']})")

    if cash:
        print("\nnon-trade cash in the same period — these reach the sleeve ledger "
              "through H4 and are NOT strategy P&L:")
        by_type: dict = {}
        for c in cash:
            by_type[c["type"]] = by_type.get(c["type"], 0.0) + c["amount"]
        for k, v in sorted(by_type.items(), key=lambda kv: -abs(kv[1])):
            print(f"    {k:<22} {v:>+12.2f}")

    if not missing and not mismatched:
        print("\nPASS — the log agrees with the statement")
        return 0

    print(f"\nFAIL — {len(missing)} missing, {len(mismatched)} mismatched")
    if not a.backfill:
        print("re-run with --backfill to write the missing trades")
        return 1

    shutil.copy2(log_path, log_path.with_suffix(".jsonl.bak"))
    added = 0
    with open(log_path, "a", encoding="utf-8") as fh:
        for c in missing:
            cluster = _KNOWN_CLUSTER.get((c["inst"], c["entry_day"]), _DEFAULT_CLUSTER)
            base = {"inst": c["inst"], "cluster": cluster,
                    "direction": c["direction"], "contracts": int(c["contracts"]),
                    "status": "FILLED", "source": "backfill:activity_statement"}
            if (c["inst"], c["entry_day"]) not in have_opens:
                fh.write(json.dumps({**base, "type": "OPEN",
                                     "entry_day": c["entry_day"],
                                     "fill_price": c["entry_price"],
                                     "ts": f"{c['entry_day']}T00:00:00+00:00"}) + "\n")
                added += 1
            if (c["inst"], c["entry_day"], c["exit_day"]) not in have_closed:
                fh.write(json.dumps({**base, "type": "CLOSE",
                                     "entry_day": c["entry_day"],
                                     "exit_day": c["exit_day"],
                                     "fill_price": c["exit_price"],
                                     "ts": f"{c['exit_day']}T00:00:00+00:00"}) + "\n")
                added += 1
    print(f"appended {added} record(s); backup at {log_path.name}.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
