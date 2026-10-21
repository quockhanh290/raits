from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


KEYWORDS = [
    "STOCKS_INTRADAY_FOCUSED_RULES",
    "FOCUSED_RULES",
    "stocks_intraday_rule_miner",
    "gapup_ge_0.03_short",
    "prevdown_-0.05_spy_down_long",
    "STOCKS_ML_RANKER",
    "rf_nolook",
]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    db = Path(os.environ["USERPROFILE"]) / ".codex" / "state_5.sqlite"
    con = sqlite3.connect(db)
    cur = con.cursor()
    rows = cur.execute(
        """
        select id, rollout_path, datetime(created_at, 'unixepoch'), datetime(updated_at, 'unixepoch'),
               cwd, title, first_user_message, preview
        from threads
        where cwd like '%raits%' or first_user_message like '%STOCKS%' or preview like '%STOCKS%'
        order by updated_at desc
        limit 80
        """
    ).fetchall()
    print("THREADS", len(rows))
    for row in rows:
        tid, rollout, created, updated, cwd, title, first, preview = row
        joined = "\n".join(str(x or "") for x in row)
        if any(k in joined for k in KEYWORDS) or "raits" in str(cwd).lower():
            print("---THREAD")
            print("id", tid)
            print("rollout", rollout)
            print("created", created, "updated", updated)
            print("cwd", cwd)
            print("title", title)
            print("first", (first or "")[:220].replace("\n", " "))
            print("preview", (preview or "")[:300].replace("\n", " "))
    con.close()

    roots = [Path(os.environ["USERPROFILE"]) / ".codex"]
    for root in roots:
        for p in root.rglob("*"):
            if not p.is_file() or p.stat().st_size > 50_000_000:
                continue
            name = str(p)
            if any(skip in name.lower() for skip in ["cache", "node_modules"]):
                continue
            try:
                data = p.read_text(errors="ignore")
            except Exception:
                continue
            hits = [k for k in KEYWORDS if k in data]
            if not hits:
                continue
            print("---FILE", p, hits)
            for hit in hits[:3]:
                idx = data.find(hit)
                lo = max(0, idx - 1500)
                hi = min(len(data), idx + 2500)
                print(data[lo:hi].replace("\x00", " ")[:4000])


if __name__ == "__main__":
    main()
