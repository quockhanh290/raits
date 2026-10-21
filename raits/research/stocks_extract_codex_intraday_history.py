from __future__ import annotations

import json
import sys
from pathlib import Path


ROLL = Path(
    r"C:\Users\quock\.codex\sessions\2026\09\07"
    r"\rollout-2026-09-07T20-37-39-01a07ee0-d56d-7072-b930-388faa87023b.jsonl"
)

NEEDLES = (
    "STOCKS_INTRADAY_FOCUSED_RULES",
    "stocks_intraday_rule_miner",
    "stocks_intraday",
    "intraday",
    "focused",
    "gapup_ge_0.03_short",
    "prevdown_-0.05_spy_down_long",
    "rvol3_gapup0.005_short",
    "to_csv",
    "WFO",
    "TRADES",
)


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def text_of(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"ROLL={ROLL}")
    if not ROLL.exists():
        raise SystemExit("missing rollout")

    for lineno, line in enumerate(ROLL.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = row.get("timestamp") or row.get("ts") or ""
        if row.get("type") == "session_meta":
            continue
        typ = row.get("type")
        item = None
        if typ == "response_item":
            payload = row.get("payload", {})
            item = payload.get("item", payload)
        elif typ in {"item_started", "item_completed"}:
            item = row.get("item") or row.get("payload", {}).get("item", {})
        if item is not None:
            if item.get("type") == "function_call" and item.get("name") == "shell_command":
                args = json.loads(item.get("arguments") or "{}")
                cmd = args.get("command", "")
                if 1780 <= lineno <= 1925 or any(n in cmd for n in NEEDLES):
                    print("\n" + "=" * 100)
                    print(f"LINE {lineno} TS {ts} LEN {len(cmd)}")
                    print(cmd)
        if typ == "CommandExecution":
            cmd = row.get("command") or []
            body = cmd[-1] if cmd else ""
            if 1780 <= lineno <= 1925 or any(n in text_of(cmd) for n in NEEDLES):
                print("\n" + "=" * 100)
                print(f"LINE {lineno} TS {ts} STATUS {row.get('status')} LEN {len(body)}")
                print(body)


if __name__ == "__main__":
    main()
