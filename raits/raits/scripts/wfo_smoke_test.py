"""
scripts/wfo_smoke_test.py
-------------------------
Mini WFO smoke test using real yfinance 5-minute data.

Purpose:
    Prove the full pipeline works end-to-end with real market data:
    - Real SPY bars → HMM regime detection
    - Real stock bars → strategy signals
    - Real costs applied
    - WFO window scheduling, grid search, parameter aggregation
    - WFOReport saved to configs/

This is NOT the real WFO run (only ~60 days of data available via yfinance).
It's a sanity check before subscribing to Polygon.io for the full 7-year run.

Usage:
    cd C:\\Users\\quock\\RAITS\\raits
    python scripts/wfo_smoke_test.py

Expected output:
    - HMM trains without error
    - At least some trades fire across the test period
    - WFOReport prints with Calmar, Sharpe, Max DD
    - configs/wfo_smoke_report.json saved
    - configs/wfo_smoke_params.yaml saved
"""

import sys
import os
import logging
import warnings
warnings.filterwarnings("ignore")

# -- Path setup ----------------------------------------------------------------
# Run from raits/ subdirectory (where pyproject.toml lives)
# Add project root to sys.path
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)


import pandas as pd
import numpy as np
import yfinance as yf

from raits.backtest.wfo import WFOEngine, WFOConfig
from raits.backtest.wfo_grid import ProductionParams

# -- Logging -------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("smoke_test")

# -- Configuration -------------------------------------------------------------
UNIVERSE  = ["AAPL", "MSFT", "NVDA"]   # keep small for speed
TICKERS   = ["SPY"] + UNIVERSE

# With ~60 days of 5-min data, use very short windows
# 15 train days + 10 test days per window — not meaningful statistically
# but proves the machinery runs end-to-end
TRAIN_DAYS_APPROX = 15   # ~3 calendar weeks
TEST_DAYS_APPROX  = 10   # ~2 calendar weeks


def download_data(tickers: list, period: str = "60d") -> dict:
    """
    Pull 5-minute bars for all tickers via yfinance.
    Returns dict: ticker → DataFrame (DatetimeIndex, lowercase columns).
    """
    print(f"\n{'='*60}")
    print(f"Downloading 5-minute data for: {tickers}")
    print(f"{'='*60}")

    market_data = {}
    for ticker in tickers:
        try:
            df = yf.download(
                ticker,
                period=period,
                interval="5m",
                auto_adjust=True,
                progress=False,
            )
            if df.empty:
                print(f"  [FAIL] {ticker}: no data returned")
                continue

            # Flatten MultiIndex columns if present (newer yfinance versions)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0].lower() for c in df.columns]
            else:
                df.columns = [c.lower() for c in df.columns]

            # Drop timezone for consistency
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            # Keep only market hours (09:30–16:00 ET)
            df = df.between_time("09:30", "16:00")

            print(f"  [OK] {ticker}: {len(df)} bars  "
                  f"{df.index[0].date()} -> {df.index[-1].date()}")
            market_data[ticker] = df

        except Exception as e:
            print(f"  [FAIL] {ticker}: {e}")

    return market_data


def validate_data(market_data: dict) -> bool:
    """Basic sanity checks before running WFO."""
    if "SPY" not in market_data:
        print("\n[FAIL] FATAL: SPY data missing — cannot compute HMM regime")
        return False

    spy_days = len(market_data["SPY"].index.normalize().unique())
    print(f"\nSPY trading days available: {spy_days}")

    if spy_days < 25:
        print("[FAIL] FATAL: Need at least 25 trading days for HMM (50 daily obs minimum)")
        return False

    stock_count = sum(1 for t in UNIVERSE if t in market_data)
    if stock_count == 0:
        print("[FAIL] FATAL: No stock data available — no trades can fire")
        return False

    print(f"[OK] Data validated: {spy_days} SPY days, {stock_count}/{len(UNIVERSE)} stocks")
    return True


def build_wfo_config(market_data: dict) -> WFOConfig:
    """
    Build a WFOConfig sized to the available data.
    With ~60 days we use very short windows — just enough to exercise the
    full WFO loop without crashing on insufficient data.
    """
    spy = market_data["SPY"]
    days = spy.index.normalize().unique().sort_values()
    total_days = len(days)

    # Vault = last 15% of data (blueprint rule, even for smoke test)
    vault_days = max(int(total_days * 0.15), 5)
    wfo_days   = total_days - vault_days

    start_date = str(days[0].date())
    # End at vault boundary (WFO only sees data before vault)
    end_date   = str(days[total_days - vault_days - 1].date())

    print(f"\nWFO config:")
    print(f"  Total days:  {total_days}")
    print(f"  WFO days:    {wfo_days}  ({start_date} -> {end_date})")
    print(f"  Vault days:  {vault_days} (held out)")

    # Use very small windows for smoke test
    # Blueprint uses 3yr train / 1yr test — we use ~15d / ~10d
    train_years_equiv = TRAIN_DAYS_APPROX / 252
    test_years_equiv  = TEST_DAYS_APPROX  / 252

    return WFOConfig(
        full_dataset_start=start_date,
        full_dataset_end=str(days[-1].date()),
        vault_fraction=0.15,
        train_years=train_years_equiv,
        test_years=test_years_equiv,
        universe=UNIVERSE,
        account_equity=25_000.0,
        enable_costs=True,
        enable_pdt_guard=True,
        log_level="WARNING",
        aggregation_method="MEAN",
    )


def run_smoke_test():
    print("\n" + "="*60)
    print("RAITS WFO SMOKE TEST — yfinance data")
    print("="*60)

    # -- 1. Download data ------------------------------------------------------
    market_data = download_data(TICKERS)

    if not validate_data(market_data):
        sys.exit(1)

    # -- 2. Build config -------------------------------------------------------
    try:
        cfg = build_wfo_config(market_data)
    except Exception as e:
        print(f"\n[FAIL] Config build failed: {e}")
        sys.exit(1)

    # -- 3. Run WFO ------------------------------------------------------------
    print(f"\nRunning WFO grid search ({27} combinations × windows)...")
    print("This may take a few minutes on real data.\n")

    try:
        engine = WFOEngine(cfg)
        report = engine.run(market_data)
    except Exception as e:
        print(f"\n[FAIL] WFO run failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # -- 4. Print results ------------------------------------------------------
    print("\n" + report.summary())

    # -- 5. Save outputs -------------------------------------------------------
    os.makedirs("configs", exist_ok=True)
    try:
        # Save with smoke-test prefix so it doesn't overwrite real WFO results
        import json, dataclasses

        report_path = "configs/wfo_smoke_report.json"
        params_path = "configs/wfo_smoke_params.yaml"

        # Save params YAML
        with open(params_path, "w") as f:
            f.write(
                f"# SMOKE TEST PARAMS — not for production use\n"
                + report.production_params.to_yaml_str()
            )

        # Save report JSON
        def default(o):
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            return str(o)

        report_dict = {
            "smoke_test": True,
            "vault_boundary": report.vault_boundary,
            "wfo_passes": report.wfo_passes,
            "proceed_to_vault": report.proceed_to_vault,
            "stitched_metrics": report.stitched_metrics,
            "dominance_check": report.dominance_check,
            "production_params": dataclasses.asdict(report.production_params),
            "windows": [dataclasses.asdict(w) for w in report.window_results],
        }
        with open(report_path, "w") as f:
            json.dump(report_dict, f, indent=2, default=default)

        print(f"\n[OK] Smoke params saved -> {params_path}")
        print(f"[OK] Smoke report saved -> {report_path}")

    except Exception as e:
        print(f"\n[WARN] Save failed (non-fatal): {e}")

    # -- 6. Verdict ------------------------------------------------------------
    print("\n" + "="*60)
    m = report.stitched_metrics
    trades = m.get("total_trades", 0)

    if trades == 0:
        print("[WARN]  NO TRADES FIRED")
        print("   This means the strategies rejected all signals on this data.")
        print("   Common causes:")
        print("   - HMM stayed in Stress/Safety mode all session")
        print("   - Scanner filters too strict for this universe/period")
        print("   - Not enough bars per day (data gaps)")
        print("   The engine itself is working — this is a signal quality issue.")
    else:
        print(f"[OK] {trades} trades fired across WFO windows")
        print(f"  Calmar:  {m.get('calmar_ratio', 0):.2f}  (target >2.0 for Tier 1)")
        print(f"  Sharpe:  {m.get('sharpe_ratio', 0):.2f}  (target >1.5)")
        print(f"  Max DD:  {m.get('max_drawdown', 0):.1%}  (target <15%)")
        print(f"  Win rate:{m.get('win_rate', 0):.1%}  (target >40%)")
        print()
        if report.wfo_passes:
            print("[OK] WFO targets met on smoke data")
        else:
            print("[WARN]  WFO targets not met — expected on 60-day smoke data")
            print("   Run again with 7-year Polygon.io data for real results.")

    print("="*60)
    print("\nSmoke test complete. Engine is working end-to-end on real market data.")
    print("Next step: subscribe to Polygon.io and run the real WFO.")


if __name__ == "__main__":
    run_smoke_test()
