"""global_index/track1_params.py — the Track 1 route's declared identity. NEW FILE.

Stage 3. Offline and pure except for reading file bytes to compute a content hash: nothing
here connects to a broker, starts a service, or decides a trade.

What this file is
-----------------
One place that says what the Track 1 route IS, per sleeve, in the vocabulary
`global_index/route_params.py` already defines. It exists so that the answer to "which
strategy produced this checkpoint entry" is a hash rather than a memory, and so that a
sleeve whose settings moved gets a `PARAMS_MISMATCH` refusal naming the setting instead of
a fast wrong resume.

Why the Normal sleeve does NOT match the Stage 2B bootstrap
-----------------------------------------------------------
`scratch/track1_bootstrap_checkpoint_20260822.py` pins the Normal sleeve as
`ema_period=30, stop_basis=chandelier_atr, stop_multiple=2.5, ratchet=True`. Those are the
LEGACY engine's settings and they were correct for what that bootstrap did — it seeded a
checkpoint from the legacy engine running on parquet.

Track 1's Normal-R4 is a different engine: ema 50, a fixed entry-anchored stop at
2.0 x daily ATR, ratchet off, armed 14:05 the next session, plus two context filters. So
the identity below deliberately does NOT match the file currently on disk at
`replay_checkpoint.track1.json`, and a Track 1 Normal sleeve asking to resume from it will
be refused. That refusal is the mechanism working. Do not loosen the identity to make it
pass; re-bootstrap under these params once the Track 1 Normal engine is promoted.

Where every value comes from
----------------------------
Each field is sourced in SOURCES below, and a field with no source is not added. That rule
is inherited from the Stage 2B bootstrap, which had to carry the same discipline: a number
in a config that nobody can point at is a number that will drift and take a checkpoint
with it.

The identity fields are CONTENT HASHES, not paths. Two files at different paths can hold
the same bars, and the same path can hold different bars after an update — which is exactly
what the 13:45 ET append does to the parquet every trading day.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from global_index import route_params as rp
from global_index.route_checkpoint import DEFAULT_ROUTE

ROUTE = DEFAULT_ROUTE                      # "track1_candidate"

#: The four sleeves this route runs, and the instruments each may touch.
SLEEVE_INSTRUMENTS: dict[str, tuple[str, ...]] = {
    "roska4_swing":  ("MES", "MNQ", "MYM", "M2K"),
    "global_nkd":    ("MNKD",),
    "roska4_calm":   ("MES", "MNQ"),
    "roska4_stress": ("MNQ",),
}

#: Contracts per position, BY SLEEVE. Legacy sizes by instrument alone
#: (`contracts_by_inst[inst]`), which cannot express MNQ=1 under Normal and MNQ=7 under
#: Stress on the same day. That is Stage 2D's BLOCK-4 and this is the fix: quantity is a
#: property of the candidate, and this table is only the default a candidate inherits.
SLEEVE_QTY: dict[str, int] = {
    "roska4_swing":  1,
    "global_nkd":    1,
    "roska4_calm":   1,
    "roska4_stress": 7,
}

#: How each sleeve's `risk_dollars` — the ONE number the cap gate reads — is derived.
#:
#: Stage 5Q-9, I-3. These were never the same thing and nobody had compared them. Two sleeves
#: carry a real stop price in their artifacts and their risk IS the stop distance. The other
#: two carry no stop at all: their measured risk is a MULTIPLE-OF-ATR proxy, `MULT x daily ATR
#: x pv x qty` with MULT = 2.5, while the stop those sleeves actually place is 2.0 x daily ATR.
#: Exactly 1.25x, on all 938 roska4_swing and all 285 global_nkd rows across three windows —
#: not a distribution, a constant.
#:
#: The live route had been sizing all four on the true stop distance, which is the more honest
#: number and is NOT what the measured book was admitted under. Replaying the committed
#: candidate stream through the real `Track1Book` on both bases:
#:
#:      window      taken (artifact -> true stop)   booked P&L           changed admissions
#:      floor        1160 -> 1234                   $64,903 -> $71,982     129
#:      vault2025     128 ->  144                   $13,236 -> $16,585      20
#:      vault2026      91 ->   98                    $8,260 ->  $5,872      17
#:
#: 166 admissions move, in BOTH directions (128 reject->take, 33 take->reject, the rest
#: same-symbol shuffles), because shrinking two sleeves and not the other two also reorders
#: `process_instant`'s risk-high-first queue. vault2026 gets 7 more trades and $2,388 LESS.
#: Three of the moved rows are Calm A, whose own risk never changed — contention, not sizing.
#:
#: So the choice is a RE-RATE, not a refinement, and the route keeps the basis its published
#: Calmar, MaxDD and net were measured under. Switching to the true stop distance is a
#: deliberate decision that has to re-rate Track 1 first; it is not a tidy-up, and this table
#: plus `sizing_basis` in the identity hash is what stops it happening by accident.
SIZING_ARTIFACT_ATR = "artifact_mult_x_daily_atr"
SIZING_TRUE_STOP = "true_stop_distance"

SIZING_BASIS: dict[str, str] = {
    "roska4_swing":  SIZING_ARTIFACT_ATR,
    "global_nkd":    SIZING_ARTIFACT_ATR,
    "roska4_calm":   SIZING_TRUE_STOP,
    "roska4_stress": SIZING_TRUE_STOP,
}


def _contract(inst: str):
    """The one contract record for `inst`, from the two tables that own them.

    `futures.basket.BASKET` holds the Rổ-4 micros and `global_index.specs.SPECS` the Nikkei
    pair; both expose `name`, `ibkr`, `point_value` and `tick`. Merged in that order because
    it is the order `ibkr_broker._RAITS_TO_IBKR` merges them in, and two layers reading one
    instrument through two different merges is how an identity drifts.
    """
    from futures.basket import BASKET
    from global_index import specs as _specs

    table = {**BASKET, **_specs.SPECS}
    try:
        return table[inst]
    except KeyError:
        raise ValueError(
            f"no contract record for {inst!r}; the route cannot state what it would trade, "
            f"and an identity that omits that is the gap Stage 5Q-9 closed") from None


def sizing_atr_mult(sleeve: str) -> float:
    """The proxy multiple, read from the module that produced the artifacts.

    Imported rather than restated: `signal_layer.ROSKA4_MULT` and `NKD_MULT` are the constants
    the measured book was sized with, and a literal here could drift from them silently.
    """
    from global_index.signal_layer import NKD_MULT, ROSKA4_MULT

    return {"roska4_swing": ROSKA4_MULT, "global_nkd": NKD_MULT}[sleeve]


def risk_dollars(sleeve: str, *, entry: float, stop: float, daily_atr: float | None,
                 point_value: float, qty: int) -> "tuple[float, str]":
    """`(risk, basis_name)` for one candidate. The single place the route sizes anything.

    Returns the basis alongside the number so a caller cannot record one and compute the
    other — which is exactly the defect this function was written to remove.
    """
    basis = SIZING_BASIS[sleeve]
    if basis == SIZING_TRUE_STOP:
        return abs(float(entry) - float(stop)) * float(point_value) * int(qty), basis
    if daily_atr is None or not (float(daily_atr) > 0):
        raise ValueError(
            f"{sleeve} sizes on {basis} and needs a positive daily ATR; got {daily_atr!r}. "
            f"Falling back to the stop distance here would silently size 20% light against "
            f"caps measured on the proxy.")
    return (sizing_atr_mult(sleeve) * float(daily_atr) * float(point_value) * int(qty), basis)


#: Cluster budgets, as fractions of the account. `None` net means gross-only.
CAPS: dict[str, tuple[float, float | None]] = {
    "roska4_swing":  (0.050, 0.044),
    "roska4_calm":   (0.050, None),
    "roska4_stress": (0.100, None),
    "global_nkd":    (0.060, 0.060),
}

#: Normal + Calm are one correlation family and share a combined cap on top of their own.
FAMILY_CLUSTERS: tuple[str, ...] = ("roska4_swing", "roska4_calm")
FAMILY_GROSS: float = 0.050
FAMILY_NET: float = 0.044

ACCOUNT: float = 50_000.0

#: Detection windows, ET. Used by the window ledger and by the entry point's slot gate.
#:
#: `roska4_swing` was added in Stage 5M-B and its bounds are not a choice: they mirror the
#: legacy entry slots minute for minute — 14:05 through 15:55, every five minutes, 23 slots.
#: The sleeve's measured rule scans from the 14:00 resume bar and takes the FIRST admitted
#: signal, so the first decidable instant is the 14:05 bar and the timing IS the sleeve. An
#: offset window would be a different rule that resembles it, and shadow evidence gathered
#: under it would not be evidence about the thing that was backtested.
#: `global_nkd` was added in Stage 5N and mirrors the legacy NKD night slots minute for
#: minute — 01:10 through 02:55 ET, every five minutes, 22 slots. These are ET times because
#: the SCHEDULER is ET-native; the sleeve itself decides on the Tokyo session clock, and the
#: correspondence between the two shifts with US DST (01:10 ET is 14:10 JST in summer and
#: 15:10 JST in winter — Japan has no DST). That drift is LEGACY'S EXISTING BEHAVIOUR: its
#: cron is fixed in ET too, so in winter the late slots fire after the Tokyo session window
#: has closed and the early part of the window has no slot. Mirroring means inheriting that,
#: and fixing it would be a rule change dressed as plumbing.
WINDOWS_ET: dict[str, tuple[str, str]] = {
    "roska4_calm":   ("10:00", "10:00"),
    "roska4_stress": ("10:35", "12:30"),
    "roska4_swing":  ("14:05", "15:55"),
    "global_nkd":    ("01:10", "02:55"),
}

#: The window a CANDIDATE's entry stamp is judged against, for sleeves whose session clock is
#: not ET — declared in the sleeve's OWN clock. Stage 5N, and found by measurement rather
#: than foresight: judging the committed NKD replay rows against the ET slot band rejected
#: 26 of them and shrank the accepted tail from 91 to 67, because the artifacts stamp
#: entries on the Tokyo session clock (aware, +09:00) where the measured rule actually
#: decides. The ET table above answers "when do slots fire"; this one answers "when may the
#: rule enter" — the two coincide for every US sleeve and drift apart for Tokyo with US DST,
#: which is legacy's own behaviour inherited, not a new rule.
SESSION_WINDOWS: dict[str, tuple[str, str]] = {
    "global_nkd": ("14:10", "15:55"),
}
SESSION_WINDOW_CLOCKS: dict[str, str] = {
    "global_nkd": "Asia/Tokyo",
}

#: Where each field's value comes from. A field absent here must not be added above.
SOURCES: dict[str, str] = {
    "ema_period": "Track 1 spec: Normal-R4 ema 50; MNKD keeps the promoted sleeve's 10",
    "max_hold_days": "futures/basket.py SWING_TF_PARAM['max_hold_days'] = 5, unchanged",
    "stop_basis": "Track 1 spec: fixed entry +/- 2.0 x daily ATR, not a chandelier. TRUE OF "
                  "BOTH sleeves that use this engine: global_nkd is Normal-R4 at ema 10 and "
                  "carries the same entry-anchored band (Stage 5Q-9, I-1)",
    "stop_multiple": "Track 1 spec: 2.0 for Normal-R4 AND for global_nkd. This said "
                     "\"MNKD keeps 2.5\" until 2026-08-24, describing legacy NKD; the "
                     "committed MNKD artifact reproduces exactly at 2.0 (Stage 5Q-9, I-1)",
    "stop_anchor": "Track 1 spec: anchored at the ENTRY price and never moved; legacy anchors "
                   "on the running extreme through the prior bar",
    "ratchet": "Track 1 spec: OFF for both sleeves on this engine. This said the MNKD "
               "sleeve kept it on until 2026-08-24 — legacy did, this one never has",
    "arm_hour": "Track 1 spec: armed 14:05 next session, on each sleeve's OWN clock — "
                "14:05 ET for Ro 4, 14:05 JST for global_nkd, both from "
                "track1_normal_r4.ARM_HOURS = 14 + 5/60 applied to a day taken from the "
                "frame's index. This said MNKD was 14:00 JST until 2026-08-24, which was "
                "legacy's hour (Stage 5Q-9, I-1). Rendered HH:MM rather than as a number — "
                "14:05 as a float hour is 14.0833.. and a reader cannot check it",
    "arm_timezone": "global_index/runner.py _ARM_BY_CLUSTER — per sleeve, declared as a zone "
                    "rather than an ET offset because ET<->JST moves with DST",
    "r4_range_threshold": "scratch/normal_promotion_filter_lib_20260821.py FLOOR_RANGE_P90",
    "r4_range_derivation_window": "same file header: p90 frozen on the floor window 2018-2024 "
                                  "by normal_sleeve_context_combo_probe_20260821.py",
    "r4_rel_volume_max": "scratch/normal_promotion_filter_lib_20260821.py VOL_LE",
    "spy_short_filter": "scratch/normal_promotion_regen_audit_20260821.py:121,131 — applied "
                        "unconditionally in the generator that WROTE the promotion artifacts, "
                        "ahead of the R4 context filter",
    "spy_short_lookback": "scratch/directional_market_filter_probe.py: spy.rolling(50).mean()",
    "spy_short_lag_days": "same line: the close compared is spy.shift(1); proven causal by "
                          "mutation 2026-08-22 (scale the close at D by ten, D is unchanged "
                          "and D+1 moves)",
    "spy_short_source_identity": "computed here: spy_daily_live.csv + sha256 of its bytes",
    "hmm_fit_end": "futures/basket.py REGIME['hmm_fit_end']",
    "regime_csv_identity": "computed here: spy_daily_live.csv + sha256 of its bytes",
    "label_lag_days": "R4 reads label_regimes directly (0); MNKD wraps it in "
                      "RegimeLabels(lag_days=1) because the Tokyo power hour precedes the "
                      "US close",
    "calm_gate_definition": "docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md — "
                            "D-1 Calm causal, prior-close location bottom-down, gap not deep",
    "cap_roska4_swing": "Track 1 spec: Normal+Calm family 5.0% gross / 4.4% net",
    "cap_roska4_calm": "same family cap",
    "cap_roska4_stress": "Track 1 spec: Stress-MNQ mnq_only_g3_q7 cap 10% gross-only",
    "cap_global_nkd": "Track 1 spec: current NKD/MNKD qty 1 cap 6%",
    # Stage 5Q-9 — I-2. What the route TRADES, beside what it reads.
    "tradable_symbol": "global_index/specs.py + futures/basket.py Contract.ibkr — the SAME "
                       "attribute ibkr_broker._RAITS_TO_IBKR is built from, read one step "
                       "earlier so the two cannot disagree. MNKD -> MNK; every other "
                       "instrument is its own name",
    "point_value": "the same Contract record: MNKD $0.50 (micro), MES $5, MNQ $2, MYM $0.50, "
                   "M2K $5. In the hash because the 2026-08-14 routing defect changed the "
                   "effective multiplier by 10x and moved no identity at all",
    "tick": "the same Contract record. Slippage is already hashed as ticks-per-side, so the "
            "SIZE of a tick decides what that costs",
    "sizing_basis": "global_index/track1_params.SIZING_BASIS — which of the two risk formulas "
                    "the cap gate is fed. Measured 2026-08-24: moving the two ATR-stop "
                    "sleeves between the bases changes 166 admissions across three windows "
                    "and turns vault2026 from +$8,260 to +$5,872 (Stage 5Q-9, I-3)",
    "cap_family_normal_calm": "Track 1 spec: Normal+Calm combined 5.0% gross / 4.4% net",
    "slippage_ticks_per_side": "generate_replay_snapshots.py SLIPPAGE = 2.0, the value the "
                               "measured artifacts were produced under — NOT deploy_sim's "
                               "CLI default of 1.0",
    "commission_basis": "global_index/specs.py commission_rt via futures.swing_tf.costs_for_basket",
    "data_source_identity": "computed here per instrument: parquet path + sha256 of file bytes",
    "fill_law": "the law the RUN used, passed in by the caller — global_index/track1_normal_r4"
                ".NormalR4Params.fill_law. Both were measured across floor/vault2025/vault2026 "
                "and the book-level difference over seven years was $0 to +$6, which is why a "
                "wrong literal here went unnoticed: an immaterial P&L delta does not make an "
                "identity true. Stage 4B made it an argument with no default.",
}

#: Conflicts that were settled by measurement rather than by preference, and what settled
#: them. Kept beside the values for the same reason the Stage 2B bootstrap keeps its copy:
#: a settled conflict that does not name its evidence is indistinguishable from a guess.
DECIDED_BY_MEASUREMENT: dict[str, str] = {
    "fill_law": "scratch/track1_three_blockers_report_20260822.md section 2 — twelve "
                "regenerations through the shipped generator, both laws, all three windows",
    "spy_short_filter": "scratch/track1_three_blockers_report_20260822.md section 1 — removing "
                        "the gate costs -11,663 to -14,143 at book level on the floor window "
                        "and widens MaxDD by 31%",
}

#: Fields with no defensible source. Must stay empty; a non-empty entry is a declaration
#: that the route is running on a number nobody can point at.
UNSOURCED: dict[str, str] = {}


def file_identity(path: str | Path) -> str:
    """`<path>:<sha256>` for a file, or `<path>:MISSING`.

    Never raises. A missing file has to reach the caller as a value that cannot match any
    recorded identity, because a route that treats "I could not read it" as "it is the
    same" is the fail-open shape this project has already paid for.
    """
    p = Path(path)
    try:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return f"{p.as_posix()}:MISSING"
    return f"{p.as_posix()}:{digest}"


#: The two fill laws, named here so a caller cannot invent a third by typo. They are the same
#: two `global_index/track1_normal_r4.py` selects between, and the string that reaches the
#: identity hash is the one the run actually used.
FILL_ARTIFACT = "artifact_all_bars_gappable"
FILL_PRODUCTION = "production_gap_after_15min_break"
FILL_LAWS = (FILL_ARTIFACT, FILL_PRODUCTION)

#: The law the Track 1 LIVE and SHADOW route runs — one name, one place. Stage 5M-1.
#:
#: Adopted by the three-blockers report of 2026-08-22, which measured both laws by
#: monkeypatching the ONE generator that produced the committed artifacts, in process, so
#: nothing was re-implemented. The production law is the more permissive of the two and is
#: therefore worth slightly MORE: $0 to +$6 at book level across floor, vault2025 and
#: vault2026, against a book netting $75,288. The published Track 1 numbers were measured
#: under the more conservative law, so nothing needs re-rating.
#:
#: The delta is immaterial. The identity is not. This string is hashed into `params_hash`,
#: and a checkpoint is accepted or refused on that hash — so a route whose identity names a
#: law it did not run would accept state computed under the other one. That is the defect
#: Stage 4B removed from this file when `fill_law` was a hard-coded literal here; naming the
#: route's law once, here, is what stops it coming back as a default nobody passed.
#:
#: Live and shadow callsites reference THIS, not `NormalR4Params().fill_law`. Reading the
#: engine's dataclass default to decide what the route records would make the route's
#: identity a side effect of an engine default — right today, because Stage 5M-1 also moved
#: that default to the production law, and silently wrong the day someone moves it back for a
#: reproduction run.
LIVE_FILL_LAW = FILL_PRODUCTION


def _base(regime_csv: str, fill_law: str) -> dict[str, Any]:
    if fill_law not in FILL_LAWS:
        raise ValueError(f"fill_law must be one of {FILL_LAWS}, got {fill_law!r}")
    ident = file_identity(regime_csv)
    return {
        "r4_range_threshold": 0.02652437134968455,
        "r4_range_derivation_window": "floor_2018_2024_p90",
        "r4_rel_volume_max": 2.0,
        "spy_short_filter": "d1_spy_close_below_sma50_for_shorts_only",
        "spy_short_lookback": 50,
        "spy_short_lag_days": 1,
        "spy_short_source_identity": ident,
        "hmm_fit_end": "2024-12-31",
        "regime_csv_identity": ident,
        # The audited sentence, not a shorter label invented here. Taken verbatim from
        # the Stage 2B bootstrap so that two producers of this identity cannot disagree
        # about what the Calm gate IS while agreeing about everything else.
        "calm_gate_definition":
            "pcloc_bottom_third_of_prior_rth_range AND prior_rth_down_close_below_open "
            "AND gap_from_prev_rth_close>=-0.01 LONG MES,MNQ entry=10:00 exit=15:55 lag1",
        "cap_roska4_swing": CAPS["roska4_swing"][0],
        "cap_roska4_calm": CAPS["roska4_calm"][0],
        "cap_roska4_stress": CAPS["roska4_stress"][0],
        "cap_global_nkd": CAPS["global_nkd"][0],
        "cap_family_normal_calm": FAMILY_GROSS,
        "slippage_ticks_per_side": 2.0,
        "commission_basis": "round_turn_per_contract",
        # Passed in, never assumed. This was a hard-coded literal until Stage 4B, and it was
        # WRONG: it declared the production law while every measured Track 1 row had been
        # generated with every bar gap-eligible. The P&L difference is immaterial, which is
        # exactly why it survived — but an identity is not a P&L estimate. It is the thing a
        # checkpoint is accepted or refused on, and one that names a law the run did not use
        # would accept state computed under the other.
        "fill_law": fill_law,
    }


def sleeve_config(sleeve: str, inst: str, *, regime_csv: str,
                  data_path: str | Path, fill_law: str) -> dict[str, Any]:
    """The full identity for one instrument inside one sleeve.

    Every one of `route_params.ALL_FIELDS` is filled explicitly. `normalise` refuses a
    missing field rather than defaulting it, and that refusal is the point: an absent
    setting is unknown, and unknown is not the same as equal.
    """
    cfg = _base(regime_csv, fill_law)
    cfg["data_source_identity"] = file_identity(data_path)

    # Stage 5Q-9 — I-2. What the route TRADES, beside what it reads.
    #
    # `Contract.ibkr` rather than `_RAITS_TO_IBKR`: that map is BUILT from this attribute, so
    # reading the attribute is reading the same authority one step earlier and cannot disagree
    # with it. It also keeps the broker module out of the identity path, which has no business
    # being imported to answer a question about a contract.
    #
    # For MNKD this deliberately differs from `data_source_identity`: bars come from full-size
    # NKD, orders go to the $0.50 micro MNK. Both are in the hash precisely because they are
    # allowed to differ — a collapse in either direction is the defect, and a defect that moves
    # no hash is one a checkpoint will happily resume across.
    contract = _contract(inst)
    cfg["tradable_symbol"] = contract.ibkr
    cfg["point_value"] = float(contract.point_value)
    cfg["tick"] = float(contract.tick)
    cfg["sizing_basis"] = SIZING_BASIS[sleeve]

    if sleeve == "roska4_swing":
        # Track 1 Normal-R4. Every one of these four differs from legacy, and legacy's
        # checkpoint identity carries none of them.
        cfg.update(ema_period=50, max_hold_days=5,
                   stop_basis="fixed_entry_atr", stop_multiple=2.0,
                   stop_anchor="entry", ratchet=False,
                   arm_hour="14:05", arm_timezone="America/New_York",
                   label_lag_days=0)
    elif sleeve == "global_nkd":
        # Stage 5Q-9 — I-1. This block said `chandelier_atr / 2.5 /
        # extreme_through_prior_bar / ratchet=True / arm 14:00` until 2026-08-24, described as
        # "the promoted sleeve, unchanged; its settings are legacy's on purpose". That sentence
        # was true of LEGACY NKD and false of this sleeve.
        #
        # What Track 1 actually promoted is Normal-R4 at ema 10:
        # `track1_live_source._nkd_candidates` builds `NormalR4Params(ema_period=10)`, whose
        # stop is `entry -+ 2.0 x DAILY ATR` anchored at the entry with the ratchet OFF, armed
        # at `ARM_HOURS` = 14:05 on the frame's own clock. The committed artifact reproduces
        # EXACTLY under that rule — MNKD 228 / 31 / 26 rows across floor, vault2025 and
        # vault2026 — so the code was right and this declaration was the thing that was wrong.
        #
        # It mattered in two places, neither cosmetic. `params_hash` is computed over this
        # dict, so a `global_nkd` checkpoint was accepted or refused against a rule nothing
        # ran; and `run_live_day_track1` reads `stop_basis` straight out of here into the
        # explanation record, so a live MNKD decision was reported to the operator as a
        # chandelier while the stop on the book was an entry-anchored band.
        #
        # `arm_timezone` stays Asia/Tokyo and is not a second copy of anything: the day loop
        # adds `arm_hours` to a day taken from the frame's index, and `frozen_frame` puts that
        # frame on the instrument's declared session zone, which for MNKD is Tokyo.
        #
        # Every `global_nkd` params hash changes. That is the point of the fix, and it is
        # cheap now precisely because no durable live state exists yet.
        cfg.update(ema_period=10, max_hold_days=5,
                   stop_basis="fixed_entry_atr", stop_multiple=2.0,
                   stop_anchor="entry", ratchet=False,
                   arm_hour="14:05", arm_timezone="Asia/Tokyo",
                   label_lag_days=1)
    elif sleeve == "roska4_calm":
        # Same-session: entry 10:00 ET, exit 15:55 ET, one disaster stop at
        # entry - 1.5 x ATR15 that is placed at the fill and never moved.
        cfg.update(ema_period=0, max_hold_days=0,
                   stop_basis="disaster_atr15", stop_multiple=1.5,
                   stop_anchor="entry", ratchet=False,
                   arm_hour="10:00", arm_timezone="America/New_York",
                   label_lag_days=1)
    elif sleeve == "roska4_stress":
        # Same-session: break of the 09:30-10:30 low inside 10:35-12:30, R:R 1.5,
        # minimum gap 3. Stop placed at the fill.
        cfg.update(ema_period=0, max_hold_days=0,
                   stop_basis="pre_low_break_rr", stop_multiple=1.5,
                   stop_anchor="entry", ratchet=False,
                   arm_hour="10:35", arm_timezone="America/New_York",
                   label_lag_days=0)
    else:
        raise ValueError(f"unknown Track 1 sleeve {sleeve!r}")
    return cfg


def sleeve_identity(sleeve: str, inst: str, *, regime_csv: str,
                    data_path: str | Path, fill_law: str) -> tuple[str, str]:
    """`(readable, params_hash)` for one instrument inside one sleeve.

    `fill_law` has no default on purpose. A default here is a default that will be taken, and
    the whole defect this signature exists to remove was a fill law nobody passed.
    """
    return rp.identity(sleeve_config(sleeve, inst, regime_csv=regime_csv,
                                     data_path=data_path, fill_law=fill_law))


def audit_sources() -> dict[str, list[str]]:
    """Which declared fields have a source, and which do not.

    Exists so a test can assert the two sets, rather than a reader having to trust that
    SOURCES was kept in step with ALL_FIELDS by hand.
    """
    declared = set(rp.ALL_FIELDS)
    sourced = set(SOURCES)
    return {
        "missing_source": sorted(declared - sourced),
        "source_for_unknown_field": sorted(sourced - declared),
        "unsourced": sorted(UNSOURCED),
    }
