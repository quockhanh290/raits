# RAITS Phase 1: Step 1.1 - Python Environment Setup

## Overview
This guide walks through setting up the complete Python development environment for Project RAITS Phase 1 (Backtesting & Validation).

**Timeline:** 2-4 hours (depending on experience level)

---

## System Requirements (Pre-Installation Check)

### Hardware Requirements
- **RAM:** 16GB+ (backtesting is memory-intensive)
- **CPU:** Modern multi-core processor (4+ cores recommended)
  - Backtesting is compute-intensive, especially WFO validation
- **Storage:** 50GB+ free disk space
  - Historical data cache: ~20GB
  - Logs and results: ~10GB
  - Python environment & libraries: ~5GB
  - Working headroom: ~15GB

### Operating System
- **Linux:** Ubuntu 22.04 LTS (recommended for cloud deployment)
- **macOS:** 12.0+ (Monterey or later)
- **Windows:** Windows 10/11 with WSL2 (for Linux environment)

**Recommendation:** Use Linux or macOS for best compatibility with Python scientific stack.

---

## Step 1: Python 3.10+ Installation

### Check Current Python Version
```bash
python3 --version
```

**Required:** Python 3.10 or higher

### Installation by OS

#### Ubuntu/Debian Linux
```bash
# Update package list
sudo apt update

# Install Python 3.10 (or 3.11/3.12)
sudo apt install python3.10 python3.10-venv python3.10-dev

# Install pip
sudo apt install python3-pip

# Verify installation
python3.10 --version
pip3 --version
```

#### macOS (using Homebrew)
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.10+
brew install python@3.10

# Verify installation
python3.10 --version
pip3 --version
```

#### Windows (WSL2 recommended)
```bash
# Enable WSL2 (PowerShell as Administrator)
wsl --install

# After WSL2 setup, follow Ubuntu instructions above
```

---

## Step 2: Create Virtual Environment

**Critical:** Always use a virtual environment to isolate project dependencies.

```bash
# Navigate to your project directory
cd ~/projects/RAITS
# or create it if it doesn't exist
mkdir -p ~/projects/RAITS
cd ~/projects/RAITS

# Create virtual environment
python3.10 -m venv venv

# Activate virtual environment
# Linux/macOS:
source venv/bin/activate

# Windows (WSL2):
source venv/bin/activate

# Verify virtual environment is active (should show venv path)
which python
```

**Expected output:** `/home/your_username/projects/RAITS/venv/bin/python`

---

## Step 3: Core Dependencies Installation

### Create requirements.txt

Create a file named `requirements.txt` with the following content:

```text
# Core Data Science & Numerical Computing
numpy>=1.24.0,<2.0.0
pandas>=2.0.0,<3.0.0
scipy>=1.10.0,<2.0.0

# Backtesting Engine
vectorbt>=0.26.0
vectorbtpro>=1.0.0  # Note: Requires license, see below

# Machine Learning - HMM Regime Detection
hmmlearn>=0.3.0,<1.0.0
scikit-learn>=1.3.0,<2.0.0

# Performance Analytics
quantstats>=0.0.62
# Alternative: pyfolio-reloaded>=0.9.5

# Data Acquisition (Polygon.io)
polygon-api-client>=1.12.0
requests>=2.31.0

# Testing Framework
pytest>=7.4.0
pytest-cov>=4.1.0
hypothesis>=6.82.0  # Property-based testing

# Logging & Debugging (Optional but Recommended)
structlog>=23.1.0  # Structured logging

# Development Tools
ipython>=8.14.0  # Enhanced REPL
jupyter>=1.0.0  # Notebooks for exploration
black>=23.7.0  # Code formatting
flake8>=6.1.0  # Linting

# Performance Profiling
line-profiler>=4.0.0
memory-profiler>=0.61.0
```

### Install Dependencies

```bash
# Ensure virtual environment is active
pip install --upgrade pip setuptools wheel

# Install core dependencies
pip install -r requirements.txt
```

**Note on VectorBT Pro:**
- VectorBT Pro requires a paid license (~$500-1000/year for individual)
- **Alternative for testing:** Start with free `vectorbt` package
- Evaluate if Pro features are needed after initial development
- Pro features: Better performance, advanced indicators, enhanced backtesting

---

## Step 4: VectorBT Pro License Setup (If Applicable)

If you have a VectorBT Pro license:

```bash
# Install VectorBT Pro
pip install vectorbtpro

# Activate license (follow prompts)
python -c "import vectorbtpro as vbt; vbt.license.activate('YOUR_LICENSE_KEY')"

# Verify installation
python -c "import vectorbtpro as vbt; print(vbt.__version__)"
```

**Without VectorBT Pro:**
```bash
# Use free version for initial development
pip install vectorbt

# Note: Some advanced features won't be available
# Blueprint can be adapted to use free version with minor modifications
```

---

## Step 5: Install Additional Debugging & Profiling Tools

```bash
# Enhanced debugger
pip install ipdb

# Performance profiling tools
pip install cProfile-pretty
```

---

## Step 6: Verify Installation

Create a verification script to test all critical imports:

```python
# test_environment.py
import sys
print(f"Python version: {sys.version}")

# Test core libraries
try:
    import numpy as np
    print(f"✓ NumPy {np.__version__}")
except ImportError as e:
    print(f"✗ NumPy: {e}")

try:
    import pandas as pd
    print(f"✓ Pandas {pd.__version__}")
except ImportError as e:
    print(f"✗ Pandas: {e}")

try:
    import scipy
    print(f"✓ SciPy {scipy.__version__}")
except ImportError as e:
    print(f"✗ SciPy: {e}")

# Test backtesting engine
try:
    import vectorbt as vbt
    print(f"✓ VectorBT {vbt.__version__}")
except ImportError as e:
    print(f"✗ VectorBT: {e}")

# Test machine learning
try:
    from hmmlearn import hmm
    print(f"✓ hmmlearn (HMM support)")
except ImportError as e:
    print(f"✗ hmmlearn: {e}")

try:
    import sklearn
    print(f"✓ scikit-learn {sklearn.__version__}")
except ImportError as e:
    print(f"✗ scikit-learn: {e}")

# Test analytics
try:
    import quantstats as qs
    print(f"✓ QuantStats {qs.__version__}")
except ImportError as e:
    print(f"✗ QuantStats: {e}")

# Test data API
try:
    from polygon import RESTClient
    print(f"✓ Polygon API Client")
except ImportError as e:
    print(f"✗ Polygon API: {e}")

# Test testing framework
try:
    import pytest
    print(f"✓ pytest {pytest.__version__}")
except ImportError as e:
    print(f"✗ pytest: {e}")

print("\n✅ Environment verification complete!")
```

Run the verification:

```bash
python test_environment.py
```

**Expected output:** All checks should show ✓ (checkmarks)

---

## Step 7: Project Directory Structure Setup

Create the recommended directory structure:

```bash
# Create project directory structure
mkdir -p raits/{data,strategies,risk,hmm,utils,tests,logs,results}
mkdir -p raits/data/{raw,processed,cache}
mkdir -p raits/tests/{unit,integration}

# Create __init__.py files
touch raits/__init__.py
touch raits/strategies/__init__.py
touch raits/risk/__init__.py
touch raits/hmm/__init__.py
touch raits/utils/__init__.py
touch raits/tests/__init__.py
```

**Directory structure:**
```
RAITS/
├── venv/                      # Virtual environment
├── raits/                     # Main package
│   ├── __init__.py
│   ├── data/                  # Data ingestion & caching
│   │   ├── raw/              # Downloaded raw data
│   │   ├── processed/        # Cleaned & preprocessed data
│   │   └── cache/            # API response cache
│   ├── hmm/                  # HMM regime detection
│   ├── strategies/           # Trading strategies
│   │   ├── orb_strategy.py
│   │   ├── mean_reversion.py
│   │   ├── trend_following.py
│   │   └── cash_mode.py
│   ├── risk/                 # Risk management
│   ├── utils/                # Helper functions
│   ├── tests/                # Test suite
│   │   ├── unit/            # Unit tests
│   │   └── integration/     # Integration tests
│   ├── logs/                # Log files
│   └── results/             # Backtest results
├── requirements.txt
└── test_environment.py
```

---

## Step 8: Configure Logging Infrastructure

Create basic logging configuration:

```python
# raits/utils/logger.py
import logging
import sys
from pathlib import Path

def setup_logger(name='RAITS', log_file=None, level=logging.INFO):
    """
    Set up structured logger for RAITS project.
    
    Args:
        name: Logger name
        log_file: Optional log file path
        level: Logging level
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Format
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

# Example usage:
# from raits.utils.logger import setup_logger
# logger = setup_logger('RAITS', log_file='raits/logs/development.log')
# logger.info("Application started")
```

---

## Step 9: Git Version Control Setup (Recommended)

```bash
# Initialize git repository
git init

# Create .gitignore
cat > .gitignore << EOF
# Virtual environment
venv/
env/

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Data files (large files should not be in git)
raits/data/raw/
raits/data/cache/
*.csv
*.parquet
*.h5

# Logs
raits/logs/
*.log

# Results
raits/results/
*.html
*.pdf

# Jupyter Notebooks
.ipynb_checkpoints/
*.ipynb

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# API Keys (CRITICAL - never commit these!)
.env
secrets.py
config_private.py
*.key
EOF

# Initial commit
git add .
git commit -m "Initial RAITS project setup"
```

---

## Step 10: Environment Configuration File

Create a configuration file for API keys and settings:

```python
# raits/config.py (template - DO NOT commit actual keys)
from pathlib import Path
import os

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / 'raits' / 'data'
RAW_DATA_DIR = DATA_DIR / 'raw'
PROCESSED_DATA_DIR = DATA_DIR / 'processed'
CACHE_DIR = DATA_DIR / 'cache'
LOGS_DIR = PROJECT_ROOT / 'raits' / 'logs'
RESULTS_DIR = PROJECT_ROOT / 'raits' / 'results'

# API Keys (use environment variables or separate secrets file)
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', 'YOUR_API_KEY_HERE')

# Backtesting parameters
INITIAL_CAPITAL = 25000  # PDT threshold
COMMISSION_PER_SHARE = 0.005  # $0.005 per share

# Data settings
START_DATE = '2019-01-01'
END_DATE = '2024-12-31'

# Logging
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

**Create a separate secrets file (NOT committed to git):**

```python
# raits/config_private.py (add to .gitignore!)
POLYGON_API_KEY = 'your_actual_api_key_here'
```

Then in `config.py`:
```python
try:
    from raits.config_private import POLYGON_API_KEY
except ImportError:
    POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', 'demo')
```

---

## Step 11: Quick Functionality Test

Create a simple test to verify the environment works:

```python
# quick_test.py
from raits.utils.logger import setup_logger
import numpy as np
import pandas as pd

def main():
    # Setup logger
    logger = setup_logger('RAITS_Test')
    logger.info("Starting quick functionality test...")
    
    # Test NumPy
    arr = np.random.randn(1000)
    logger.info(f"NumPy array mean: {arr.mean():.4f}")
    
    # Test Pandas
    df = pd.DataFrame({
        'date': pd.date_range('2024-01-01', periods=100),
        'price': np.random.randn(100).cumsum() + 100
    })
    logger.info(f"Pandas DataFrame shape: {df.shape}")
    logger.info(f"Price range: {df['price'].min():.2f} to {df['price'].max():.2f}")
    
    logger.info("✅ Quick test passed!")

if __name__ == '__main__':
    main()
```

Run the test:
```bash
python quick_test.py
```

---

## Troubleshooting Common Issues

### Issue 1: "ModuleNotFoundError: No module named 'X'"
**Solution:**
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue 2: "Permission denied" during pip install
**Solution:**
```bash
# Don't use sudo with virtual environment
# Instead, ensure venv is activated first
source venv/bin/activate
pip install -r requirements.txt
```

### Issue 3: NumPy/SciPy compilation errors
**Solution (Ubuntu):**
```bash
# Install build dependencies
sudo apt install build-essential gfortran libopenblas-dev liblapack-dev
pip install --upgrade pip
pip install numpy scipy
```

### Issue 4: VectorBT Pro license activation fails
**Solution:**
```bash
# Verify license key format
# Contact VectorBT support if issue persists
# Or use free VectorBT version temporarily
pip uninstall vectorbtpro
pip install vectorbt
```

---

## Checklist: Environment Setup Complete ✅

Before moving to Step 1.2 (Polygon.io API setup), verify:

- [ ] Python 3.10+ installed and accessible
- [ ] Virtual environment created and activated
- [ ] All core dependencies installed (numpy, pandas, scipy)
- [ ] Backtesting engine installed (vectorbt or vectorbtpro)
- [ ] Machine learning libraries installed (hmmlearn, sklearn)
- [ ] Testing framework installed (pytest)
- [ ] Project directory structure created
- [ ] Logging infrastructure configured
- [ ] Git repository initialized with .gitignore
- [ ] Configuration files created (config.py)
- [ ] Environment verification script passed
- [ ] Quick functionality test passed

**Estimated time:** 2-4 hours

---

## Next Steps

With the environment set up, you're ready for:
- **Step 1.2:** Configure Polygon.io API access
- **Step 1.3:** Build data ingestion pipeline
- **Step 1.4:** Validate data quality

**Critical reminder:** The environment setup is foundational. Don't rush through this step. A solid foundation prevents debugging nightmares later.

---

## Additional Resources

**Python Virtual Environments:**
- https://docs.python.org/3/tutorial/venv.html

**VectorBT Documentation:**
- https://vectorbt.dev/
- https://vectorbt.pro/ (Pro version)

**hmmlearn Documentation:**
- https://hmmlearn.readthedocs.io/

**QuantStats:**
- https://github.com/ranaroussi/quantstats

**Testing with pytest:**
- https://docs.pytest.org/

---

**Document Status:** Production-Ready  
**Last Updated:** February 26, 2026  
**Next:** Step 1.2 - Polygon.io API Configuration
