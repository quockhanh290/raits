"""global_index/route_params.py — strategy identity for a route checkpoint. NEW FILE.

Stage 1B of the Track 1 resume-primary plan. Pure functions only: no I/O, no engine
import, nothing that can decide a trade.

Why this exists
---------------
`replay_checkpoint._param_id` renders three settings — `ema_period`,
`chandelier_atr_mult`, `max_hold_days` — and that is the whole of the legacy checkpoint's
strategy identity. Track 1's Normal-R4 differs from legacy by its stop basis (2.0 x daily
ATR, entry-anchored), by having the ratchet off, by arming at a different hour, and by two
filters that decide which trades exist at all. **None of those four appear in the legacy
identity.** A Track 1 variant that changed only its stop would resume state computed under
the old one and nothing would notice.

So the rule here is the one `replay_checkpoint.usable` already states for its own narrower
case: *unknown is not the same as equal*. Every input that changes which position the bars
produce goes into the hash, or the checkpoint is fast and wrong.

Two artefacts, deliberately
---------------------------
`readable()` renders a sorted `k=v` string a person can read; `params_hash()` returns the
sha256 that actually decides. Both are kept for the reason `_param_id`'s docstring gives:
a refusal has to be explainable, and sixteen hex digits explain nothing. The hash decides,
the string says which setting moved.

`hashlib`, never Python's `hash()`
----------------------------------
`hash()` is salted per interpreter process (PYTHONHASHSEED), so the same config would hash
differently on every run and every checkpoint would be refused while looking like it was
working. Floats are rendered at fixed precision so `2.5` and `2.50` cannot disagree.

Adding a field
--------------
A field that cannot be tested is not added. Every name in FIELDS owes
`scratch/test_track1_route_checkpoint_stage1_20260822.py` a mutation assertion: change
that one field, the hash must move.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "route_params/1"

# Float rendering precision. Fixed rather than repr() so 2.5 and 2.50 render identically
# and a config round-tripped through JSON cannot change its own hash.
_FLOAT_FMT = "{:.10g}"

#: Every input that changes which position the bars produce.
#:
#: Grouped only for readability — the hash is computed over the flat sorted rendering, so
#: moving a name between groups does not change it. Each name owes a mutation test.
FIELDS: dict[str, tuple[str, ...]] = {
    "signal": ("ema_period", "max_hold_days"),
    # stop_anchor matters on its own: "entry" and "bar" put the same multiple in a
    # different place, and legacy carries the distinction in scratch/harness.py only.
    "stop": ("stop_basis", "stop_multiple", "stop_anchor", "ratchet"),
    # The hour alone is ambiguous — 14:00 means one instant for Ro 4 and another for NKD.
    "arming": ("arm_hour", "arm_timezone"),
    # A threshold derived from a window is a different thing when the window moves, so the
    # derivation window travels with the value rather than only the number it produced.
    # The SPY short gate travels as four fields, not one name. It is a market-wide filter
    # read from a file the futures data does not contain, so the file it came from and the
    # lag it was read at decide the answer as much as the rule does. Audited 2026-08-22:
    # it is applied unconditionally in the generator that produced the promotion artifacts,
    # ahead of the R4 context filter, so it belongs to the shipped Normal config rather
    # than to the filter layered on top.
    "filters": ("r4_range_threshold", "r4_range_derivation_window",
                "r4_rel_volume_max", "spy_short_filter", "spy_short_lookback",
                "spy_short_source_identity", "spy_short_lag_days"),
    # regime_csv_identity is expected to be "path:content-hash", not a bare path: two
    # files at different paths can hold the same labels and the same path can hold
    # different ones after an update.
    "regime": ("hmm_fit_end", "regime_csv_identity", "label_lag_days",
               "calm_gate_definition"),
    # Caps decide which candidates are ADMITTED, so a stored admitted position depends on
    # them exactly as much as it depends on the signal.
    "caps": ("cap_roska4_swing", "cap_roska4_calm", "cap_roska4_stress",
             "cap_global_nkd", "cap_family_normal_calm"),
    "cost": ("slippage_ticks_per_side", "commission_basis"),
    # fill_law: the promotion artifacts were built with every bar gap-eligible, while the
    # production engine only fills at the open after a real >15-minute break. Same bars,
    # different exits.
    "data": ("data_source_identity", "fill_law"),
    # Stage 5Q-9 — I-2. What the route TRADES, as opposed to what it reads.
    #
    # Until 2026-08-24 nothing here named the symbol an order is routed to, what a contract is
    # worth, or how size is derived. That is not a hypothetical gap: on 2026-08-14 MNKD orders
    # were found to be routing to the FULL-SIZE NKD contract at ten times the intended size —
    # measured from the broker statement at -$1,400.00 against -$140.00 in the sleeve ledger,
    # exactly 10.0000x — and correcting it would not have moved a single hash. A checkpoint
    # written before that discovery would have been accepted after it.
    #
    # `tradable_symbol` is the order identity and is deliberately SEPARATE from
    # `data_source_identity`: for MNKD they differ on purpose — bars come from full-size NKD,
    # which has history from 2018, while orders go to the $0.50 micro MNK. Collapsing the two
    # is the defect, in either direction, so the hash now carries both.
    #
    # `sizing_basis` decides which candidates are ADMITTED at all. Measured 2026-08-24:
    # moving the two ATR-stop sleeves between the two bases changes 166 admissions across
    # three windows and turns vault2026 from +$8,260 to +$5,872. A change that large must not
    # be able to happen without a refused checkpoint.
    "instrument": ("tradable_symbol", "point_value", "tick", "sizing_basis"),
}

#: Flat, sorted, canonical order. This is what is hashed.
ALL_FIELDS: tuple[str, ...] = tuple(sorted(n for g in FIELDS.values() for n in g))


class MissingParamError(ValueError):
    """A required field was absent.

    Absent is refused rather than defaulted. A default here would mean two different
    configs hashing the same because one of them simply forgot to say — which is the
    failure this module exists to prevent, arriving through the front door.
    """


def _render(value: Any) -> str:
    """One value, canonically. Rendering is part of the identity: if two callers can
    render the same value differently, the hash stops meaning what it claims."""
    if value is None:
        return "None"
    if isinstance(value, bool):          # before int — bool is an int subclass
        return "True" if value else "False"
    if isinstance(value, float):
        return _FLOAT_FMT.format(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_render(v) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{" + ",".join(f"{k}:{_render(value[k])}" for k in sorted(value)) + "}"
    return str(value)


def normalise(config: Mapping[str, Any]) -> dict[str, str]:
    """Config -> the exact {field: rendered} map that gets hashed.

    Exposed so a test can assert what went in, and so a refusal can diff two of these
    and name the field that moved instead of comparing two hashes.
    """
    missing = [f for f in ALL_FIELDS if f not in config]
    if missing:
        raise MissingParamError(
            f"route_params: missing required field(s) {missing}. Every field in "
            f"ALL_FIELDS must be supplied explicitly — an absent field is refused, not "
            f"defaulted, so two configs cannot hash alike because one forgot to say.")
    return {f: _render(config[f]) for f in ALL_FIELDS}


def readable(config: Mapping[str, Any]) -> str:
    """Sorted `k=v;k=v` string. Human-facing; not the thing that decides."""
    n = normalise(config)
    return ";".join(f"{f}={n[f]}" for f in ALL_FIELDS)


def params_hash(config: Mapping[str, Any]) -> str:
    """`sha256:<64 hex>` over the canonical rendering.

    Stable across processes: hashlib, not Python's salted hash(). Stable across a JSON
    round-trip: fixed float precision.
    """
    payload = json.dumps({"schema": SCHEMA, "fields": normalise(config)},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def identity(config: Mapping[str, Any]) -> tuple[str, str]:
    """`(readable, params_hash)` — the pair a checkpoint entry stores."""
    return readable(config), params_hash(config)


def diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """Which fields differ, as {field: (a_rendered, b_rendered)}.

    This is what turns `params_mismatch` from a refusal into a sentence naming the
    setting that moved.
    """
    na, nb = normalise(a), normalise(b)
    return {f: (na[f], nb[f]) for f in ALL_FIELDS if na[f] != nb[f]}
