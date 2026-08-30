"""global_index/track1_paper_callsite.py — the dry run for the paper call site. NEW FILE.

Stage 5Z. **Imported by nothing, and it cannot send an order even if it were.** The broker it
builds is a wall: every read says "cannot say" and `send_order` raises by name.

What a dry run is for
---------------------
Every piece between a decision and a broker now exists — the mapping (5T), the state machine
(5U), the fail-closed journal (5V), the executor (5W), the tri-state reads (5X), the order id
(5Y). None of them has ever run in sequence. A rehearsal that stops at the last inch is how you
find out whether they fit before the inch that matters.

Six stages, and the sixth is a wall:

    gate                 what the REAL blocker table says right now
    reconcile_precheck   would a restart be allowed to enter at all
    executor             can the executor even be constructed
    mapping              every admitted decision -> a broker.Order
    journal              INTENDED and SUBMITTED, durable, in a REDIRECTED root
    boundary             the broker refuses, by name

Where the seam actually is
--------------------------
Not where Stage 5W said. That report named `run_shadow`'s `NoOrderBroker()` line, and both
halves of that are wrong:

  * `run_shadow` replays a whole measured WINDOW. The scheduler's 70 strategy slots run
    `observe_live_slot`, which is a different function and takes no gate and no broker;
  * in `run_shadow` the broker object is never passed to anything. It is constructed and then
    read once, for `len(broker.calls)`, to prove nothing was sent. Swapping it for a real
    broker would change nothing at all, because no code hands it an order.

The seam is in `observe_live_slot`, immediately after

    settlements, decisions = run_candidates(found, book=book)

which is the first and only moment a live slot holds admitted decisions. `seam()` below
derives that location from the file rather than restating it, because a comment naming a line
number is a comment that will be wrong.

What the dry run leaves behind
------------------------------
Rows. Deliberately. `INTENDED`, `SUBMITTED`, and then `UNKNOWN` when the wall raises — which is
the correct record of "we were about to send and could not see what happened", and is exactly
the crash-path rehearsal worth having. They land in a REDIRECTED root, never the production
one, and `assert_dry_run_root` refuses if anyone points it at the real journal.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from global_index import track1_broker_read as br
from global_index import track1_order_journal as journal
from global_index import track1_order_state as st
from global_index import track1_paper_executor as ex
from global_index import track1_paper_order as po

#: The six stages, in order. Data rather than prose so a report can walk them and a test can
#: assert none was skipped.
STAGES: tuple = ("gate", "reconcile_precheck", "executor", "mapping", "journal", "boundary")

#: Refusal codes.
BOUNDARY_REACHED = "dry_run_boundary_reached"
PRODUCTION_ROOT = "dry_run_refuses_production_journal_root"
NOT_A_DRY_RUN = "dry_run_broker_is_not_the_wall"

#: Where a dry run is allowed to keep its journal, relative to the root it is given.
DRY_RUN_DIRNAME = "track1_dry_run"


class PaperCallsiteRefused(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── the wall ─────────────────────────────────────────────────────────────────────────────

class RefusingBroker:
    """Has every method the executor demands and answers nothing.

    `CAN_TESTIFY = False` so `track1_broker_read` refuses to believe its empty reads — an
    empty answer from a broker that was never connected means "never asked", not "flat".
    `send_order` raises rather than returning a synthetic fill, for the same reason
    `NoOrderBroker` does: a rehearsal that quietly produced fills would build a book nobody
    could distinguish from a traded one.
    """

    CAN_TESTIFY = False

    def __init__(self) -> None:
        self.attempts: list = []

    def send_order(self, order, *, on_submit=None):
        self.attempts.append(order)
        raise PaperCallsiteRefused(
            BOUNDARY_REACHED,
            f"the dry run reached the broker boundary with {order.action} "
            f"{order.direction} x{order.contracts} {order.inst}. Nothing was sent. This is "
            f"the wall, and reaching it is the success condition")

    # present so the executor can be constructed; none of them testifies
    def get_positions(self): return None
    def get_open_orders(self): return None
    def get_order_status(self, order_id): return br.STATUS_NOT_FOUND
    def find_execution(self, order_id, inst=None): return None
    def cancel_order(self, order_id): return False
    def place_stop(self, *a, **k): return ""


@dataclass(frozen=True)
class DryRunGate:
    """A synthetic gate, so the executor can be built while the real one is shut.

    It is a separate type from `ProductionGate` on purpose: `isinstance` tells them apart, and
    a test asserts the real gate still refuses. Arming the rehearsal is not arming anything.
    """

    allow_orders: bool = True
    synthetic: bool = True


# ── where the seam is, derived rather than described ─────────────────────────────────────

def seam(root: str | Path = ".") -> dict:
    """The exact production location a paper call site would occupy, read from the file.

    Derived, not written down. Stage 5W wrote the location into a report and it was wrong by
    the time anyone checked — wrong function, and a line whose object is never used.
    """
    p = Path(root) / "global_index" / "run_live_day_track1.py"
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()

    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot"), None)
    if fn is None:
        raise PaperCallsiteRefused(
            NOT_A_DRY_RUN, "observe_live_slot is gone; the live slot path has moved")

    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "run_candidates"]
    if len(calls) != 1:
        raise PaperCallsiteRefused(
            NOT_A_DRY_RUN,
            f"observe_live_slot holds {len(calls)} run_candidates calls; the seam is the one "
            f"moment a live slot holds admitted decisions, and it must be unambiguous")

    at = calls[0].lineno
    return {
        "file": "global_index/run_live_day_track1.py",
        "function": "observe_live_slot",
        "function_lines": [fn.lineno, fn.end_lineno],
        "after_line": at,
        "anchor": lines[at - 1].strip(),
        "why_here": ("the first and only moment a live slot holds admitted decisions"),
        "not_run_shadow": ("run_shadow replays a measured window and is not what the "
                           "scheduler runs; its broker object is never passed to anything, "
                           "only read for len(broker.calls)"),
    }


# ── the guard on where a rehearsal may write ─────────────────────────────────────────────

def dry_run_root(root: str | Path = ".") -> Path:
    """The redirected journal root, and the only one a dry run may use."""
    return Path(root) / DRY_RUN_DIRNAME


def assert_dry_run_root(candidate: str | Path, *, production_root: str | Path = ".") -> Path:
    """Refuse anything that would put rehearsal rows where a real reconcile reads.

    A dry-run journal is indistinguishable from a real one once written: the route stamp is
    the same, the schema is the same, and it will contain rows that read as unresolved orders.
    The ONLY thing keeping them apart is the directory, so the directory is checked hard.
    """
    cand = Path(candidate).resolve()
    real = (Path(production_root) / journal.ORDERS_DIR).resolve()
    if cand == real or real in cand.parents or cand in real.parents:
        raise PaperCallsiteRefused(
            PRODUCTION_ROOT,
            f"{cand} touches the production order journal at {real}. Rehearsal rows carry "
            f"the same route stamp and the same schema as real ones, and a reconcile pointed "
            f"at them would read unresolved orders that never existed")
    return cand


# ── the report ───────────────────────────────────────────────────────────────────────────

@dataclass
class StageResult:
    name: str
    ok: bool
    detail: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class DryRunReport:
    stages: list = field(default_factory=list)
    orders_mapped: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    reached_boundary: bool = False
    journal_rows: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """A dry run SUCCEEDS by being stopped at the wall.

        Not by completing. If `reached_boundary` were false the rehearsal never got as far as
        the thing it exists to test, and every earlier stage passing would mean nothing.
        """
        return self.reached_boundary and all(s.ok for s in self.stages)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reached_boundary": self.reached_boundary,
            "stages": [{"name": s.name, "ok": s.ok, "detail": s.detail, **s.data}
                       for s in self.stages],
            "orders_mapped": len(self.orders_mapped),
            "refusals": list(self.refusals),
            "journal_rows": [{"state": r.state, "instrument": r.instrument,
                              "order_id": r.order_id} for r in self.journal_rows],
        }


# ── the rehearsal ────────────────────────────────────────────────────────────────────────

def dry_run(decisions: Sequence[Any], *, ref_day: str, slot_id: str = "",
            root: str | Path = ".", journal_root: str | Path | None = None,
            broker: Any = None) -> DryRunReport:
    """Walk every stage a real call site would, and stop at the broker.

    `decisions` is what `run_candidates` returns at the seam. Only the admitted ones are
    mapped; the rest are counted, because "nothing was admitted" and "nothing was offered" are
    different days and a report that shows one number for both is useless.
    """
    rep = DryRunReport()
    target = assert_dry_run_root(
        journal_root if journal_root is not None else dry_run_root(root),
        production_root=root)

    wall = broker if broker is not None else RefusingBroker()
    if not isinstance(wall, RefusingBroker):
        # A caller may pass a fake for a test, but it must still be a wall.
        try:
            wall.send_order(object())
        except PaperCallsiteRefused:
            pass
        except Exception as exc:
            raise PaperCallsiteRefused(
                NOT_A_DRY_RUN,
                f"the supplied broker did not refuse by name ({type(exc).__name__}); a dry "
                f"run may only be handed something that cannot send")
        else:
            raise PaperCallsiteRefused(
                NOT_A_DRY_RUN, "the supplied broker accepted an order")

    # 1 ── what the real gate says. The rehearsal proceeds anyway, on a synthetic gate, and
    #      records the true answer so a reader can never mistake one for the other.
    real = ex.production_gate()
    rep.stages.append(StageResult(
        "gate", True,
        f"production gate allow_orders={real.allow_orders}; rehearsing on a synthetic gate",
        {"production_allow_orders": bool(real.allow_orders),
         "production_reasons": [r.split(":")[0] for r in real.reasons]}))

    # 2 ── would a restart be allowed to enter at all
    reader = br.Track1BrokerReader(wall)
    pos = reader.positions()
    book, book_detail = ex.read_book(Path(root) / ex.BOOK_PATH)
    would_block = not pos.known
    rep.stages.append(StageResult(
        "reconcile_precheck", True,
        f"book: {book_detail}; broker positions: {pos.detail}",
        {"book_positions": len(book), "broker_positions_known": pos.known,
         "entries_would_be_blocked": would_block}))

    # 3 ── can the executor be built
    executor = ex.Track1OrderExecutor(broker=wall, gate=DryRunGate(), journal_root=target)
    cap = ex.broker_capability_report(wall)
    rep.stages.append(StageResult(
        "executor", True, "constructed against the wall",
        {"reports_order_id_at_placement": cap["reports_order_id_at_placement"],
         "fill_carries_order_id": cap["fill_carries_order_id"]}))

    # 4 ── mapping
    admitted, mapped = [], []
    from global_index import track1_signal_layer as T
    for d in decisions:
        if getattr(d, "verdict", None) != T.TAKE:
            continue
        admitted.append(d)
        try:
            mapped.append(po.candidate_to_order(d.candidate, ref_day=ref_day, action="OPEN"))
        except po.PaperOrderRefused as exc:
            rep.refusals.append(f"mapping/{exc.code}: {exc.detail[:160]}")
    rep.orders_mapped = mapped
    rep.stages.append(StageResult(
        "mapping", len(rep.refusals) == 0,
        f"{len(mapped)} of {len(admitted)} admitted decision(s) mapped "
        f"({len(decisions)} offered)",
        {"offered": len(decisions), "admitted": len(admitted), "mapped": len(mapped)}))

    # 5 + 6 ── journal, then the wall. These are one call: `open_position` writes INTENDED and
    #          SUBMITTED and only then reaches the broker, which is the whole ordering under
    #          test. Separating them here would rehearse an order the real path never takes.
    reached = 0
    for d in admitted:
        try:
            executor.open_position(d, ref_day=ref_day, slot_id=slot_id)
        except PaperCallsiteRefused:
            reached += 1
        except po.PaperOrderRefused:
            pass          # already counted at the mapping stage
    rows, invalid = journal.read(root=target, day=str(ref_day).replace("-", ""))
    rep.journal_rows = rows
    rep.reached_boundary = reached > 0 and reached == len(mapped)
    rep.stages.append(StageResult(
        "journal", not invalid,
        f"{len(rows)} row(s) under {target}",
        {"rows": len(rows), "invalid": len(invalid),
         "states": [r.state for r in rows]}))
    rep.stages.append(StageResult(
        "boundary", rep.reached_boundary,
        f"{reached} of {len(mapped)} order(s) stopped at the wall",
        {"attempts": len(getattr(wall, "attempts", [])), "sent": 0}))
    return rep


# ── what a real call site would still need ───────────────────────────────────────────────

#: Measured, not assumed. Each entry is (operation, who covers it today, what is missing).
#:
#: The finding that matters: **the protective stop and the max-hold exit are already covered.**
#: `run_stop_repair` and `run_maxhold_exit` are registered as 11 Track 1 safety jobs against
#: `live_positions.track1.json`, and B3/B4 run inside `FuturesRunner.__init__` — they place
#: stops and book exits. They no-op today only because that book file does not exist. So the
#: first paper fill does not leave a naked position; it ACTIVATES eleven jobs that have never
#: run against anything, which is a larger blast radius than the entry itself.
COVERAGE: tuple = (
    ("open_position", "the executor (Stage 5W)", "nothing — built and rehearsed"),
    ("place_protective_stop", "run_stop_repair, B4 inside FuturesRunner.__init__",
     "no journal row: a stop placed by the safety job is invisible to the order journal"),
    ("close_position (max hold)", "run_maxhold_exit, B3/B4",
     "same: books the exit and writes trade_log, not the order journal"),
    ("close_position (strategy exit)", "nobody",
     "the sleeves' own exits have no path to a broker at all"),
    ("switch_same_symbol", "nobody — track1_switch is imported by NOTHING",
     "it calls broker.send_order at two sites with no journal; if it is ever wired it must "
     "go through the executor, or two orders leave no record"),
)
