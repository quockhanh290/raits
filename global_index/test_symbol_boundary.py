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
    assert _to_runner("MNK") == "MNKD"
    assert _to_runner("MES") == "MES", "names that agree pass through untouched"
    assert _to_runner("ZZZ") == "ZZZ", "an unknown symbol is not dropped or guessed"


def test_sb5_no_call_site_builds_a_contract_by_hand():
    """H1. Contract construction lives in ONE place, and the source says so.

    Appendix F consolidated three call sites (_fetch_raw, send_order, place_stop) into
    _front_month_contract and reported the job done. There were four. The roll path was
    missed, and it kept all three defects the consolidation existed to remove: the raw
    runner name as the IBKR symbol, exchange hardcoded "CME" (MYM is CBOT), and no conId
    check after qualifyContracts — which does not raise, it leaves conId 0.

    Same shape as sb2: enforced on the source, because a fifth hand-rolled site would
    otherwise stay invisible until a roll date arrived.

    Parsed, not grepped: the docstring of _front_month_contract discusses
    `ibi.Future(sym)` in prose, and a text scan counts that as a violation. A test that
    cannot tell code from a comment about code will fire on the next person who explains
    the rule in writing.
    """
    import ast

    tree = ast.parse(_SOURCE)
    builders = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "Future"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "ibi"):
                builders.add((fn.name, node.lineno))

    # Self-check: if the locator finds nothing, the invariant is unverified, not met.
    assert builders, (
        "no ibi.Future(...) call found anywhere — the locator is broken, so a green "
        "result here would mean nothing")

    # The invariant is "one builder", not "a builder with this name" — pinning the name
    # would make a rename look like a regression, and the defect was never about naming.
    where = sorted({name for name, _ln in builders})
    assert len(where) == 1, (
        "every contract must be built by ONE shared resolver, which translates the "
        "symbol, picks the exchange and refuses an unlisted contract. Built in "
        f"{len(where)} places: " + ", ".join(where))


class _RollIB:
    """Fake ib. Records what was asked for and whether qualifyContracts resolved it."""

    def __init__(self, resolve=True):
        self.built = []
        self._resolve = resolve

    def qualifyContracts(self, c):
        self.built.append(c)
        # Real ib_insync does NOT raise on an unresolvable contract; it leaves conId 0.
        if self._resolve:
            c.conId = 12345
        return [c]

    def sleep(self, _s):
        pass


class _RollFuture:
    def __init__(self, symbol, lastTradeDateOrContractMonth=None, exchange=None, **_kw):
        self.symbol = symbol
        self.lastTradeDateOrContractMonth = lastTradeDateOrContractMonth
        self.exchange = exchange
        self.conId = 0


def _roll_broker(monkeypatch, resolve=True):
    """IBKRBroker with a fake ib and a fake ib_insync, offline short-circuit removed.

    _handle_rollover returns synthetic fills while _raw_fetcher is set, which is exactly
    why no test ever reached its contract-building code (audit §4.4).
    """
    import types
    from global_index import ibkr_broker as B

    ib = _RollIB(resolve=resolve)
    fake_ibi = types.SimpleNamespace(Future=_RollFuture)
    monkeypatch.setitem(sys.modules, "ib_insync", fake_ibi)

    b = B.IBKRBroker(_raw_fetcher=lambda i, t: None)
    b._raw_fetcher = None
    b._require_connection = lambda: ib
    return b, ib


def test_sb6_the_roll_path_translates_the_symbol(monkeypatch):
    """MNKD must reach IBKR as MNK. C1 made this reachable: before the roll-schedule
    lookup was fixed the roll never fired for Nikkei, so `ibi.Future("MNKD", ...)` was
    dead code. Fixing C1 without this turns "never rolls" into "rolls into a contract
    IBKR cannot resolve"."""
    b, ib = _roll_broker(monkeypatch)
    try:
        b._handle_rollover("MNKD", "2026-09-04", "LONG", 1, "global_nkd")
    except Exception:
        pass  # the order path is not under test; the contracts are

    assert ib.built, "no contract was built — the test never reached the roll path"
    symbols = {c.symbol for c in ib.built}
    assert symbols == {"MNK"}, (
        f"the roll sent the runner's own name to IBKR; MNKD is not a listed symbol. "
        f"built={[(c.symbol, c.lastTradeDateOrContractMonth, c.exchange) for c in ib.built]}")


def test_sb7_the_roll_path_uses_the_right_exchange(monkeypatch):
    """MYM trades on CBOT. The roll path hardcoded "CME" for every instrument, and the
    first of the two orders it sends is the one that CLOSES the position. Next MYM roll:
    2026-09-11."""
    b, ib = _roll_broker(monkeypatch)
    try:
        b._handle_rollover("MYM", "2026-09-11", "LONG", 1, "roska4_swing")
    except Exception:
        pass

    assert ib.built, "no contract was built — the test never reached the roll path"
    exchanges = {c.exchange for c in ib.built}
    assert exchanges == {"CBOT"}, (
        f"MYM was sent to the wrong exchange; _IBKR_EXCHANGE declares CBOT. "
        f"built={[(c.symbol, c.exchange) for c in ib.built]}")


def test_sb8_the_roll_path_refuses_an_unlisted_contract(monkeypatch):
    """qualifyContracts leaves conId 0 rather than raising. Without a check, two market
    orders go out against a contract IBKR never confirmed — and the micro carries far
    fewer forward months than the full-size contract, so a ROLL_SCHEDULE date can outrun
    the listed chain."""
    from global_index.ibkr_broker import ContractResolutionError

    b, _ib = _roll_broker(monkeypatch, resolve=False)
    with pytest.raises(ContractResolutionError):
        b._handle_rollover("MNKD", "2026-09-04", "LONG", 1, "global_nkd")


def test_sb4_the_full_size_contract_is_not_adopted_as_ours():
    """NKD is the $5/pt contract; MNKD is the $0.50/pt micro. They are not the same size.

    Orders were routed to NKD until 2026-08-14 — four fills that cost $1,400 at the
    broker while the ledger booked $140. With routing fixed, a stray NKD position is
    something this system did not open and cannot size. Translating it back to MNKD
    would hand it to B4, which would compute a stop for the micro and place it against
    ten times the exposure.
    """
    assert _to_runner("NKD") == "NKD", (
        "NKD must stay unrecognised so it surfaces as an orphan rather than being "
        "managed as if it were the micro"
    )


def test_sb6_an_unschedulable_symbol_raises_instead_of_going_out_unqualified():
    """No ROLL_SCHEDULE entry used to fall through to ibi.Future(sym) with no month.

    IBKR rejects that as ambiguous whenever two months are live, and the rejection
    surfaces at the first bar fetch or the first order rather than at import. MNK would
    have hit exactly this after routing moved to it, because ROLL_SCHEDULE was keyed on
    NKD alone.
    """
    from global_index.ibkr_broker import ContractResolutionError, _front_month_contract

    class _IB:
        def qualifyContracts(self, *c):
            raise AssertionError("must not reach IBKR with an unschedulable symbol")

    class _Ibi:
        @staticmethod
        def Future(*a, **k):
            raise AssertionError("must not build a contract for an unschedulable symbol")

    with pytest.raises(ContractResolutionError) as e:
        _front_month_contract(_IB(), _Ibi(), "ZZZ")
    assert "ROLL_SCHEDULE" in str(e.value)


def test_sb7_a_month_the_exchange_does_not_list_raises():
    """qualifyContracts does not raise: ib_insync leaves conId 0 and logs a warning.

    ROLL_SCHEDULE rolls MNK to 202703 on 2026-12-04, but CME lists MNK only out to Z6
    (2 forward months against the full-size contract's 15, measured 2026-08-14). If
    MNKH7 is not listed by then the roll yields a contract that cannot resolve, and the
    old code would have sent the request anyway.
    """
    from global_index.ibkr_broker import ContractResolutionError, _front_month_contract

    class _Contract:
        conId = 0            # what ib_insync leaves behind when resolution fails

    class _IB:
        def qualifyContracts(self, *c):
            return []        # nothing qualified

    class _Ibi:
        @staticmethod
        def Future(*a, **k):
            return _Contract()

    with pytest.raises(ContractResolutionError) as e:
        _front_month_contract(_IB(), _Ibi(), "MNKD")
    assert "conId" in str(e.value)


def test_sb5_every_routed_symbol_has_a_roll_schedule():
    """_current_front_month returning None drops the call sites onto the unqualified
    contract branch, which IBKR rejects as ambiguous when two months are live. The
    failure lands on the first bar fetch or the first order, not at import."""
    from global_index.ibkr_broker import ROLL_SCHEDULE, _RAITS_TO_IBKR, _current_front_month

    for inst, ibkr_sym in _RAITS_TO_IBKR.items():
        assert ibkr_sym in ROLL_SCHEDULE, (
            f"{inst} routes to {ibkr_sym}, which has no ROLL_SCHEDULE entry; "
            f"ibi.Future({ibkr_sym!r}) without a month is ambiguous at IBKR"
        )
        assert _current_front_month(ibkr_sym), f"no front month resolves for {ibkr_sym}"


def test_sb8_the_order_symbol_is_never_the_data_symbol():
    """The exact substitution that produced C8.

    MNKD legitimately carries data_symbol="NKD" -- the backtest uses full-size Nikkei
    history because it starts in 2018 while micro data starts in 2024 Q4. The broker
    layer had no third field to read, so it read that one, and orders for the $0.50
    micro went to the $5 full-size contract for four days at ten times the intended
    size. Any future contract whose data root differs from its listed ticker walks
    into the same trap unless ibkr_symbol is set.
    """
    from futures.basket import BASKET
    from global_index.specs import SPECS

    for name, c in {**BASKET, **SPECS}.items():
        if c.data_symbol == name:
            continue
        assert c.ibkr != c.data_symbol, (
            f"{name} would be ordered as {c.data_symbol!r}, which is its DATA root, "
            f"not its listed contract; set ibkr_symbol explicitly"
        )


def test_sb9_the_routing_map_is_derived_from_the_specs_not_a_second_copy():
    """A hand-written map is a second copy of an instrument's identity, and the copy
    that drifts is the one that routes orders. Read the source: the map must be built
    from the contract objects, not typed out."""
    from global_index import ibkr_broker

    src = Path(ibkr_broker.__file__).read_text(encoding="utf-8")
    decl = re.search(r"_RAITS_TO_IBKR: dict\[str, str\] = \{(.*?)\n\}", src, re.S)
    assert decl, "_RAITS_TO_IBKR declaration not found"
    body = decl.group(1)
    assert "for name, contract in" in body, (
        "_RAITS_TO_IBKR is a literal again; derive it from Contract.ibkr so the two "
        "cannot disagree"
    )
    assert '"MNK"' not in body and "'MNK'" not in body, (
        "a ticker is hardcoded in the routing map; it belongs in specs.py only"
    )


def test_sb10_the_micro_nikkei_is_ordered_as_mnk():
    """Anchored to what IBKR returned on 2026-08-14: MNK is multiplier 0.5, NKD is 5."""
    from global_index.specs import SPECS

    assert SPECS["MNKD"].ibkr == "MNK"
    assert SPECS["MNKD"].point_value == 0.5
    assert SPECS["NKD"].ibkr == "NKD"
    assert SPECS["NKD"].point_value == 5.0


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
            return [_Pos("MNK", 1.0), _Pos("MES", -1.0)]
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
