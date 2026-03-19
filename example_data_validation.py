"""
RAITS Data Quality Validation - Example Usage

Demonstrates how to validate data quality before backtesting.
Critical for avoiding survivorship bias and ensuring reliable results.
"""

from datetime import datetime, timedelta
from raits.data.raits_data_pipeline import DataPipeline, quick_universe
from raits.data.raits_data_validator import (
    DataQualityValidator,
    validate_data,
    validate_universe
)


def example_1_basic_validation():
    """Example 1: Basic data quality check."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Basic Data Quality Check")
    print("="*60)
    
    # Fetch data
    pipeline = DataPipeline(api_key=None)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    print(f"\nFetching AAPL data...")
    data = pipeline.get_daily_data("AAPL", start_date, end_date)
    
    # Validate using quick function
    print("Running validation...")
    report = validate_data(data, max_missing_pct=5.0)
    
    # Print results
    print("\n" + report.summary())
    
    return report


def example_2_custom_validation():
    """Example 2: Custom validation with specific thresholds."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Custom Validation Thresholds")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    
    # Fetch data
    data = pipeline.get_daily_data(
        "TSLA",
        datetime(2024, 1, 1),
        datetime(2024, 12, 31)
    )
    
    # Create validator with custom settings
    validator = DataQualityValidator(
        max_missing_pct=3.0,  # Stricter: only 3% missing allowed
        extreme_move_threshold=0.15,  # 15% instead of 20%
        min_volume_threshold=100000,  # Higher minimum volume
        zero_volume_critical=False  # Don't fail on zero volume
    )
    
    print(f"\nValidating {data.ticker} with strict settings...")
    report = validator.validate(data)
    
    # Show specific checks
    print(f"\nQuality Score: {report.quality_score}/100")
    print(f"Status: {'✓ PASS' if report.passed else '✗ FAIL'}")
    
    print(f"\nDetailed Checks:")
    print(f"  Missing data: {report.missing_percentage:.1f}%")
    print(f"  Gaps: {len(report.gap_dates)}")
    print(f"  Extreme moves: {len(report.extreme_moves)}")
    print(f"  Zero volume days: {len(report.zero_volume_days)}")
    print(f"  OHLC violations: {len(report.ohlc_violations)}")
    
    # Show issues by severity
    critical = report.get_critical_issues()
    warnings = report.get_warnings()
    
    if critical:
        print(f"\n⚠️  Critical Issues ({len(critical)}):")
        for issue in critical:
            print(f"  - {issue}")
    
    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for issue in warnings[:5]:  # Show first 5
            print(f"  - {issue}")
    
    return report


def example_3_selective_checks():
    """Example 3: Run only specific validation checks."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Selective Validation Checks")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    data = pipeline.get_daily_data("MSFT", datetime.now() - timedelta(days=180), datetime.now())
    
    validator = DataQualityValidator()
    
    # Only check price anomalies and volume (skip survivorship)
    print(f"\nRunning selective checks on {data.ticker}...")
    report = validator.validate(
        data,
        check_survivorship=False,  # Skip this
        check_corporate_actions=True,
        check_price_anomalies=True,
        check_volume=True
    )
    
    print(f"\nPrice Anomalies:")
    print(f"  Extreme moves (>20%): {len(report.extreme_moves)}")
    if report.extreme_moves:
        print(f"  Largest moves:")
        for date, pct in sorted(report.extreme_moves, key=lambda x: abs(x[1]), reverse=True)[:3]:
            print(f"    {date}: {pct:+.1f}%")
    
    print(f"\nVolume Analysis:")
    print(f"  Zero volume days: {len(report.zero_volume_days)}")
    print(f"  Low volume days: {len(report.low_volume_days)}")
    print(f"  Volume spikes: {len(report.volume_spikes)}")
    
    return report


def example_4_universe_validation():
    """Example 4: Validate entire trading universe."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Universe Validation")
    print("="*60)
    
    # Build small universe
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
    
    print(f"\nBuilding universe: {tickers}")
    universe = quick_universe(tickers, days=180)
    
    # Validate all tickers
    print(f"\nValidating {len(universe)} tickers...")
    reports = validate_universe(universe, show_progress=True)
    
    # Summary
    print(f"\n" + "="*60)
    print("Universe Validation Summary")
    print("="*60)
    
    passed = [t for t, r in reports.items() if r.passed]
    failed = [t for t, r in reports.items() if not r.passed]
    
    print(f"\nOverall Results:")
    print(f"  ✓ Passed: {len(passed)}/{len(reports)}")
    print(f"  ✗ Failed: {len(failed)}/{len(reports)}")
    
    print(f"\nQuality Scores:")
    for ticker in sorted(reports.keys()):
        report = reports[ticker]
        status = "✓" if report.passed else "✗"
        print(f"  {status} {ticker}: {report.quality_score:.1f}/100")
    
    if failed:
        print(f"\nFailed Tickers:")
        for ticker in failed:
            report = reports[ticker]
            critical = len(report.get_critical_issues())
            print(f"  {ticker}: {critical} critical issues")
    
    # Detailed report for worst ticker
    if reports:
        worst = min(reports.items(), key=lambda x: x[1].quality_score)
        print(f"\nWorst Quality Ticker: {worst[0]}")
        print(worst[1].summary())
    
    return reports


def example_5_corporate_actions():
    """Example 5: Check corporate actions (splits/dividends)."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Corporate Actions Validation")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    
    # Fetch data
    data = pipeline.get_daily_data("AAPL", datetime(2024, 1, 1), datetime(2024, 12, 31))
    
    # Validate
    validator = DataQualityValidator()
    report = validator.validate(data, check_corporate_actions=True)
    
    print(f"\nCorporate Actions for {data.ticker}:")
    print(f"  Splits: {len(report.splits)}")
    print(f"  Dividends: {len(report.dividends)}")
    
    if report.splits:
        print(f"\n  Split Details:")
        for split in report.splits:
            print(f"    {split.ex_date}: {split.split_ratio:.1f}-for-1 split")
    
    if report.dividends:
        print(f"\n  Dividend Details:")
        for dividend in report.dividends[:5]:  # Show first 5
            print(f"    {dividend.ex_date}: ${dividend.dividend_amount:.2f} per share")
    
    # Check if data is properly adjusted
    corporate_issues = [i for i in report.issues if i.category == 'corporate_actions']
    if corporate_issues:
        print(f"\n⚠️  Corporate Action Issues:")
        for issue in corporate_issues:
            print(f"  - {issue}")
    else:
        print(f"\n✓ Corporate actions properly handled")
    
    return report


def example_6_survivorship_bias():
    """Example 6: Check for survivorship bias."""
    print("\n" + "="*60)
    print("EXAMPLE 6: Survivorship Bias Detection")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    data = pipeline.get_daily_data("TEST", datetime(2020, 1, 1), datetime(2024, 12, 31))
    
    validator = DataQualityValidator()
    report = validator.validate(data, check_survivorship=True)
    
    print(f"\nSurvivorship Analysis for {data.ticker}:")
    print(f"  Currently active: {report.is_currently_active}")
    print(f"  Delisted date: {report.delisted_date if report.delisted_date else 'N/A'}")
    print(f"  Survivorship bias risk: {'Yes' if report.has_survivorship_bias_risk else 'No'}")
    
    # Check for survivorship issues
    survivorship_issues = [i for i in report.issues if i.category == 'survivorship_bias']
    
    if survivorship_issues:
        print(f"\n⚠️  Survivorship Issues Found:")
        for issue in survivorship_issues:
            print(f"  - {issue}")
    else:
        print(f"\n✓ No survivorship bias detected")
    
    return report


def example_7_pass_fail_decisions():
    """Example 7: Using validation for pass/fail decisions."""
    print("\n" + "="*60)
    print("EXAMPLE 7: Pass/Fail Decision Making")
    print("="*60)
    
    # Build universe
    tickers = ["AAPL", "MSFT", "GOOGL"]
    universe = quick_universe(tickers, days=252)
    
    # Validate
    reports = validate_universe(universe, show_progress=False)
    
    # Filter based on quality
    print(f"\nFiltering universe based on data quality...")
    
    acceptable_tickers = []
    rejected_tickers = []
    
    for ticker, report in reports.items():
        if report.passed and report.quality_score >= 80:
            acceptable_tickers.append(ticker)
        else:
            rejected_tickers.append(ticker)
    
    print(f"\nResults:")
    print(f"  ✓ Acceptable for trading: {acceptable_tickers}")
    print(f"  ✗ Rejected (quality issues): {rejected_tickers}")
    
    print(f"\nQuality Criteria:")
    print(f"  - Must pass validation (no critical issues)")
    print(f"  - Quality score >= 80/100")
    print(f"  - Missing data <= 5%")
    
    # Show why rejected
    if rejected_tickers:
        print(f"\nRejection Reasons:")
        for ticker in rejected_tickers:
            report = reports[ticker]
            critical = len(report.get_critical_issues())
            print(f"  {ticker}:")
            print(f"    Score: {report.quality_score:.1f}/100")
            print(f"    Critical issues: {critical}")
            if critical > 0:
                for issue in report.get_critical_issues()[:2]:
                    print(f"      - {issue.description}")
    
    return acceptable_tickers


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print(" " * 15 + "RAITS DATA QUALITY VALIDATION")
    print("="*70)
    print("\nComprehensive data validation examples")
    print("Ensures clean, reliable data before backtesting")
    
    try:
        # Run examples
        report1 = example_1_basic_validation()
        report2 = example_2_custom_validation()
        report3 = example_3_selective_checks()
        reports4 = example_4_universe_validation()
        report5 = example_5_corporate_actions()
        report6 = example_6_survivorship_bias()
        acceptable = example_7_pass_fail_decisions()
        
        # Summary
        print("\n" + "="*70)
        print("✅ All validation examples completed!")
        print("="*70)
        
        print("\nWhat you learned:")
        print("  1. Basic data quality validation")
        print("  2. Custom validation thresholds")
        print("  3. Selective checks (pick what to validate)")
        print("  4. Universe-wide validation")
        print("  5. Corporate actions detection")
        print("  6. Survivorship bias checking")
        print("  7. Pass/fail decision making")
        
        print("\nKey Takeaways:")
        print("  ✓ Always validate data before backtesting")
        print("  ✓ Check for survivorship bias (critical!)")
        print("  ✓ Verify corporate actions are handled")
        print("  ✓ Filter out low-quality tickers")
        print("  ✓ Use quality scores to rank data reliability")
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
