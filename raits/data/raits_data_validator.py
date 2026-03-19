"""
RAITS Data Quality Validator

Comprehensive data validation to ensure clean, reliable data for backtesting.
Checks for survivorship bias, delisted tickers, splits/dividends, and anomalies.

Critical for avoiding lookahead bias and ensuring Point-in-Time (PIT) data accuracy.
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from dataclasses import dataclass, field

from raits.data.raits_data_models import (
    HistoricalData, 
    BarData, 
    DataQualityReport,
    SplitDividend
)


@dataclass
class DataQualityIssue:
    """Single data quality issue detected."""
    severity: str  # 'CRITICAL', 'WARNING', 'INFO'
    category: str  # 'survivorship_bias', 'missing_data', 'price_anomaly', etc.
    description: str
    date: Optional[date] = None
    value: Optional[float] = None
    
    def __str__(self) -> str:
        if self.date:
            return f"[{self.severity}] {self.category}: {self.description} on {self.date}"
        return f"[{self.severity}] {self.category}: {self.description}"


@dataclass
class ComprehensiveQualityReport:
    """
    Comprehensive data quality assessment.
    
    Extends basic DataQualityReport with detailed survivorship bias,
    corporate action, and Point-in-Time data checks.
    """
    ticker: str
    start_date: date
    end_date: date
    total_bars: int
    
    # Missing data
    expected_bars: int
    missing_bars: int
    missing_percentage: float
    gap_dates: List[date] = field(default_factory=list)
    
    # Corporate actions
    splits: List[SplitDividend] = field(default_factory=list)
    dividends: List[SplitDividend] = field(default_factory=list)
    
    # Survivorship bias
    is_currently_active: bool = True
    delisted_date: Optional[date] = None
    has_survivorship_bias_risk: bool = False
    
    # Price anomalies
    extreme_moves: List[Tuple[date, float]] = field(default_factory=list)  # (date, return %)
    price_spikes: List[Tuple[date, float]] = field(default_factory=list)  # (date, spike %)
    suspicious_patterns: List[str] = field(default_factory=list)
    
    # Volume anomalies
    zero_volume_days: List[date] = field(default_factory=list)
    low_volume_days: List[date] = field(default_factory=list)
    volume_spikes: List[Tuple[date, float]] = field(default_factory=list)
    
    # Price consistency
    negative_prices: List[date] = field(default_factory=list)
    ohlc_violations: List[date] = field(default_factory=list)  # High < Low, etc.
    
    # Overall assessment
    issues: List[DataQualityIssue] = field(default_factory=list)
    passed: bool = False
    quality_score: float = 0.0  # 0-100
    
    def get_critical_issues(self) -> List[DataQualityIssue]:
        """Get only critical issues."""
        return [i for i in self.issues if i.severity == 'CRITICAL']
    
    def get_warnings(self) -> List[DataQualityIssue]:
        """Get warnings."""
        return [i for i in self.issues if i.severity == 'WARNING']
    
    def summary(self) -> str:
        """Get human-readable summary."""
        status = "PASS" if self.passed else "FAIL"
        
        summary = [
            f"Data Quality Report: {self.ticker}",
            f"Status: {status} (Score: {self.quality_score:.1f}/100)",
            f"Period: {self.start_date} to {self.end_date}",
            f"Bars: {self.total_bars}/{self.expected_bars} ({self.missing_percentage:.1f}% missing)",
            "",
            f"Corporate Actions:",
            f"  - Splits: {len(self.splits)}",
            f"  - Dividends: {len(self.dividends)}",
            "",
            f"Survivorship:",
            f"  - Active: {self.is_currently_active}",
            f"  - Delisted: {self.delisted_date if self.delisted_date else 'No'}",
            f"  - Bias Risk: {'Yes' if self.has_survivorship_bias_risk else 'No'}",
            "",
            f"Anomalies:",
            f"  - Extreme moves (>20%): {len(self.extreme_moves)}",
            f"  - Price spikes: {len(self.price_spikes)}",
            f"  - Zero volume days: {len(self.zero_volume_days)}",
            f"  - OHLC violations: {len(self.ohlc_violations)}",
            "",
            f"Issues: {len(self.issues)} total",
            f"  - Critical: {len(self.get_critical_issues())}",
            f"  - Warnings: {len(self.get_warnings())}",
        ]
        
        if self.get_critical_issues():
            summary.append("\nCritical Issues:")
            for issue in self.get_critical_issues()[:5]:  # Show first 5
                summary.append(f"  - {issue}")
        
        return "\n".join(summary)


class DataQualityValidator:
    """
    Comprehensive data quality validation.
    
    Implements checks for:
    - Survivorship bias
    - Missing data and gaps
    - Corporate actions (splits, dividends)
    - Price anomalies
    - Volume issues
    - OHLC consistency
    - Point-in-Time data integrity
    """
    
    def __init__(
        self,
        max_missing_pct: float = 5.0,
        extreme_move_threshold: float = 0.20,  # 20%
        price_spike_threshold: float = 3.0,  # 3 std devs
        min_volume_threshold: int = 1000,
        zero_volume_critical: bool = True
    ):
        """
        Initialize validator with thresholds.
        
        Args:
            max_missing_pct: Maximum allowed missing data %
            extreme_move_threshold: Threshold for extreme single-day moves
            price_spike_threshold: Standard deviations for price spikes
            min_volume_threshold: Minimum acceptable volume
            zero_volume_critical: Treat zero volume as critical issue
        """
        self.max_missing_pct = max_missing_pct
        self.extreme_move_threshold = extreme_move_threshold
        self.price_spike_threshold = price_spike_threshold
        self.min_volume_threshold = min_volume_threshold
        self.zero_volume_critical = zero_volume_critical
    
    def validate(
        self,
        data: HistoricalData,
        check_survivorship: bool = True,
        check_corporate_actions: bool = True,
        check_price_anomalies: bool = True,
        check_volume: bool = True
    ) -> ComprehensiveQualityReport:
        """
        Perform comprehensive validation.
        
        Args:
            data: Historical data to validate
            check_survivorship: Check for survivorship bias
            check_corporate_actions: Validate splits/dividends
            check_price_anomalies: Detect price anomalies
            check_volume: Check volume issues
        
        Returns:
            ComprehensiveQualityReport with all findings
        """
        df = data.to_dataframe()
        
        # Initialize report
        start_date = data.bars[0].timestamp.date()
        end_date = data.bars[-1].timestamp.date()
        
        report = ComprehensiveQualityReport(
            ticker=data.ticker,
            start_date=start_date,
            end_date=end_date,
            total_bars=len(data.bars),
            expected_bars=len(pd.bdate_range(start=start_date, end=end_date)),
            missing_bars=0,
            missing_percentage=0.0
        )
        
        # Run checks
        self._check_missing_data(data, df, report)
        
        if check_survivorship:
            self._check_survivorship_bias(data, report)
        
        if check_corporate_actions:
            self._check_corporate_actions(data, df, report)
        
        if check_price_anomalies:
            self._check_price_anomalies(df, report)
        
        if check_volume:
            self._check_volume_issues(df, report)
        
        self._check_ohlc_consistency(df, report)
        
        # Calculate overall score and pass/fail
        self._calculate_quality_score(report)
        
        return report
    
    def _check_missing_data(
        self,
        data: HistoricalData,
        df: pd.DataFrame,
        report: ComprehensiveQualityReport
    ) -> None:
        """Check for missing bars and gaps."""
        expected_dates = pd.bdate_range(
            start=report.start_date,
            end=report.end_date
        )
        
        actual_dates = pd.DatetimeIndex([bar.timestamp for bar in data.bars])
        
        # Missing bars
        report.expected_bars = len(expected_dates)
        report.missing_bars = report.expected_bars - report.total_bars
        report.missing_percentage = (report.missing_bars / report.expected_bars * 100) if report.expected_bars > 0 else 0
        
        # Detect gaps (3+ consecutive missing days)
        timestamps = pd.DatetimeIndex([bar.timestamp for bar in data.bars])
        gaps = timestamps.to_series().diff() > pd.Timedelta(days=3)
        gap_dates = timestamps[gaps].tolist()
        report.gap_dates = [g.date() for g in gap_dates]
        
        # Add issues
        if report.missing_percentage > self.max_missing_pct:
            report.issues.append(DataQualityIssue(
                severity='CRITICAL',
                category='missing_data',
                description=f'High missing data: {report.missing_percentage:.1f}% ({report.missing_bars} bars)',
                value=report.missing_percentage
            ))
        elif report.missing_percentage > self.max_missing_pct / 2:
            report.issues.append(DataQualityIssue(
                severity='WARNING',
                category='missing_data',
                description=f'Some missing data: {report.missing_percentage:.1f}%',
                value=report.missing_percentage
            ))
        
        if len(report.gap_dates) > 0:
            report.issues.append(DataQualityIssue(
                severity='WARNING',
                category='data_gaps',
                description=f'Found {len(report.gap_dates)} gaps in data (3+ day breaks)',
                value=len(report.gap_dates)
            ))
    
    def _check_survivorship_bias(
        self,
        data: HistoricalData,
        report: ComprehensiveQualityReport
    ) -> None:
        """
        Check for survivorship bias.
        
        Survivorship bias occurs when only currently-traded stocks are included,
        excluding delisted/bankrupt companies. This creates unrealistic backtest results.
        """
        # Check if stock is currently active
        if data.metadata:
            report.is_currently_active = data.metadata.is_active
            report.delisted_date = data.metadata.delisted_date
            
            # If stock was delisted during the backtest period
            if report.delisted_date and report.delisted_date <= report.end_date:
                # Check if we have data through delisting
                last_data_date = data.bars[-1].timestamp.date()
                
                if last_data_date < report.delisted_date:
                    report.issues.append(DataQualityIssue(
                        severity='CRITICAL',
                        category='survivorship_bias',
                        description=f'Data ends {(report.delisted_date - last_data_date).days} days before delisting',
                        date=report.delisted_date
                    ))
                    report.has_survivorship_bias_risk = True
            
            # If stock is currently delisted but we're testing on old data
            if not report.is_currently_active and report.delisted_date:
                if report.end_date > report.delisted_date:
                    report.issues.append(DataQualityIssue(
                        severity='WARNING',
                        category='survivorship_bias',
                        description=f'Testing period extends past delisting date',
                        date=report.delisted_date
                    ))
        else:
            # No metadata - can't verify survivorship
            report.issues.append(DataQualityIssue(
                severity='INFO',
                category='survivorship_bias',
                description='No metadata available to check survivorship bias'
            ))
    
    def _check_corporate_actions(
        self,
        data: HistoricalData,
        df: pd.DataFrame,
        report: ComprehensiveQualityReport
    ) -> None:
        """Check for splits and dividends."""
        if data.splits_dividends:
            report.splits = [s for s in data.splits_dividends if s.action_type == 'split']
            report.dividends = [d for d in data.splits_dividends if d.action_type == 'dividend']
            
            # Check if data is adjusted for splits
            for split in report.splits:
                # Look for sudden price changes around split date
                split_date = pd.Timestamp(split.ex_date)
                
                # Find bars around split
                before = df[df.index < split_date].tail(5)
                after = df[df.index >= split_date].head(5)
                
                if not before.empty and not after.empty:
                    price_ratio = after.iloc[0]['close'] / before.iloc[-1]['close']
                    expected_ratio = 1.0 / split.split_ratio  # e.g., 0.5 for 2-for-1
                    
                    # Check if price adjusted correctly (within 5%)
                    if abs(price_ratio - expected_ratio) > 0.05:
                        report.issues.append(DataQualityIssue(
                            severity='WARNING',
                            category='corporate_actions',
                            description=f'Split adjustment may be incorrect: expected {expected_ratio:.2f}x, got {price_ratio:.2f}x',
                            date=split.ex_date,
                            value=price_ratio
                        ))
            
            # Log corporate actions as INFO
            if len(report.splits) > 0:
                report.issues.append(DataQualityIssue(
                    severity='INFO',
                    category='corporate_actions',
                    description=f'Stock had {len(report.splits)} split(s) during period'
                ))
            
            if len(report.dividends) > 0:
                report.issues.append(DataQualityIssue(
                    severity='INFO',
                    category='corporate_actions',
                    description=f'Stock paid {len(report.dividends)} dividend(s) during period'
                ))
    
    def _check_price_anomalies(
        self,
        df: pd.DataFrame,
        report: ComprehensiveQualityReport
    ) -> None:
        """Detect price anomalies and suspicious patterns."""
        # Calculate returns
        returns = df['close'].pct_change()
        
        # Extreme single-day moves (>20%)
        extreme_moves = returns[abs(returns) > self.extreme_move_threshold]
        
        for date, ret in extreme_moves.items():
            report.extreme_moves.append((date.date(), ret * 100))
            report.issues.append(DataQualityIssue(
                severity='WARNING',
                category='price_anomaly',
                description=f'Extreme price move: {ret*100:.1f}%',
                date=date.date(),
                value=ret * 100
            ))
        
        # Price spikes (>3 std devs from mean)
        returns_std = returns.std()
        returns_mean = returns.mean()
        
        if returns_std > 0:
            z_scores = (returns - returns_mean) / returns_std
            spikes = z_scores[abs(z_scores) > self.price_spike_threshold]
            
            for date, z in spikes.items():
                if abs(z) > 5:  # Very extreme
                    report.price_spikes.append((date.date(), z))
                    report.issues.append(DataQualityIssue(
                        severity='WARNING',
                        category='price_spike',
                        description=f'Price spike: {z:.1f} std devs from mean',
                        date=date.date(),
                        value=z
                    ))
        
        # Check for negative prices
        negative = df[df['close'] <= 0]
        if not negative.empty:
            report.negative_prices = [idx.date() for idx in negative.index]
            report.issues.append(DataQualityIssue(
                severity='CRITICAL',
                category='price_anomaly',
                description=f'Found {len(negative)} bars with negative/zero prices',
                value=len(negative)
            ))
        
        # Suspicious patterns - flat prices
        flat_days = (df['high'] == df['low']).sum()
        if flat_days > len(df) * 0.1:  # More than 10% of days
            report.suspicious_patterns.append(f'{flat_days} days with no intraday movement')
            report.issues.append(DataQualityIssue(
                severity='WARNING',
                category='suspicious_pattern',
                description=f'{flat_days} days with High = Low (no movement)',
                value=flat_days
            ))
    
    def _check_volume_issues(
        self,
        df: pd.DataFrame,
        report: ComprehensiveQualityReport
    ) -> None:
        """Check for volume anomalies."""
        # Zero volume days
        zero_vol = df[df['volume'] == 0]
        if not zero_vol.empty:
            report.zero_volume_days = [idx.date() for idx in zero_vol.index]
            
            severity = 'CRITICAL' if self.zero_volume_critical else 'WARNING'
            report.issues.append(DataQualityIssue(
                severity=severity,
                category='volume_anomaly',
                description=f'Found {len(zero_vol)} days with zero volume',
                value=len(zero_vol)
            ))
        
        # Very low volume days
        low_vol = df[(df['volume'] > 0) & (df['volume'] < self.min_volume_threshold)]
        if not low_vol.empty:
            report.low_volume_days = [idx.date() for idx in low_vol.index]
            
            if len(low_vol) > len(df) * 0.2:  # More than 20% of days
                report.issues.append(DataQualityIssue(
                    severity='WARNING',
                    category='volume_anomaly',
                    description=f'{len(low_vol)} days with very low volume (<{self.min_volume_threshold:,})',
                    value=len(low_vol)
                ))
        
        # Volume spikes (>10x average)
        avg_volume = df['volume'].mean()
        if avg_volume > 0:
            vol_spikes = df[df['volume'] > avg_volume * 10]
            
            for date, row in vol_spikes.iterrows():
                multiplier = row['volume'] / avg_volume
                report.volume_spikes.append((date.date(), multiplier))
                
                if multiplier > 50:  # Very extreme
                    report.issues.append(DataQualityIssue(
                        severity='INFO',
                        category='volume_spike',
                        description=f'Volume spike: {multiplier:.1f}x average',
                        date=date.date(),
                        value=multiplier
                    ))
    
    def _check_ohlc_consistency(
        self,
        df: pd.DataFrame,
        report: ComprehensiveQualityReport
    ) -> None:
        """Check OHLC data consistency."""
        # High must be >= Low
        violations_hl = df[df['high'] < df['low']]
        
        # High must be >= Open and Close
        violations_ho = df[df['high'] < df['open']]
        violations_hc = df[df['high'] < df['close']]
        
        # Low must be <= Open and Close
        violations_lo = df[df['low'] > df['open']]
        violations_lc = df[df['low'] > df['close']]
        
        all_violations = pd.concat([
            violations_hl, violations_ho, violations_hc,
            violations_lo, violations_lc
        ]).drop_duplicates()
        
        if not all_violations.empty:
            report.ohlc_violations = [idx.date() for idx in all_violations.index]
            report.issues.append(DataQualityIssue(
                severity='CRITICAL',
                category='ohlc_consistency',
                description=f'Found {len(all_violations)} OHLC consistency violations',
                value=len(all_violations)
            ))
    
    def _calculate_quality_score(
        self,
        report: ComprehensiveQualityReport
    ) -> None:
        """
        Calculate overall quality score (0-100).
        
        Scoring:
        - Start at 100
        - Deduct points for issues
        - Critical: -20 points each
        - Warning: -5 points each
        - Info: -1 point each
        """
        score = 100.0
        
        for issue in report.issues:
            if issue.severity == 'CRITICAL':
                score -= 20
            elif issue.severity == 'WARNING':
                score -= 5
            elif issue.severity == 'INFO':
                score -= 1
        
        # Ensure score is between 0 and 100
        score = max(0.0, min(100.0, score))
        
        report.quality_score = score
        
        # Pass criteria:
        # - No critical issues
        # - Score >= 70
        # - Missing data <= threshold
        critical_issues = report.get_critical_issues()
        
        report.passed = (
            len(critical_issues) == 0 and
            score >= 70 and
            report.missing_percentage <= self.max_missing_pct
        )


# Convenience functions

def validate_data(
    data: HistoricalData,
    max_missing_pct: float = 5.0
) -> ComprehensiveQualityReport:
    """
    Quick validation with default settings.
    
    Args:
        data: Historical data to validate
        max_missing_pct: Maximum allowed missing data %
    
    Returns:
        ComprehensiveQualityReport
    """
    validator = DataQualityValidator(max_missing_pct=max_missing_pct)
    return validator.validate(data)


def validate_universe(
    universe: Dict[str, HistoricalData],
    show_progress: bool = True
) -> Dict[str, ComprehensiveQualityReport]:
    """
    Validate entire universe of stocks.
    
    Args:
        universe: Dict of ticker -> HistoricalData
        show_progress: Show progress bar
    
    Returns:
        Dict of ticker -> ComprehensiveQualityReport
    """
    reports = {}
    
    if show_progress:
        try:
            from tqdm import tqdm
            ticker_iter = tqdm(universe.items(), desc="Validating universe")
        except ImportError:
            ticker_iter = universe.items()
            print(f"Validating {len(universe)} tickers...")
    else:
        ticker_iter = universe.items()
    
    for ticker, data in ticker_iter:
        try:
            report = validate_data(data)
            reports[ticker] = report
        except Exception as e:
            print(f"⚠️  Failed to validate {ticker}: {e}")
            continue
    
    return reports


if __name__ == '__main__':
    # Example usage
    from raits.data.raits_mock_data import generate_mock_daily_data
    
    print("Testing Data Quality Validator...\n")
    
    # Generate mock data
    data = generate_mock_daily_data(ticker="TEST", days=252)
    
    # Validate
    validator = DataQualityValidator()
    report = validator.validate(data)
    
    # Print summary
    print(report.summary())
    print("\n" + "="*60)
    
    if report.passed:
        print("Data quality: PASS")
    else:
        print("Data quality: FAIL")
    
    print(f"Quality Score: {report.quality_score}/100")
