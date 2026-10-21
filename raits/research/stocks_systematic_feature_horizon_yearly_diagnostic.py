from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

import stocks_systematic_feature_horizon_map as edge_map


PREFIX = "STOCKS_SYSTEMATIC_FEATURE_HORIZON_2026-10-03"
SOURCE = Path(f"{PREFIX}_DISCOVERY_REPLICATION.csv")
OUTPUT = Path(f"{PREFIX}_YEARLY_DIAGNOSTIC.csv")
MANIFEST = Path(f"{PREFIX}_YEARLY_DIAGNOSTIC_MANIFEST.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    source = pd.read_csv(SOURCE)[
        ["context", "feature", "horizon", "binary", "discoveryPass", "replicationPass"]
    ]
    datasets, _ = edge_map.prepare(edge_map.REP_END)
    frames = []
    for year in range(2018, 2022):
        start = max(edge_map.medium.START, pd.Timestamp(year=year, month=1, day=1))
        end = pd.Timestamp(year=year, month=12, day=31)
        yearly = edge_map.build_tests(datasets, start, end)
        yearly.insert(0, "year", year)
        frames.append(yearly)
    result = pd.concat(frames, ignore_index=True).merge(
        source,
        on=["context", "feature", "horizon", "binary"],
        how="left",
        validate="many_to_one",
    )
    if len(result) != 4 * 180:
        raise RuntimeError("yearly diagnostic cell count mismatch")
    result.to_csv(OUTPUT, index=False)
    payload = {
        "status": "DIAGNOSTIC_ONLY_NOT_A_SELECTION_INPUT",
        "years": [2018, 2019, 2020, 2021],
        "cellsPerYear": 180,
        "rows": len(result),
        "post2021PerformanceConsumed": False,
        "sourceResultHash": sha256(SOURCE),
        "edgeMapScriptHash": sha256(Path(edge_map.__file__)),
        "scriptHash": sha256(Path(__file__)),
        "outputHash": sha256(OUTPUT),
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    selected = result[result["discoveryPass"].astype(bool)]
    print(selected[["year", "context", "feature", "horizon", "spread", "t", "dates"]].to_string(index=False))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
