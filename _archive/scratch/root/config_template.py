"""
RAITS Configuration Template

This file contains the main configuration settings for the RAITS project.
Copy this to config_private.py and fill in your actual values.

DO NOT commit config_private.py to version control!
"""

from pathlib import Path
import os

# ============================================
# Project Paths
# ============================================
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'raits' / 'data'
RAW_DATA_DIR = DATA_DIR / 'raw'
PROCESSED_DATA_DIR = DATA_DIR / 'processed'
CACHE_DIR = DATA_DIR / 'cache'
LOGS_DIR = PROJECT_ROOT / 'raits' / 'logs'
RESULTS_DIR = PROJECT_ROOT / 'raits' / 'results'

# Create directories if they don't exist
for directory in [RAW_DATA_DIR, PROCESSED_DATA_DIR, CACHE_DIR, LOGS_DIR, RESULTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# ============================================
# API Configuration
# ============================================

# Polygon.io API Key
# Get your API key from: https://polygon.io/
# Paid tier required for historical data and delisted tickers
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', 'YOUR_API_KEY_HERE')

# API Rate Limiting
POLYGON_RATE_LIMIT_CALLS = 100  # Calls per minute (adjust based on your plan)
POLYGON_RATE_LIMIT_PERIOD = 60  # Seconds

# ============================================
# Backtesting Parameters
# ============================================

# Initial capital (PDT threshold)
INITIAL_CAPITAL = 25000  # $25,000 minimum for Pattern Day Trader

# Commission structure
COMMISSION_PER_SHARE = 0.005  # $0.005 per share (typical for discount brokers)
COMMISSION_MIN = 0.00  # Minimum commission (most brokers now $0)
COMMISSION_MAX = None  # Maximum commission cap (if applicable)

# Slippage parameters (conservative defaults)
SLIPPAGE_FIXED_BPS = 5  # 5 basis points fixed slippage
SLIPPAGE_VARIABLE_PCT = 0.10  # 0.10% of trade value

# Market impact (for position sizing)
MARKET_IMPACT_COEFFICIENT = 0.0001  # 0.01% per $1000 of order

# ============================================
# Data Settings
# ============================================

# Historical data range
START_DATE = '2019-01-01'  # Start date for historical data
END_DATE = '2024-12-31'    # End date for historical data

# Trading universe
UNIVERSE_SIZE = 100  # Number of stocks to screen (based on liquidity)
MIN_PRICE = 5.00  # Minimum stock price ($)
MAX_PRICE = 500.00  # Maximum stock price ($)
MIN_VOLUME = 500000  # Minimum average daily volume (shares)

# Data quality filters
MAX_MISSING_DATA_PCT = 0.05  # Max 5% missing data allowed
REQUIRE_FULL_HISTORY = True  # Require stocks to have full history in date range

# ============================================
# Strategy Parameters
# ============================================

# Opening Range Breakout (ORB)
ORB_ENABLED = True
ORB_RANGE_MINUTES = 15  # 15-minute opening range (9:30-9:45 ET)
ORB_MIN_RANGE_ATR = 0.30  # Minimum range (30% of ATR)
ORB_MAX_RANGE_ATR = 3.00  # Maximum range (3× ATR)
ORB_MIN_RELATIVE_VOLUME = 1.5  # Minimum 1.5× average volume
ORB_TARGET_RISK_REWARD = 3.0  # Target R:R ratio

# VWAP Mean Reversion
VWAP_MR_ENABLED = True
VWAP_MR_ENTRY_THRESHOLD = 1.5  # 1.5 standard deviations from VWAP
VWAP_MR_EXIT_THRESHOLD = 0.5  # Exit at 0.5 std dev from VWAP
VWAP_MR_MAX_HOLDING_MINUTES = 240  # Maximum 4-hour holding period

# Trend Following
TREND_ENABLED = True
TREND_EMA_SHORT = 9  # Short-term EMA period
TREND_EMA_LONG = 21  # Long-term EMA period
TREND_MIN_ADX = 25  # Minimum ADX for trend strength
TREND_ATR_STOP_MULTIPLE = 2.0  # Stop loss at 2× ATR

# ============================================
# Risk Management
# ============================================

# Position sizing
KELLY_FRACTION = 0.50  # Half-Kelly for safety
MAX_POSITION_SIZE_PCT = 0.20  # Max 20% of capital per position
VOLATILITY_TARGET_PCT = 0.01  # 1% volatility target per trade

# Portfolio limits
MAX_SIMULTANEOUS_POSITIONS = 5  # Max open positions at once
MAX_SECTOR_EXPOSURE_PCT = 0.40  # Max 40% in any sector
MAX_CORRELATION_THRESHOLD = 0.70  # Max correlation between positions

# Daily risk controls
MAX_DAILY_LOSS_PCT = 0.02  # 2% max daily loss (circuit breaker)
MAX_DAILY_TRADES = 10  # Maximum trades per day

# ============================================
# HMM Regime Detection
# ============================================

# HMM model parameters
HMM_N_STATES = 3  # Number of market regimes (Normal, Stress, Volatile)
HMM_LOOKBACK_DAYS = 252  # 1 year of data for training
HMM_RETRAIN_FREQUENCY = 'weekly'  # Retrain frequency

# Features for regime detection
HMM_FEATURES = [
    'returns',
    'volatility',
    'volume',
    'vix_level',
]

# Confidence thresholds
HMM_MIN_CONFIDENCE = 0.60  # Minimum confidence to act on regime signal
HMM_OVERRIDE_THRESHOLD = 3.0  # Standard deviations for override triggers

# ============================================
# Validation Settings
# ============================================

# Walk-Forward Optimization
WFO_TRAIN_PERIOD_MONTHS = 12  # 12-month training window
WFO_TEST_PERIOD_MONTHS = 3  # 3-month test window
WFO_STEP_MONTHS = 3  # Step forward 3 months each iteration
WFO_MIN_TRADES_PER_WINDOW = 50  # Minimum trades to validate window

# Vault test (final validation)
VAULT_TEST_ENABLED = True
VAULT_HOLDOUT_START = '2024-01-01'  # Locked hold-out period
VAULT_HOLDOUT_END = '2024-12-31'
VAULT_COOLING_OFF_DAYS = 7  # 1 week cooling-off before Vault test

# ============================================
# Logging Configuration
# ============================================

# Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL = 'INFO'
LOG_TO_FILE = True
LOG_TO_CONSOLE = True
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_FILE_BACKUP_COUNT = 5  # Keep 5 backup log files

# Structured logging format
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# ============================================
# Performance Optimization
# ============================================

# Caching
ENABLE_DATA_CACHE = True
CACHE_EXPIRY_HOURS = 24  # Cache data for 24 hours

# Parallel processing
NUM_WORKERS = 4  # Number of parallel workers (adjust based on CPU cores)
ENABLE_NUMBA_JIT = True  # Enable Numba JIT compilation for HMM

# ============================================
# Development/Testing Flags
# ============================================

# Debug mode (enables verbose logging and checks)
DEBUG_MODE = False

# Fast mode (reduced data for quick testing)
FAST_MODE = False  # Set to True for quick iteration during development
FAST_MODE_N_DAYS = 30  # Use only 30 days of data in fast mode

# ============================================
# Load Private Configuration
# ============================================

# Try to load private configuration (not in version control)
try:
    from raits.config_private import *
    print("✓ Private configuration loaded")
except ImportError:
    print("⚠️  Warning: config_private.py not found. Using default configuration.")
    print("   Create config_private.py with your API keys and custom settings.")
