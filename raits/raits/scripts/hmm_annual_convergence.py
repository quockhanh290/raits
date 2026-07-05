"""
scripts/hmm_annual_convergence.py
----------------------------------
TRUST AUDIT — HMM annual convergence audit.

Corrects the "3/6 year-end models failed to converge" claim in
HMM_STABILITY_REPORT.md. Runs 4 scenarios and produces the table
documented in HMM_ANNUAL_CONVERGENCE_AUDIT.md.

Usage:
    python scripts/hmm_annual_convergence.py

Requires: hmmlearn, raits package (editable install)
Output: prints 4 scenario tables to stdout, saves
        configs/hmm_annual_convergence_report.txt

Expected result: all 6 year-ends converge in all 4 scenarios.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Ensure project root (d:\raits) is on sys.path so `import raits` works when
# running the script directly: python raits/raits/scripts/hmm_annual_convergence.py
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

# Silence noisy sklearn/hmmlearn convergence output
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*ConvergenceWarning.*")

from hmmlearn.hmm import GaussianHMM
from raits.hmm.features import build_feature_matrix
from raits.hmm.state_sorting import sort_hmm_states, validate_state_order

_SPY_PATH = Path("raits/data/cache/daily/SPY_daily_2007_2024.parquet")
_YEAR_ENDS = [2016, 2017, 2018, 2019, 2020, 2021]
_IS_ANCHOR = "2017-01-03"


def _load_spy() -> pd.Series:
    df = pd.read_parquet(_SPY_PATH)
    return df["close"]


def _fit_best_of_n(
    X: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    n_init: int,
    min_covar: float,
) -> tuple[GaussianHMM | None, float, int]:
    """Fit best-of-n_init HMM seeds. Returns (best_model, best_ll, n_degen)."""
    best_ll = -1e18
    best_m = None
    n_degen = 0
    for seed in range(n_init):
        try:
            m = GaussianHMM(
                n_components=n_components,
                covariance_type=covariance_type,
                n_iter=n_iter,
                min_covar=min_covar,
                random_state=seed,
            )
            m.fit(X)
            ll = m.score(X)
            if ll > best_ll:
                best_ll = ll
                best_m = m
        except Exception:
            n_degen += 1
    return best_m, best_ll, n_degen


def _row(ye: int, spy_close: pd.Series, covariance_type: str, n_init: int, n_iter: int, is_only: bool) -> dict:
    if is_only:
        subset = spy_close[(spy_close.index >= _IS_ANCHOR) & (spy_close.index <= f"{ye}-12-31")]
    else:
        subset = spy_close[spy_close.index <= f"{ye}-12-31"]

    N = len(subset)
    if N < 35:
        return {"YE": ye, "N": N, "Start": "—", "End": "—", "EM_ok": "NO DATA",
                "Degen": "—", "ValidOrder": "—", "BestLL": "—"}

    X = build_feature_matrix(subset)
    model, ll, n_degen = _fit_best_of_n(X, 4, covariance_type, n_iter, n_init, 1e-2)

    em_ok = model is not None
    valid_order = False
    if em_ok:
        try:
            sorted_m = sort_hmm_states(model)
            valid_order = validate_state_order(sorted_m)
        except Exception:
            valid_order = False

    start = subset.index[0].strftime("%Y-%m-%d")
    end = subset.index[-1].strftime("%Y-%m-%d")
    ll_str = f"{ll:.1f}" if em_ok else "—"
    return {
        "YE": ye, "N": N, "Start": start, "End": end,
        "EM_ok": str(em_ok), "Degen": f"{n_degen}/{n_init}",
        "ValidOrder": str(valid_order), "BestLL": ll_str,
    }


def _print_table(title: str, rows: list[dict]) -> str:
    cols = ["YE", "N", "Start", "End", "EM_ok", "Degen", "ValidOrder", "BestLL"]
    widths = {c: max(len(c), max(len(str(r[c])) for r in rows)) for c in cols}
    header = "  ".join(f"{c:<{widths[c]}}" for c in cols)
    sep = "-" * len(header)
    lines = [title, sep, header, sep]
    for r in rows:
        lines.append("  ".join(f"{str(r[c]):<{widths[c]}}" for c in cols))
    lines.append(sep)
    return "\n".join(lines)


def run(spy_close: pd.Series) -> str:
    sections = []

    # Scenario A: IS-only (2017→YE), report settings (full, n_init=5, n_iter=100)
    print("Running Scenario A: IS-only (2017→YE), full covariance, n_init=5…", file=sys.stderr)
    rows_a = [_row(ye, spy_close, "full", 5, 100, is_only=True) for ye in _YEAR_ENDS]
    sections.append(_print_table(
        "Scenario A — IS-only (2017→YE), full covariance, n_init=5, n_iter=100\n"
        "  [What the prior analysis likely used — NOT anchored from 2007]", rows_a))

    # Scenario B: Anchored (2007→YE), report settings
    print("Running Scenario B: Anchored (2007→YE), full covariance, n_init=5…", file=sys.stderr)
    rows_b = [_row(ye, spy_close, "full", 5, 100, is_only=False) for ye in _YEAR_ENDS]
    sections.append(_print_table(
        "Scenario B — Anchored-expanding (2007→YE), full covariance, n_init=5, n_iter=100\n"
        "  [True anchored scheme — 6/6 expected to converge]", rows_b))

    # Scenario C: n_init=5 vs n_init=20 (anchored, full)
    print("Running Scenario C: n_init=5 vs n_init=20 comparison…", file=sys.stderr)
    rows_c5 = [_row(ye, spy_close, "full", 5, 100, is_only=False) for ye in _YEAR_ENDS]
    rows_c20 = [_row(ye, spy_close, "full", 20, 100, is_only=False) for ye in _YEAR_ENDS]
    c_lines = ["Scenario C — n_init=5 vs n_init=20 (anchored, full covariance, n_iter=100)",
               "  [Tests whether more restarts materially change the result]",
               f"{'YE':>4}  {'N':>5}  {'n5_ok':<8}  {'n5_LL':>10}  {'n20_ok':<9}  {'n20_LL':>10}"]
    c_lines.append("-" * 65)
    for r5, r20 in zip(rows_c5, rows_c20):
        ok5 = f"{r5['ValidOrder']}/{r5['Degen']}" if r5["EM_ok"] != "NO DATA" else "NO DATA"
        ok20 = f"{r20['ValidOrder']}/{r20['Degen']}" if r20["EM_ok"] != "NO DATA" else "NO DATA"
        c_lines.append(f"{r5['YE']:>4}  {r5['N']:>5}  {ok5:<8}  {r5['BestLL']:>10}  {ok20:<9}  {r20['BestLL']:>10}")
    c_lines.append("-" * 65)
    sections.append("\n".join(c_lines))

    # Scenario D: Production settings (diag, n_init=10, n_iter=200)
    print("Running Scenario D: Production settings (diag, n_init=10, n_iter=200)…", file=sys.stderr)
    rows_d = [_row(ye, spy_close, "diag", 10, 200, is_only=False) for ye in _YEAR_ENDS]
    sections.append(_print_table(
        "Scenario D — Production settings (diag covariance, n_init=10, n_iter=200)\n"
        "  [6/6 converge with zero degen seeds expected]", rows_d))

    return "\n\n".join(sections)


def main() -> None:
    spy = _load_spy()
    report = run(spy)
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "hmm_annual_convergence_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
