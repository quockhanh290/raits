import json
from pathlib import Path
B = lambda **kw: kw
blockers = [
 B(id="L1", title="Track 1 Normal-R4 has no production slot, and legacy's swing is a DIFFERENT strategy",
   evidence=("legacy run_live_day: ema 30, chandelier 2.5, ratchet ON (NKD_EMA/SWING_TF_PARAM); "
             "Track1 NormalR4Params: ema 50, entry-anchored 2.0x ATR, ratchet OFF, arm 14:05. "
             "run_live_day_track1 documents the resulting checkpoint params_mismatch as correct."),
   impact=("the 23 live_day slots (14:05-15:55) produce LEGACY Rổ-4, not Track 1's Normal-R4. "
           "Track 1's largest sleeve has no live path at all"),
   fix="promote Normal-R4 into Track 1 slots covering 14:05-15:55, as Calm/Stress were",
   blocks={"shadow": "partially - Normal cannot be shadowed", "paper": True, "live": True,
           "legacy_retirement": True}),
 B(id="L2", title="STOP_TRADING freezes two of Track 1's four sleeves",
   evidence=("Normal-R4's window is served by legacy live_day slots and NKD's by legacy "
             "nkd_night slots; both run run_live_day, whose D5 gate clears entry_candidates "
             "when STOP_TRADING is present"),
   impact=("the Stage 5J/5K operator flow - STOP_TRADING then --track1-shadow - measures Calm "
           "and Stress ONLY. It is not the combined route, and coverage collected under it "
           "cannot support a combined-book claim"),
   fix=("either promote Normal/NKD to Track 1 slots first, or state explicitly that the first "
        "shadow period is a Calm+Stress-only measurement"),
   blocks={"shadow": "changes what shadow MEANS", "paper": True, "live": True,
           "legacy_retirement": True}),
 B(id="L3", title="Safety jobs are hard-wired to the legacy positions file",
   evidence=("captured argv: run_maxhold_exit --positions-path live_positions.json; "
             "run_stop_repair --positions-path live_positions.json"),
   impact=("a Track 1 position in live_positions.track1.json would get NO stop repair and NO "
           "max-hold exit. The two mechanisms that protect a multi-day position do not see it"),
   fix="route-aware stop repair and max-hold, or a second pair of route-scoped jobs",
   blocks={"shadow": False, "paper": True, "live": True, "legacy_retirement": True}),
 B(id="L4", title="One IB login is one position book (B1, unchanged)",
   evidence="IBKRBroker.get_positions() reads ib.positions() unfiltered; B3 reconciles per contract",
   impact="legacy LONG 1 beside Track 1 SHORT 1 nets to zero and halts entries on BOTH routes",
   fix="retire legacy first, or a separate account",
   blocks={"shadow": False, "paper": True, "live": True, "legacy_retirement": "is the fix"}),
 B(id="L5", title="Track 1 caps/family guard are not applied to the legacy-run sleeves",
   evidence=("track1_params CAPS/FAMILY_GROSS 0.05/FAMILY_NET 0.044 are enforced by "
             "track1_signal_layer, which only the Track 1 slots reach; legacy uses its own "
             "MultiClusterGuard in run_live_day"),
   impact=("while Normal/NKD are legacy-run, the combined book is capped by legacy's guard, not "
           "Track 1's - the two are not the same object and have not been reconciled"),
   fix="whichever route owns a sleeve must own its cap; reconcile the two guards before mixing",
   blocks={"shadow": "partially", "paper": True, "live": True, "legacy_retirement": True}),
 B(id="L6", title="Pre-flight is a legacy job that Track 1 depends on",
   evidence=("the single `preflight` job at 13:45 ET runs update_ibkr_daily + update_spy_csv and "
             "writes preflight_state.json; track1_freshness encodes the D-1 13:45 contract"),
   impact=("retiring legacy jobs wholesale would remove the data refresh Track 1's freshness "
           "gate is defined against, and every Track 1 slot would refuse"),
   fix="promote pre-flight to a SHARED production job owned by neither route",
   blocks={"shadow": False, "paper": False, "live": True, "legacy_retirement": True}),
 B(id="L7", title="Morning Track 1 slots trade on D-1 data by contract",
   evidence=("required_data_through(): before 13:45 ET the answer is the previous business day; "
             "Calm fires 10:00 and Stress 10:35-12:30, all before 13:45"),
   impact=("this is the DESIGNED contract, not a defect - but it means Calm/Stress decide on "
           "yesterday's parquet plus today's live bars through the provider. If anyone expects "
           "a pre-market refresh, it does not exist"),
   fix="none required; state it, or add a pre-market refresh as a deliberate change",
   blocks={"shadow": False, "paper": False, "live": False, "legacy_retirement": False}),
 B(id="L8", title="The running scheduler predates all Track 1 work",
   evidence="pid 36656, started 2026-08-20 06:35:53, pythonw, --port 4002 --shadow-resume",
   impact="any Track 1 change is inert until it is restarted; it also runs pre-Track-1 legacy code",
   fix="restart --scheduler --track1-shadow when the operator is ready",
   blocks={"shadow": True, "paper": True, "live": True, "legacy_retirement": False}),
]
Path("scratch/_audit_blockers.json").write_text(json.dumps(blockers, indent=1, ensure_ascii=False),
                                                encoding="utf-8")
print("blockers:", len(blockers))
