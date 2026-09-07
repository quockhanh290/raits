"""Generate scratch/track1_explainability_schema_20260823.json FROM the registry.

Derived, never hand-written: a schema document written beside the code is a description
that will drift from it. The examples are built through the real builders and validated
before they are embedded, so an example that stopped being valid cannot ship.
"""
import json, sys
sys.path.insert(0, r"d:\raits")
sys.path.insert(0, r"d:\raits\scratch")
from global_index import track1_explain as tx
import test_track1_explain_20260823 as T

FIELD_DOC = {
 "schema_version": "Which contract this row obeys. A reader that does not know the version must not guess.",
 "explain_id": "sha256 over route|session_date|sleeve|instrument|candidate_id|record_type|stage|sequence. Stable across processes.",
 "parent_explain_id": "The record this one descends from - a DECISION names its SIGNAL, an EXECUTION names its DECISION. null when there is none.",
 "route": "track1_candidate. Present on every row so a reader can split Track 1 from legacy without inferring it.",
 "sleeve": "roska4_swing | global_nkd | roska4_calm | roska4_stress.",
 "instrument": "Must be one the sleeve is declared to trade.",
 "session_date": "The trading session the record belongs to, YYYY-MM-DD ET.",
 "candidate_id": "The trade/candidate this row is about. Non-trade rows use a stable label such as 'window'.",
 "record_type": "SIGNAL | DECISION | EXECUTION | NO_SIGNAL | NO_ACTION.",
 "stage": "Free label separating two records of the same tuple, e.g. 'detection' vs 'admission'. Part of the id.",
 "sequence": "Integer separating repeated evaluations inside a window. Part of the id.",
 "decision_time": "The instant the verdict was taken, ET.",
 "data_time": "The instant the data used was current as of.",
 "bar_timestamps": "The bar timestamps the rules actually read.",
 "status": "pass | fail | accepted | rejected | info, constrained per record_type.",
 "reason_code": "One code from the registry. Refusal codes are imported from the modules that own them.",
 "rule_ids": "Which registered rules fired. An id not in the registry is refused.",
 "code_refs": "Derived from rule_ids: file + symbol + rule_id, line optional. Never supplied by the caller.",
 "evidence_refs": "Derived from rule_ids: the test/report/artifact that proves each rule.",
 "feature_snapshot": "The measured values. Every entry carries value AND threshold AND whether it passed. value=null means the feature was ABSENT, which for the R4 context filter is a block.",
 "thresholds": "The explicit threshold values in force for this record, beyond the per-feature ones.",
 "inputs_summary": "Which bars / regime / checkpoint / freshness / window-ledger source fed the decision.",
 "outputs": "direction, qty, entry basis, stop basis, risk, cap bucket.",
 "rejection": "Refusal detail. Required when status=rejected.",
 "track1_params_hash": "route_params.params_hash of the config the run used. What a checkpoint is accepted or refused on.",
 "fill_law": "artifact_all_bars_gappable | production_gap_after_15min_break. No default.",
 "data_source_identity": "path:sha256 of the bar file used.",
 "regime_csv_identity": "path:sha256 of the regime CSV used.",
 "git_commit": "HEAD when the record was built, or null meaning 'could not read it' - never a guess.",
}

reg = tx.registry()
examples = {
    "DECISION_accepted": T._accepted_decision(),
    "DECISION_rejected": T._rejected_decision(),
    "SIGNAL_filter_blocked": T._signal(),
    "NO_SIGNAL_window_watched": tx.no_signal_record(
        route=tx.ROUTE, session_date="2026-08-24", sleeve="roska4_stress",
        instrument="MNQ", candidate_id="window", decision_time="2026-08-24 12:30:00",
        rule_ids=["GATE.WINDOW_LEDGER"],
        features=[tx.Feature("observed_slots", 24, 24, "==", True)],
        inputs_summary={"window": "10:35-12:30 ET", "expected_slots": 24},
        outputs={}, identity=T.IDENT),
}
for name, rec in examples.items():
    errs = tx.validate(rec)
    assert not errs, (name, errs)          # an invalid example must not ship

missing_fields = sorted(set(reg["required_fields"]) - set(FIELD_DOC))
assert not missing_fields, missing_fields  # every required field must be documented

doc = {
    "_generated_by": "global_index/track1_explain.registry() — do not hand-edit; "
                     "regenerate with scratch/gen (see the design note). A schema written "
                     "beside the code is a description that will drift from it.",
    "_generated_on_session": "2026-08-23",
    **reg,
    "field_documentation": FIELD_DOC,
    "examples": examples,
    "counts": {
        "rules": len(reg["rules"]),
        "reason_codes": len(reg["reason_codes"]),
        "required_fields": len(reg["required_fields"]),
        "rules_by_scope": {s: sum(1 for r in reg["rules"].values() if r["scope"] == s)
                           for s in sorted({r["scope"] for r in reg["rules"].values()})},
    },
}
out = r"d:\raits\scratch\track1_explainability_schema_20260823.json"
with open(out, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, sort_keys=False, ensure_ascii=True)
print("wrote", out)
print("rules:", doc["counts"]["rules"], "by scope:", doc["counts"]["rules_by_scope"])
print("reason codes:", doc["counts"]["reason_codes"], "required fields:", doc["counts"]["required_fields"])
