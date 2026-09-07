"""Where a safety sweep writes its trade rows — one contract, both entry points.

`run_stop_repair` and `run_maxhold_exit` both hand a `trade_log_path` to `FuturesRunner`,
and until Stage 5ZG both hardcoded the same literal:

    trade_log_path=str(_CWD / "trade_log.jsonl")

That is correct for the legacy book and wrong for Track 1's. The scheduler already gives
the Track 1 copies of these two jobs their own positions file, kill switch, lock file and
client id — but not their own trade log, so the first Track 1 fill either of them ever
closed would have written a CLOSE row into the legacy log, in the legacy shape, with
nothing on the row to say which route produced it. There is one trade log on disk and
`paper_evidence_reader` aggregates all of it without splitting on anything, so that row
would have entered legacy's fill-quality and P&L gates as a legacy row.

The rule this module holds:

    no argument            -> the legacy log, byte for byte what it was before
    --trade-log-path P     -> P, and P must be writable NOW or the job fails
    --route R              -> every row this run writes carries route=R
    --route without a path -> refused

The last line is the one that matters. Inferring the destination from `--positions-path`
would have been fewer arguments and one silent failure mode: a caller who changed the book
but not the log would get legacy's log with no warning at all. The destination has to be
chosen on purpose, and choosing a route tag without choosing a destination is the mistake
that would tag rows `track1_candidate` inside legacy's file — distinguishable, but sitting
in the aggregate that must not contain them.

Why the writability probe happens before the positions check
------------------------------------------------------------
Both scripts return early when their positions file does not exist, which during the
shadow period is every single run: Track 1 holds nothing, so `live_positions.track1.json`
is absent and the sweep exits before it would ever touch a log. A check placed after that
return would therefore never execute in shadow, and a misconfigured path would first be
discovered by the first real fill — the worst possible moment to discover it.

Probed first, all eleven Track 1 safety jobs prove the destination writable every day
they run, months before there is anything to write. The probe is an append-open of the
real file rather than a permission bit on its directory, because an append-open is
exactly the operation `_append_trade_raw` will perform; a directory that is writable and
a file that is not is a real state and the weaker check passes it.

The probe creates the file empty on first success. That is wanted, not a side effect: a
reader can then tell "this route has never run a sweep" (no file) from "it ran and closed
nothing" (empty file), which absence alone cannot express.
"""
from __future__ import annotations

from pathlib import Path

#: What both jobs wrote before this module existed, and still write with no argument.
DEFAULT_TRADE_LOG = "trade_log.jsonl"


class TradeLogRefused(Exception):
    """The requested trade log cannot be honoured — the job must fail, not fall back.

    Never raised for the default path: an unwritable legacy log behaves exactly as it
    did before Stage 5ZG (the runner logs a warning per row and drops it), because
    changing that would change legacy safety behaviour.
    """


def resolve(trade_log_path: str | None,
            route: str | None,
            cwd: Path) -> "tuple[Path, str | None]":
    """Return (destination, route tag) or raise `TradeLogRefused`.

    `cwd` is the repository root; both entry points already refuse to start anywhere
    else, so a relative path is resolved against it rather than against the process
    working directory. That keeps `global_index/track1_runtime/...` meaning the same
    thing whether the scheduler spawned the child or an operator typed it by hand.
    """
    if route is not None and trade_log_path is None:
        raise TradeLogRefused(
            f"--route {route} was given without --trade-log-path. Tagging rows with a "
            f"route while still writing them into {DEFAULT_TRADE_LOG} puts them inside "
            f"the aggregate that must not contain them. Pass both, or neither.")

    if trade_log_path is None:
        return (cwd / DEFAULT_TRADE_LOG), None

    dest = Path(trade_log_path)
    if not dest.is_absolute():
        dest = cwd / dest

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise TradeLogRefused(
            f"cannot append to {dest}: {exc}. Refusing to run: the alternative is a "
            f"sweep that closes a position and records it nowhere, or worse, into "
            f"{DEFAULT_TRADE_LOG}.") from exc

    return dest, route
