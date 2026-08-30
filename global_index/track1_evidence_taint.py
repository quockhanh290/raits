"""Stage 5ZZZ-AA — which runtime evidence rows are known NOT to be live slot evidence.

Runtime evidence is append-only. When something writes a row that no slot produced — a test
run that was not output-isolated, say — the row cannot be deleted or edited, because rewriting
the operational record is a worse fault than the bad row. So the row stays, and this module
records that it is not to be believed.

**The taint record is itself append-only.** It names rows by the sha256 of their exact line, so
a taint entry can never widen to cover a row written later: a legitimate future row has a
different hash and is untouched by it.

Three states, and they are deliberately not two:

    tainted        proven not to be live slot evidence; readers must exclude or label it
    touched        a file was written during a contamination window but the specific rows
                   could not be identified. NOT tainted - tainting rows that might be real
                   would be the same falsification in the other direction
    clean          everything else

A tainted row must never be reported as PASS, and never as FAIL either. It is not evidence at
all, and scoring it in either direction reads as a statement about the route.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "track1_evidence_taint/1"
TAINT_DIR = "global_index/track1_runtime/evidence_taint"

#: the verdict readers use for a row this module has tainted. Deliberately not PASS or FAIL.
TAINTED = "TAINTED_TEST_EVIDENCE"


def _records(root: str | Path = ".") -> list:
    d = Path(root) / TAINT_DIR
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("evidence_taint_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue                      # a malformed entry taints nothing
            if rec.get("schema") == SCHEMA:
                out.append(rec)
    return out


def tainted_hashes(root: str | Path = ".") -> set:
    """Every row-sha256 any taint record marks as not-live-evidence."""
    out: set = set()
    for rec in _records(root):
        out |= set(rec.get("row_sha256") or [])
    return out


def touched_files(root: str | Path = ".") -> dict:
    """`{path: reason}` for files written during a contamination window whose specific rows
    could NOT be identified. These are reported, not excluded."""
    out = {}
    for rec in _records(root):
        for f in rec.get("touched_unproven") or []:
            out[f] = rec.get("reason", "")
    return out


def row_hash(line: str) -> str:
    """The identity a taint record uses: sha256 of the exact stored line."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def is_tainted(line: str, root: str | Path = ".") -> bool:
    """Is this exact stored line known not to be live slot evidence?"""
    return row_hash(line) in tainted_hashes(root)


def taint_for(line: str, root: str | Path = ".") -> dict | None:
    """The record that taints this line, so a reader can say WHY rather than just hiding it."""
    h = row_hash(line)
    for rec in _records(root):
        if h in set(rec.get("row_sha256") or []):
            return rec
    return None


def summary(root: str | Path = ".") -> dict:
    recs = _records(root)
    return {
        "schema": SCHEMA,
        "records": len(recs),
        "tainted_rows": len(tainted_hashes(root)),
        "touched_unproven_files": len(touched_files(root)),
        "note": ("a tainted row is excluded from evidence, never scored. It stays on disk: "
                 "append-only evidence is not rewritten"),
        "grants_nothing": True,
    }
