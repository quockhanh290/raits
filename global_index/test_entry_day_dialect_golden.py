from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

from global_index.runner import _openpos_from_dict


HERE = Path(__file__).parent
GOLDEN = HERE / "test_entry_day_dialect_golden.json"
BASE = HERE / "test_runner_book_dialect_golden.json"


def _values(row):
    return json.loads(json.dumps(dataclasses.asdict(_openpos_from_dict(row)), default=str))


def _digest(values):
    raw = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def test_prechange_golden_equivalence_allows_only_a_date_bearing_entry_time():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    base = json.loads(BASE.read_text(encoding="utf-8"))["records"]
    records = [
        (base[item["base_index"]]["input"], item)
        for item in golden["base_records"]
    ] + [(item["input"], item) for item in golden["live_records"]]

    assert len(records) == golden["row_count"] == 14
    assert golden["raised_count"] == 0
    changed = []
    for row, expected in records:
        values = _values(row)
        before_entry_day = expected["entry_day"]
        if values["entry_day"] != before_entry_day:
            entry_time = str(row.get("entry_time") or "")
            assert re.match(r"^\d{4}-\d{2}-\d{2}", entry_time), row
            assert values["entry_day"][:10] == entry_time[:10]
            changed.append((expected.get("path"), expected.get("index")))
        normalized = dict(values, entry_day=before_entry_day)
        assert _digest(normalized) == expected["output_sha256"]

    assert len(changed) <= 6
