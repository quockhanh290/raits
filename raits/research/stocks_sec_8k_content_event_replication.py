from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_sec_8k_content_event_map as discovery


FREEZE = Path("STOCKS_SEC_8K_CONTENT_EVENT_REPLICATION_FROZEN_2026-10-03.json")
LABELS = discovery.CACHE / "labels_replication.csv"
CLASSIFICATION_MANIFEST = discovery.CACHE / "classification_manifest_replication.json"
PREFIX = "STOCKS_SEC_8K_CONTENT_EVENT_REPLICATION_2026-10-03"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    freeze = json.loads(FREEZE.read_text(encoding="ascii"))
    if freeze["scriptHash"] != sha256(Path(__file__)):
        raise RuntimeError("replication freeze hash mismatch")
    classification = json.loads(CLASSIFICATION_MANIFEST.read_text(encoding="ascii"))
    if classification["unresolvedAccessions"] != 0 or classification["labelsHash"] != sha256(LABELS):
        raise RuntimeError("replication content coverage mismatch")
    selected = pd.read_csv(f"{discovery.PREFIX}_DISCOVERY.csv")
    selected = selected[selected["developmentPass"].astype(bool)].copy()
    frozen_cells = freeze["selectedCells"]
    observed_cells = selected[["eventClass", "horizon", "direction"]].to_dict("records")
    if observed_cells != frozen_cells or len(observed_cells) != 1:
        raise RuntimeError("selected cell mismatch")

    labels = pd.read_csv(LABELS, dtype={"cik": str, "accession_number": str})
    panel, sessions = discovery.build_panel()
    assigned = discovery.assign_sessions(labels, sessions)
    event_class = str(frozen_cells[0]["eventClass"])
    horizon = str(frozen_cells[0]["horizon"])
    direction = int(frozen_cells[0]["direction"])
    events = assigned[assigned[event_class].astype(bool)].copy()
    events = events.sort_values(["entry_date", "cik", "accession_number"])
    events = events.drop_duplicates(["entry_date", "cik"], keep="first")
    events = events.merge(panel, on=["entry_date", "ticker"], how="inner", validate="many_to_one")
    events = events[events["entry_date"].dt.year.eq(2021)].copy()
    values = events[f"resid_{horizon}"].replace([np.inf, -np.inf], np.nan).dropna()
    std = float(values.std())
    t_value = float(values.mean() / std * math.sqrt(len(values))) if len(values) > 1 and std > 0 else np.nan
    discovery_mean = float(selected.iloc[0]["meanResidual"])
    row = {
        "eventClass": event_class, "horizon": horizon, "direction": direction,
        "events": int(len(values)), "meanResidual": float(values.mean()), "t": t_value,
        "directionalT": direction * t_value, "discoveryMeanResidual": discovery_mean,
        "minimumReplicationMagnitude": abs(discovery_mean) * 0.25,
    }
    row["replicationPass"] = bool(
        row["events"] >= 20 and direction * row["meanResidual"] > 0
        and row["directionalT"] >= 1.0 and abs(row["meanResidual"]) >= row["minimumReplicationMagnitude"]
    )
    pd.DataFrame([row]).to_csv(f"{PREFIX}_RESULT.csv", index=False)
    events[["entry_date", "ticker", "cik", "accession_number", f"resid_{horizon}",
            f"exit_fallback_{horizon}", f"exit_writeoff_{horizon}"]].to_csv(f"{PREFIX}_EVENTS.csv", index=False)
    selection = {"replicationPasses": int(row["replicationPass"]), "productionPassAllowed": False,
                 "post2021PerformanceConsumed": False}
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "freeze": str(FREEZE), "freezeHash": sha256(FREEZE), "labelsHash": sha256(LABELS),
        "classificationManifestHash": sha256(CLASSIFICATION_MANIFEST), "selection": selection,
        "oldManual62Used": False, "post2021PerformanceConsumed": False,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(json.dumps(row, indent=2)); print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
