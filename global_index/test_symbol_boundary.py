"""global_index/test_symbol_boundary.py — one vocabulary leaves IBKRBroker

IBKR calls the Nikkei contract NKD; the runner calls it MNKD. _RAITS_TO_IBKR exists for
exactly that, but it was applied ad hoc at each call site, so the sites that forgot were
invisible until a position existed.

Six such sites were found one at a time — place_stop, cancel_order, get_order_status,
has_working_stop, get_working_stops, and finally get_positions, which on 2026-08-10
reported the live NKD position under a name the file did not use. B3 then counted the
same position twice, once as missing and once as an orphan, and halted every entry.

The rule is not "remember the mapping". It is that nothing leaves this class speaking
IBKR's vocabulary, and the source itself is checked so the seventh site cannot be added
quietly.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.ibkr_broker import IBKRBroker, _to_runner

_SOURCE = (Path(__file__).resolve().parent / "ibkr_broker.py").read_text(encoding="utf-8")


def test_sb1_the_translation_is_one_function():
    assert _to_runner("NKD") == "MNKD"
    assert _to_runner("MES") == "MES", "names that agree pass through untouched"
    assert _to_runner("ZZZ") == "ZZZ", "an unknown symbol is not dropped or guessed"


def test_sb2_every_symbol_read_goes_through_it():
    """The invariant, enforced on the source rather than on memory.

    Any new `x.contract.symbol` that is not wrapped is the seventh site, and it would
    otherwise stay invisible until an NKD position happened to exist.
    """
    offenders = []
    for n, line in enumerate(_SOURCE.splitlines(), 1):
        code = line.split("#", 1)[0]
        if "contract.symbol" not in code:
            continue
        # Allowed shapes: _to_runner(x.contract.symbol), or the definition itself.
        if not re.search(r"_to_runner\(\s*[\w.]*contract\.symbol", code):
            offenders.append(f"{n}: {line.strip()}")
    assert not offenders, (
        "these read an IBKR symbol without translating it — wrap in _to_runner():\n  "
        + "\n  ".join(offenders))


def test_sb3_positions_report_runner_names():
    """The site that halted live trading. get_positions feeds B3, which compares its
    inst against live_positions.json — a file written in the runner's vocabulary."""
    class _Pos:
        def __init__(self, sym, qty):
            self.contract = type("C", (), {"symbol": sym})()
            self.position = qty

    class _IB:
        def positions(self):
            return [_Pos("NKD", 1.0), _Pos("MES", -1.0)]
        def sleep(self, _s):
            pass

    b = IBKRBroker(_raw_fetcher=lambda i, t: None)
    b._raw_fetcher = None
    b._require_connection = lambda: _IB()

    by_inst = {p.inst: p.direction for p in b.get_positions()}
    assert by_inst == {"MNKD": "LONG", "MES": "SHORT"}, (
        f"B3 compares these against the file's names; got {by_inst}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
