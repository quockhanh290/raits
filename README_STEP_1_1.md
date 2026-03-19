# RAITS Phase 1 - Step 1.1: Python Environment Setup

## 📦 Deliverables

This package contains everything you need to set up your Python development environment for Project RAITS Phase 1.

### Files Included

1. **step_1_1_environment_setup.md** - Complete setup guide
   - System requirements
   - Python installation
   - Virtual environment setup
   - Dependency installation
   - Troubleshooting guide

2. **requirements.txt** - Python dependencies
   - Core data science libraries (NumPy, Pandas, SciPy)
   - Backtesting engine (VectorBT)
   - Machine learning (hmmlearn, scikit-learn)
   - Testing framework (pytest)
   - Development tools

3. **quick_start.sh** - Automated setup script
   - Creates virtual environment
   - Installs all dependencies
   - Verifies installation
   - One-command setup

4. **setup_project_structure.py** - Directory structure creator
   - Creates complete project layout
   - Initializes Python packages
   - Sets up data/logs/results directories

5. **verify_environment.py** - Environment verification
   - Checks all dependencies
   - Tests basic functionality
   - Provides diagnostic output

6. **config_template.py** - Configuration template
   - Project paths
   - API configuration
   - Backtesting parameters
   - Risk management settings

7. **.gitignore** - Git ignore rules
   - Prevents committing sensitive data
   - Excludes large data files
   - Protects API keys

## 🚀 Quick Start (2 Options)

### Option 1: Automated Setup (Recommended)

```bash
# 1. Download all files to your project directory
cd ~/projects/RAITS

# 2. Run the quick start script
chmod +x quick_start.sh
./quick_start.sh

# Done! Environment is ready.
```

### Option 2: Manual Setup

```bash
# 1. Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# 3. Create project structure
python setup_project_structure.py

# 4. Verify installation
python verify_environment.py

# 5. Initialize git
git init
cp .gitignore .  # Use provided .gitignore
git add .gitignore
git commit -m "Initial commit"
```

## 📋 Checklist

After setup, verify these items:

- [ ] Python 3.10+ installed
- [ ] Virtual environment created and activated
- [ ] All dependencies installed (verify_environment.py passes)
- [ ] Project directory structure created
- [ ] Git repository initialized
- [ ] .gitignore in place
- [ ] Configuration template reviewed

## 🔧 Configuration

1. Copy `config_template.py` to `raits/config_private.py`:
   ```bash
   cp config_template.py raits/config_private.py
   ```

2. Edit `raits/config_private.py` and add your settings:
   - Polygon.io API key (Step 1.2)
   - Custom backtesting parameters
   - Risk management preferences

3. **IMPORTANT:** Never commit `config_private.py` to version control!
   - It contains sensitive API keys
   - Already excluded in .gitignore

## 📖 Documentation

**Main Guide:** `step_1_1_environment_setup.md`
- Detailed installation instructions
- Troubleshooting common issues
- System requirements
- Next steps

## ⏱️ Time Estimate

- **Automated setup:** 30-60 minutes
- **Manual setup:** 2-4 hours
- Includes: downloading, installing, verifying, and understanding the setup

## 🆘 Troubleshooting

### Virtual environment won't activate
```bash
# Ensure you're using the correct Python version
python3.10 -m venv venv
source venv/bin/activate
```

### Pip install fails
```bash
# Upgrade pip first
pip install --upgrade pip setuptools wheel

# Install dependencies again
pip install -r requirements.txt
```

### NumPy/SciPy compilation errors
```bash
# Ubuntu/Debian
sudo apt install build-essential gfortran libopenblas-dev liblapack-dev

# macOS (requires Homebrew)
brew install gcc openblas lapack
```

### VectorBT Pro license issues
- Use free VectorBT initially: `pip install vectorbt`
- Evaluate if Pro features are needed later
- Pro license: ~$500-1000/year

## 🔜 Next Steps

After completing Step 1.1:

1. **Step 1.2:** Configure Polygon.io API access
2. **Step 1.3:** Build data ingestion pipeline
3. **Step 1.4:** Validate data quality

## 💰 Cost Estimate

**Monthly costs for Phase 1 (Backtesting):**
- Python dependencies: $0 (open source)
- VectorBT Pro (optional): ~$80-100/month
- Polygon.io (required for Step 1.2): ~$89-199/month
- **Total:** $89-299/month

**Note:** Most expensive part is data (Polygon.io). Environment setup itself is free.

## 📞 Support

If you encounter issues:

1. Check `step_1_1_environment_setup.md` troubleshooting section
2. Run `python verify_environment.py` for diagnostics
3. Review error messages carefully
4. Search for specific error messages online

## ✅ Success Criteria

Environment setup is complete when:

- ✅ `verify_environment.py` shows all green checkmarks
- ✅ Project directory structure exists
- ✅ Git repository initialized
- ✅ Configuration template copied and reviewed
- ✅ You can import core libraries in Python

**Test:** Run this in Python:
```python
import numpy as np
import pandas as pd
from hmmlearn import hmm
import vectorbt as vbt
print("✅ Environment ready!")
```

## 📁 Project Structure After Setup

```
RAITS/
├── venv/                      # Virtual environment (git ignored)
├── raits/                     # Main package
│   ├── data/                  # Data directories
│   │   ├── raw/              # Raw data from Polygon.io
│   │   ├── processed/        # Cleaned data
│   │   └── cache/            # API cache
│   ├── hmm/                  # HMM regime detection
│   ├── strategies/           # Trading strategies
│   ├── risk/                 # Risk management
│   ├── utils/                # Utilities
│   ├── tests/                # Test suite
│   ├── logs/                 # Log files
│   └── results/              # Backtest results
├── notebooks/                 # Jupyter notebooks (exploration)
├── docs/                      # Documentation
├── requirements.txt           # Python dependencies
├── .gitignore                 # Git ignore rules
└── config_template.py         # Configuration template
```

---

**Version:** 1.0  
**Last Updated:** February 26, 2026  
**Status:** Production-Ready  

**🎯 Goal:** Get Python environment ready for RAITS development in < 1 hour
