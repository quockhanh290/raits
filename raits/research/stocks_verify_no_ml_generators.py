from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import pandas as pd


OUT = Path("STOCKS_NO_ML_GENERATOR_REPRO_VERIFY_2026-09-09.csv")
ENGINE_START = pd.Timestamp("2023-03-28")
ENGINE_END = pd.Timestamp("2024-12-31")
DIFF_TOL = 1e-9


def window(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(start), pd.Timestamp(end)


CHECKS = [
    {
        "sleeve": "broad_adv10_g2_dd85",
        "script": "raits/research/stocks_databento_daily_xs_mtm_dd_overlay.py",
        "original": "STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_2026-09-08.csv",
        "regen": "STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_REGEN_2026-09-09.csv",
        "command": ["raits/research/stocks_databento_daily_xs_mtm_dd_overlay.py"],
        "sort_key": ["entry_date", "symbol", "planned_exit_date", "ret5"],
        "date_col": "entry_date",
    },
    {
        "sleeve": "local_xs_full_s10",
        "script": "raits/research/stocks_daily_xs_ret5_bottom_h20_full.py",
        "original": "STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_2026-09-08.csv",
        "regen": "STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_REGEN_2026-09-09.csv",
        "command": ["raits/research/stocks_daily_xs_ret5_bottom_h20_full.py"],
        "sort_key": ["date", "ticker"],
        "date_col": "date",
        "allowed_pre_engine_change_windows": [window("2021-07-15", "2022-02-08")],
    },
    {
        "sleeve": "yday_ex6_actual",
        "script": "raits/research/stocks_wfo_clean_retest.py",
        "original": "STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_2026-09-08.csv",
        "regen": "STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_CAUSEQA_2026-09-10.csv",
        "command": [
            "raits/research/stocks_wfo_clean_retest.py",
            "--position-pct",
            "0.80",
            "--max-positions",
            "1",
            "--output-md",
            "STOCKS_WFO_CLEAN_RETEST_MAX1_80_CAUSEQA_2026-09-10.md",
            "--trades-csv",
            "STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_CAUSEQA_2026-09-10.csv",
        ],
        "sort_key": ["date", "ticker", "wfo_mode"],
        "date_col": "date",
    },
    {
        "sleeve": "intraday_ex10",
        "script": "raits/research/stocks_intraday_focused_rule_miner.py",
        "original": "STOCKS_INTRADAY_FOCUSED_RULES_TRADES_2026-09-08.csv",
        "regen": "STOCKS_INTRADAY_FOCUSED_RULES_TRADES_CAUSEQA_2026-09-10.csv",
        "command": ["raits/research/stocks_intraday_focused_rule_miner.py"],
        "sort_key": ["date", "ticker", "entry", "rule", "side", "slots", "dropSet"],
        "date_col": "date",
        "allowed_pre_engine_change_windows": [window("2022-02-08", "2022-02-08")],
    },
]


def max_diff(orig: pd.DataFrame, regen: pd.DataFrame) -> tuple[int, float]:
    diff_cols = 0
    max_abs = 0.0
    for col in orig.columns:
        left_num = pd.to_numeric(orig[col], errors="coerce")
        right_num = pd.to_numeric(regen[col], errors="coerce")
        left_numeric = (left_num.notna() | orig[col].isna()).all()
        right_numeric = (right_num.notna() | regen[col].isna()).all()
        if left_numeric and right_numeric:
            if not left_num.isna().equals(right_num.isna()):
                diff_cols += 1
                continue
            diff = (left_num - right_num).abs().max()
            diff = 0.0 if pd.isna(diff) else float(diff)
            max_abs = max(max_abs, diff)
            if diff > DIFF_TOL:
                diff_cols += 1
        else:
            neq = int((orig[col].fillna("").astype(str) != regen[col].fillna("").astype(str)).sum())
            if neq:
                diff_cols += 1
                max_abs = max(max_abs, float(neq))
    return diff_cols, max_abs


def changed_rows(orig: pd.DataFrame, regen: pd.DataFrame, key: list[str], date_col: str) -> pd.DataFrame:
    orig_keys = orig[key].drop_duplicates()
    regen_keys = regen[key].drop_duplicates()
    old_only = orig_keys.merge(regen_keys, on=key, how="left", indicator=True).query("_merge == 'left_only'")[key]
    new_only = regen_keys.merge(orig_keys, on=key, how="left", indicator=True).query("_merge == 'left_only'")[key]
    frames = []
    if not old_only.empty:
        frames.append(old_only.assign(changeType="legacy_only"))
    if not new_only.empty:
        frames.append(new_only.assign(changeType="regen_only"))

    shared = orig.merge(regen, on=key, suffixes=("_orig", "_regen"))
    for col in orig.columns:
        if col in key or f"{col}_orig" not in shared.columns:
            continue
        left = shared[f"{col}_orig"]
        right = shared[f"{col}_regen"]
        left_num = pd.to_numeric(left, errors="coerce")
        right_num = pd.to_numeric(right, errors="coerce")
        left_numeric = (left_num.notna() | left.isna()).all()
        right_numeric = (right_num.notna() | right.isna()).all()
        if left_numeric and right_numeric:
            if not left_num.isna().equals(right_num.isna()):
                mask = left_num.isna() != right_num.isna()
            else:
                mask = (left_num - right_num).abs() > DIFF_TOL
        else:
            mask = left.fillna("").astype(str) != right.fillna("").astype(str)
        if mask.any():
            frames.append(shared.loc[mask, key].assign(changeType=f"value:{col}"))

    if not frames:
        return pd.DataFrame(columns=[*key, "changeType"])
    out = pd.concat(frames, ignore_index=True).drop_duplicates()
    out[date_col] = pd.to_datetime(out[date_col])
    return out


def allowed_pre_engine_only(changes: pd.DataFrame, date_col: str, windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> bool:
    if changes.empty or not windows:
        return False
    dates = pd.to_datetime(changes[date_col])
    if (dates >= ENGINE_START).any():
        return False
    allowed = pd.Series(False, index=changes.index)
    for start, end in windows:
        allowed |= (dates >= start) & (dates <= end)
    return bool(allowed.all())


def compare_frames(orig: pd.DataFrame, regen: pd.DataFrame, key: list[str]) -> dict[str, object]:
    row: dict[str, object] = {
        "rowsOrig": len(orig),
        "rowsRegen": len(regen),
        "sameColumns": list(orig.columns) == list(regen.columns),
        "sameKeys": False,
        "sharedRows": None,
        "legacyOnlyRows": None,
        "regenOnlyRows": None,
        "diffColumns": None,
        "maxAbsDiff": None,
    }
    if not row["sameColumns"]:
        return row
    orig_idx = pd.MultiIndex.from_frame(orig[key].drop_duplicates().sort_values(key).reset_index(drop=True))
    regen_idx = pd.MultiIndex.from_frame(regen[key].drop_duplicates().sort_values(key).reset_index(drop=True))
    row["sameKeys"] = orig_idx.equals(regen_idx)
    shared_idx = orig_idx.intersection(regen_idx)
    row["sharedRows"] = len(shared_idx)
    row["legacyOnlyRows"] = len(orig_idx.difference(regen_idx))
    row["regenOnlyRows"] = len(regen_idx.difference(orig_idx))
    if not row["sameKeys"]:
        return row
    orig = orig.sort_values(key).reset_index(drop=True)
    regen = regen.sort_values(key).reset_index(drop=True)
    diff_cols, max_abs = max_diff(orig, regen)
    row["diffColumns"] = diff_cols
    row["maxAbsDiff"] = max_abs
    return row


def check_one(spec: dict[str, object]) -> dict[str, object]:
    script = Path(str(spec["script"]))
    original_path = Path(str(spec["original"]))
    regen_path = Path(str(spec["regen"]))
    row = {
        "sleeve": spec["sleeve"],
        "script": str(script),
        "scriptExists": script.exists(),
        "original": str(original_path),
        "regen": str(regen_path),
        "status": "FAIL",
        "originalRows": 0,
        "regenRows": 0,
        "sameColumns": False,
        "sameKeys": False,
        "diffColumns": None,
        "maxAbsDiff": None,
        "generatorReturnCode": None,
        "generatorSeconds": None,
        "engineWindowRowsOriginal": None,
        "engineWindowRowsRegen": None,
        "engineWindowSameKeys": None,
        "engineWindowDiffColumns": None,
        "engineWindowMaxAbsDiff": None,
        "allowedPreEngineChange": None,
        "changedRows": None,
        "changedStart": None,
        "changedEnd": None,
    }
    if not script.exists() or not original_path.exists():
        return row
    cmd = [sys.executable, *[str(x) for x in spec["command"]]]  # type: ignore[index]
    started = time.perf_counter()
    result = subprocess.run(cmd, check=False)
    row["generatorReturnCode"] = result.returncode
    row["generatorSeconds"] = round(time.perf_counter() - started, 3)
    if result.returncode != 0 or not regen_path.exists():
        return row
    date_col = str(spec.get("date_col", "date"))
    orig = pd.read_csv(original_path, parse_dates=[date_col])
    regen = pd.read_csv(regen_path, parse_dates=[date_col])
    row["originalRows"] = len(orig)
    row["regenRows"] = len(regen)
    key = list(spec["sort_key"])  # type: ignore[arg-type]
    all_cmp = compare_frames(orig, regen, key)
    row["sameColumns"] = all_cmp["sameColumns"]
    row["sameKeys"] = all_cmp["sameKeys"]
    row["diffColumns"] = all_cmp["diffColumns"]
    row["maxAbsDiff"] = all_cmp["maxAbsDiff"]

    orig_engine = orig[(orig[date_col] >= ENGINE_START) & (orig[date_col] <= ENGINE_END)].copy()
    regen_engine = regen[(regen[date_col] >= ENGINE_START) & (regen[date_col] <= ENGINE_END)].copy()
    engine_cmp = compare_frames(orig_engine, regen_engine, key)
    row["engineWindowRowsOriginal"] = engine_cmp["rowsOrig"]
    row["engineWindowRowsRegen"] = engine_cmp["rowsRegen"]
    row["engineWindowSameKeys"] = engine_cmp["sameKeys"]
    row["engineWindowDiffColumns"] = engine_cmp["diffColumns"]
    row["engineWindowMaxAbsDiff"] = engine_cmp["maxAbsDiff"]
    changes = changed_rows(orig, regen, key, date_col)
    row["changedRows"] = len(changes)
    if not changes.empty:
        row["changedStart"] = changes[date_col].min().date()
        row["changedEnd"] = changes[date_col].max().date()
    windows = list(spec.get("allowed_pre_engine_change_windows", []))  # type: ignore[arg-type]
    row["allowedPreEngineChange"] = allowed_pre_engine_only(changes, date_col, windows)

    if row["sameKeys"] and row["diffColumns"] == 0:
        row["status"] = "PASS"
    elif row["engineWindowSameKeys"] and row["engineWindowDiffColumns"] == 0 and row["allowedPreEngineChange"]:
        row["status"] = "CHANGED_PRE_ENGINE_ONLY"
    else:
        row["status"] = "FAIL"
    return row


def main() -> None:
    rows = [check_one(spec) for spec in CHECKS]
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(out.to_string(index=False))
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
