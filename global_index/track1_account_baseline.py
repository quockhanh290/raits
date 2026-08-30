"""global_index/track1_account_baseline.py — is the paper account safe to start from?

Stage 5ZZE. Pure measurement. **This module never constructs a broker** — it is named
`track1_*`, and the live-frame gate scans every such file for anything that obtains live data, so
a connection here would close that gate and manufacture a blocker. The connecting half lives in
`account_baseline_audit.py`, deliberately outside the prefix, for the same reason `b1_audit.py`
was renamed in Stage 5ZQ after exactly that mistake.

What this adds to B1, and the measurement that showed B1 was not enough
-----------------------------------------------------------------------
B1 already proves the books are flat, the broker holds no positions and no working orders stand.
What it does not ask is **which account that was** and **in what currency**.

Measured on 2026-08-27 against the live B1 record, taken 19.77 hours earlier and therefore still
inside its own 24-hour window:

    recorded equity   996,875.91      (no currency recorded anywhere in the row)
    stated baseline   250,000
    drift             299%

The account had been reset underneath a PASS. B1's freshness window is about POSITIONS AND
ORDERS, and a reset changes neither — so the record went on vouching for an account that no
longer existed, and nothing in it could have said so.

`IBKRBroker.get_equity()` cannot close that gap either. Its own docstring says "Accept any
currency (CAD/USD/BASE accounts all work)", and the code prefers a `BASE` figure, then whichever
of USD or CAD the broker happens to list first, then anything at all — returning a bare float. A
baseline built on it would record "equity 250000" for an account holding two hundred and fifty
thousand Canadian dollars, and nobody could tell afterwards.

So the account probe reads the currency-tagged values and keeps the label attached to the number,
all the way into the record.

Three states, not two
---------------------
The same discipline B1 carries. `currency=None` means nobody asked or the ask failed; it is not
"not USD". An account that could not be read is UNKNOWN, and UNKNOWN never satisfies the gate.

The attribution caveat, carried forward
---------------------------------------
On a shared login, **zero is attributable and non-zero is not**. Seeing no positions proves no
route holds one. Seeing three proves only that the login holds three — which of them belongs to
this route is a question this evidence cannot answer, and the record says so rather than
implying an owner.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "track1_account_baseline/1"
ROUTE = "track1_candidate"

#: Durable, beside the rest of the route's runtime evidence — not scratch. A baseline that lives
#: only in a report is a baseline the gate cannot read.
BASELINE_DIR = "global_index/track1_runtime/account_baseline"

# ── verdicts ─────────────────────────────────────────────────────────────────
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
STATUSES = (PASS, WARN, FAIL, UNKNOWN)

#: Only PASS satisfies the readiness gate. WARN and FAIL both refuse — the difference between
#: them is what an operator does next, not what the gate does. A gate with a maybe in it is a
#: gate somebody argues with.
SATISFIES_GATE = (PASS,)

# ── reason codes ─────────────────────────────────────────────────────────────
OK = "account_flat_and_funded"
CURRENCY_WRONG = "account_currency_not_usd"
CURRENCY_UNKNOWN = "account_currency_unknown"
EQUITY_UNKNOWN = "account_equity_unknown"
EQUITY_OFF_BAND = "account_equity_outside_expected_band"
EQUITY_IMPLAUSIBLE = "account_equity_implausible"
BROKER_NOT_QUERIED = "broker_not_queried"
OBSERVATION_STALE = "broker_observation_stale"
B1_NOT_PASSING = "b1_not_passing"
B1_MISSING = "b1_record_missing_or_stale"
NO_RECORD = "no_baseline_recorded"
RECORD_UNREADABLE = "baseline_record_unreadable"
RECORD_STALE = "baseline_record_stale"

# ── the contract, stated as numbers ──────────────────────────────────────────
#: What the account is expected to hold after the reset. The RECORD keeps the OBSERVED figure;
#: this is only the sanity band the observation is judged against, so a deliberate re-funding to
#: a different size is a one-line change here rather than a silent drift in what "fine" means.
EXPECTED_CURRENCY = "USD"
EXPECTED_EQUITY = 250_000.0

#: Within this fraction of the expected figure, the account is what it is supposed to be. Five
#: per cent of 250k is 12,500 — wide enough for fees, marks and a partial day, narrow enough
#: that a mis-funded account cannot hide inside it.
EQUITY_PASS_FRACTION = 0.05
#: Beyond this the number is not a variation on the expectation; it is a different account or a
#: different currency being read. Twenty-five per cent of 250k is 62,500 — and the reading that
#: prompted this module was 299% away, which is what that end of the scale looks like.
EQUITY_FAIL_FRACTION = 0.25

#: How old a broker observation may be and still count as "now".
MAX_OBSERVATION_MINUTES = 30
#: How long a recorded baseline stands before it must be taken again.
MAX_RECORD_AGE_HOURS = 24


class BaselineRefused(Exception):
    """Raised only for a caller error — a malformed evidence object, never a bad account."""


# ══════════════════════════════════════════════════════════════════════════════
# what the account said
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AccountEvidence:
    """What the broker reported about the ACCOUNT, with the currency still attached.

    Keeping the pair inseparable in the type is cheaper than remembering to check: a number
    whose unit was lost is the defect this module exists for.
    """
    source: str
    connected: bool | None = None
    observed_at: str = ""
    account_id: str = ""
    currency: str | None = None
    equity: float | None = None
    #: every NetLiquidation the account reported, by currency, so a reader can see whether the
    #: account is single-currency or whether one was chosen from several.
    equity_by_currency: dict = field(default_factory=dict)
    error: str = ""

    @property
    def currency_known(self) -> bool:
        return bool(self.currency)

    @property
    def equity_known(self) -> bool:
        return self.equity is not None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["currency_known"] = self.currency_known
        d["equity_known"] = self.equity_known
        return d


def account_unavailable(reason: str, source: str = "none") -> AccountEvidence:
    """The account could not be read. NOT an account holding nothing."""
    return AccountEvidence(source=source, connected=False, error=reason)


def from_account_values(rows, *, source: str = "ibkr", account_id: str = "",
                        observed_at: str = "") -> AccountEvidence:
    """Evidence from IBKR `accountValues()` rows: objects or mappings with tag/currency/value.

    Keeps every currency-tagged NetLiquidation rather than picking one. Picking is a judgement,
    and the judgement belongs in `measure`, where it can be reported instead of buried — which
    is precisely what `get_equity` does not do.
    """
    by_ccy: dict = {}
    for r in rows or ():
        if _field(r, "tag") != "NetLiquidation":
            continue
        ccy = str(_field(r, "currency") or "").upper()
        try:
            val = float(_field(r, "value"))
        except (TypeError, ValueError):
            continue
        if ccy:
            by_ccy[ccy] = val

    if not by_ccy:
        return AccountEvidence(source=source, connected=True, account_id=account_id,
                               observed_at=observed_at or _now(),
                               error="the account reported no NetLiquidation in any currency")

    # The expected currency when it is there; otherwise the account is reported as it actually
    # is, and `measure` refuses on the mismatch — rather than this function quietly substituting
    # a number in the wrong unit.
    ccy = EXPECTED_CURRENCY if EXPECTED_CURRENCY in by_ccy else sorted(by_ccy)[0]
    return AccountEvidence(source=source, connected=True, account_id=account_id,
                           observed_at=observed_at or _now(),
                           currency=ccy, equity=by_ccy[ccy], equity_by_currency=dict(by_ccy))


def _field(row: Any, name: str):
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


# ══════════════════════════════════════════════════════════════════════════════
# the judgement
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BaselineResult:
    status: str
    code: str
    detail: str
    checked_at: str
    inputs: dict = field(default_factory=dict)
    findings: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {"schema": SCHEMA, "route": ROUTE, **asdict(self)}
        # Said in every record rather than left to the reader: what a zero here does and does
        # not establish on a login more than one route can reach.
        d["attribution"] = ("zero positions is attributable to every route; a non-zero count "
                            "is attributable to none")
        return d

    def one_line(self) -> str:
        return f"{self.status} ({self.code}): {self.detail}"


def measure(account: AccountEvidence, b1: Any, *, now: Any = None,
            max_observation_minutes: int = MAX_OBSERVATION_MINUTES) -> BaselineResult:
    """PASS only when the account is USD, funded as expected, and B1 says everything is flat.

    B1 is REQUIRED rather than re-derived. Asking the books and the positions again here would
    be a second implementation of a question that already has one, and two implementations of
    "is it flat" is how they come to disagree on the morning it matters.

    Order: a KNOWN wrong thing outranks an unknown one, exactly as B1 orders its own findings.
    """
    from global_index import track1_b1 as _b1

    checked = _iso(now)
    inputs = {"account": account.as_dict(),
              "b1": {"status": getattr(b1, "status", None), "code": getattr(b1, "code", None),
                     "detail": getattr(b1, "detail", "")}}
    findings: dict = {}

    # ── known-wrong first ────────────────────────────────────────────────────
    if account.currency_known and account.currency != EXPECTED_CURRENCY:
        findings["currency"] = account.currency
        return BaselineResult(
            FAIL, CURRENCY_WRONG,
            f"the account reports {account.currency}, not {EXPECTED_CURRENCY}. Every size, "
            f"stop distance and cap on this route is a USD figure; running them against "
            f"another currency is not a smaller version of the same thing",
            checked, inputs, findings)

    if account.equity_known:
        eq = float(account.equity)
        drift = abs(eq - EXPECTED_EQUITY) / EXPECTED_EQUITY if EXPECTED_EQUITY else 0.0
        findings["equity"] = eq
        findings["expected"] = EXPECTED_EQUITY
        findings["drift_fraction"] = round(drift, 6)
        if eq <= 0:
            return BaselineResult(
                FAIL, EQUITY_IMPLAUSIBLE,
                f"the account reports {eq:,.2f} {account.currency or '(no currency)'}. An "
                f"account with nothing in it cannot be the baseline for anything",
                checked, inputs, findings)
        if drift > EQUITY_FAIL_FRACTION:
            return BaselineResult(
                FAIL, EQUITY_IMPLAUSIBLE,
                f"the account reports {eq:,.2f} against an expected {EXPECTED_EQUITY:,.2f} — "
                f"{drift:.0%} away. At that distance this is a different account or a "
                f"different currency being read, not a variation on the expected one",
                checked, inputs, findings)

    # ── B1 second: the books and the broker's own flatness ───────────────────
    if getattr(b1, "status", None) == _b1.FAIL:
        return BaselineResult(
            FAIL, B1_NOT_PASSING,
            f"B1 reports a known risk and the account cannot be a starting point until it is "
            f"cleared: {getattr(b1, 'detail', '')}", checked, inputs, findings)

    # ── then the things nobody answered ──────────────────────────────────────
    if account.connected is False or (not account.currency_known and not account.equity_known):
        return BaselineResult(
            UNKNOWN, BROKER_NOT_QUERIED,
            f"the account was not read ({account.error or 'no reason recorded'}). Unknown is "
            f"not flat and it is not funded", checked, inputs, findings)
    if not account.currency_known:
        return BaselineResult(
            UNKNOWN, CURRENCY_UNKNOWN,
            "the account answered but did not say which currency it is denominated in. A "
            "number without its unit is not evidence", checked, inputs, findings)
    if not account.equity_known:
        return BaselineResult(
            UNKNOWN, EQUITY_UNKNOWN,
            "the account's currency is known and its balance is not", checked, inputs, findings)
    if getattr(b1, "status", None) != _b1.PASS:
        return BaselineResult(
            UNKNOWN, B1_MISSING,
            f"B1 is {getattr(b1, 'status', None) or 'absent'} ({getattr(b1, 'code', '')}): "
            f"{getattr(b1, 'detail', '')}. This is not 'the books are flat'",
            checked, inputs, findings)

    stale = _observation_age_minutes(account.observed_at, now)
    findings["observation_age_minutes"] = stale
    if stale is None:
        return BaselineResult(
            UNKNOWN, OBSERVATION_STALE,
            "the account reading carries no usable timestamp, so its age cannot be judged",
            checked, inputs, findings)
    if stale > max_observation_minutes:
        return BaselineResult(
            UNKNOWN, OBSERVATION_STALE,
            f"the account was read {stale} minutes ago, beyond the {max_observation_minutes} "
            f"a reading may stand for. A position could have been opened since",
            checked, inputs, findings)

    # ── everything answered, nothing wrong; how far off is it? ───────────────
    drift = findings.get("drift_fraction", 0.0)
    if drift > EQUITY_PASS_FRACTION:
        return BaselineResult(
            WARN, EQUITY_OFF_BAND,
            f"the account holds {account.equity:,.2f} {account.currency} against an expected "
            f"{EXPECTED_EQUITY:,.2f} — {drift:.1%} away. Inside the plausible range and outside "
            f"the expected one: either the reset landed on a different figure or something has "
            f"moved. The gate does not open on a WARN",
            checked, inputs, findings)

    return BaselineResult(
        PASS, OK,
        f"{account.currency} {account.equity:,.2f}, no positions, no working orders, both books "
        f"flat and route-stamped, read {stale} minute(s) ago",
        checked, inputs, findings)


# ══════════════════════════════════════════════════════════════════════════════
# the record
# ══════════════════════════════════════════════════════════════════════════════

def record_path(root: str | Path = ".", day: str | None = None) -> Path:
    d = (day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    return Path(root) / BASELINE_DIR / f"account_baseline_{d}.jsonl"


def record(result: BaselineResult, root: str | Path = ".", *, source: str = "") -> Path:
    """Append one baseline. Appends only — a baseline that overwrote its predecessor would make
    "when did this account last look right" unanswerable."""
    p = record_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = result.as_dict()
    if source:
        row["recorded_by"] = source
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return p


def latest(root: str | Path = ".", *, now: Any = None,
           max_age_hours: "int | None" = None) -> BaselineResult:
    """The most recent baseline, or an UNKNOWN saying why there is not one.

    Never returns a PASS it did not read. An absent record and a stale one are different answers
    and both refuse.

    `max_age_hours` defaults to None and is resolved from the module constant HERE, at call
    time, rather than being bound into the signature. A default argument is evaluated once when
    the function is defined, so `MAX_RECORD_AGE_HOURS` written into the signature would look
    exactly like the setting and change nothing when anybody set it — the same shape as a
    comment that has drifted from the code it describes. A mutation test found it by patching
    the constant and watching the stale record still come back as a PASS.
    """
    max_age_hours = MAX_RECORD_AGE_HOURS if max_age_hours is None else max_age_hours
    d = Path(root) / BASELINE_DIR
    files = sorted(d.glob("account_baseline_*.jsonl")) if d.is_dir() else []
    rows: list = []
    for f in reversed(files):
        try:
            rows = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
        except Exception as exc:                                      # noqa: BLE001
            return BaselineResult(UNKNOWN, RECORD_UNREADABLE,
                                  f"{f.name} could not be read ({type(exc).__name__}: {exc})",
                                  _iso(now))
        if rows:
            break
    if not rows:
        return BaselineResult(
            UNKNOWN, NO_RECORD,
            f"no account baseline has been recorded under {BASELINE_DIR}. A check that never "
            f"ran is not a check that passed", _iso(now))

    last = rows[-1]
    age = _record_age_hours(last.get("checked_at"), now)
    if age is None:
        return BaselineResult(UNKNOWN, RECORD_STALE,
                              "the newest baseline carries no usable timestamp", _iso(now),
                              last.get("inputs") or {}, last.get("findings") or {})
    if age > max_age_hours:
        return BaselineResult(
            UNKNOWN, RECORD_STALE,
            f"the newest baseline is {age:.1f}h old, beyond the {max_age_hours}h it stands "
            f"for. An account can be reset or traded in between — which is exactly what "
            f"happened to the B1 record this module was written after",
            _iso(now), last.get("inputs") or {}, last.get("findings") or {})
    return BaselineResult(str(last.get("status") or UNKNOWN), str(last.get("code") or ""),
                          str(last.get("detail") or ""), str(last.get("checked_at") or ""),
                          last.get("inputs") or {}, last.get("findings") or {})


def operator_line(result: BaselineResult) -> str:
    """One line an operator can act on, in the words a person uses."""
    f = result.findings or {}
    acc = (result.inputs or {}).get("account") or {}
    ccy, eq = acc.get("currency"), acc.get("equity")
    # A record whose account block did not survive — an old schema, a hand-edited row, a stub —
    # must still produce a line. The first version formatted the equity unconditionally and
    # raised TypeError on a PASS with no inputs, which would have taken the whole readiness
    # call down with it: a reporting function that can crash is a reporting function that turns
    # a mild problem into no report at all.
    money = f"{ccy} {eq:,.0f}" if (ccy and eq is not None) else "an unrecorded amount"
    if result.status == PASS:
        return f"Paper account baseline: {money} — broker reconcile flat"
    if result.status == WARN:
        return (f"Paper account baseline: {money}, expected {EXPECTED_EQUITY:,.0f} — "
                f"{f.get('drift_fraction', 0):.1%} away")
    if result.status == FAIL:
        return f"Paper account NOT a safe baseline: {result.detail}"
    return f"Paper account baseline UNKNOWN: {result.detail}"


# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _iso(now: Any) -> str:
    return _now() if now is None else str(now)


def _parse(ts: Any):
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _observation_age_minutes(observed_at: Any, now: Any) -> "int | None":
    t = _parse(observed_at)
    if t is None:
        return None
    ref = _parse(now) or _dt.datetime.now(_dt.timezone.utc)
    return int((ref - t).total_seconds() // 60)


def _record_age_hours(checked_at: Any, now: Any) -> "float | None":
    t = _parse(checked_at)
    if t is None:
        return None
    ref = _parse(now) or _dt.datetime.now(_dt.timezone.utc)
    return (ref - t).total_seconds() / 3600.0
