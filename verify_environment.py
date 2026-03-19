#!/usr/bin/env python3
"""
RAITS Environment Verification Script

This script verifies that all required dependencies are installed and working correctly.
Run this after installing dependencies with pip install -r requirements.txt

Usage:
    python verify_environment.py
"""

import sys
from typing import Tuple, List

def check_python_version() -> Tuple[bool, str]:
    """Check if Python version meets requirements."""
    version = sys.version_info
    required_major, required_minor = 3, 10
    
    if version.major >= required_major and version.minor >= required_minor:
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    else:
        return False, f"Python {version.major}.{version.minor}.{version.micro} (requires 3.10+)"

def check_import(module_name: str, display_name: str = None) -> Tuple[bool, str]:
    """
    Try to import a module and return success status with version info.
    
    Args:
        module_name: Name of the module to import
        display_name: Display name for the module (defaults to module_name)
    
    Returns:
        (success, message) tuple
    """
    if display_name is None:
        display_name = module_name
    
    try:
        module = __import__(module_name)
        
        # Try to get version
        version = "installed"
        if hasattr(module, '__version__'):
            version = module.__version__
        
        return True, f"{display_name} {version}"
    except ImportError as e:
        return False, f"{display_name}: {str(e)}"

def verify_environment():
    """Verify all dependencies are installed correctly."""
    
    print("=" * 70)
    print("RAITS Environment Verification")
    print("=" * 70)
    print()
    
    # Track results
    checks: List[Tuple[str, bool, str]] = []
    
    # Check Python version
    success, message = check_python_version()
    checks.append(("Python Version", success, message))
    
    # Define dependencies to check
    dependencies = [
        # Core data science
        ('numpy', 'NumPy'),
        ('pandas', 'Pandas'),
        ('scipy', 'SciPy'),
        
        # Backtesting
        ('vectorbt', 'VectorBT'),
        
        # Machine learning
        ('hmmlearn', 'hmmlearn (HMM)'),
        ('sklearn', 'scikit-learn'),
        
        # Analytics
        ('quantstats', 'QuantStats'),
        
        # Data acquisition
        ('polygon', 'Polygon API Client'),
        ('requests', 'Requests'),
        
        # Testing
        ('pytest', 'pytest'),
        
        # Utilities
        ('tqdm', 'tqdm (progress bars)'),
    ]
    
    # Optional dependencies (won't fail if missing)
    optional_dependencies = [
        ('vectorbtpro', 'VectorBT Pro'),
        ('structlog', 'structlog'),
        ('ipython', 'IPython'),
        ('jupyter', 'Jupyter'),
    ]
    
    print("Core Dependencies:")
    print("-" * 70)
    for module_name, display_name in dependencies:
        success, message = check_import(module_name, display_name)
        checks.append((display_name, success, message))
        status = "✓" if success else "✗"
        print(f"{status} {message}")
    
    print()
    print("Optional Dependencies:")
    print("-" * 70)
    for module_name, display_name in optional_dependencies:
        success, message = check_import(module_name, display_name)
        status = "✓" if success else "○"
        print(f"{status} {message}")
    
    print()
    print("=" * 70)
    
    # Check if all required dependencies passed
    core_checks = [c for c in checks if c[0] != "Python Version" or c[1]]
    failed_checks = [c for c in core_checks if not c[1]]
    
    if not failed_checks:
        print("✅ All core dependencies verified successfully!")
        print()
        print("Environment is ready for RAITS development.")
        print()
        print("Next steps:")
        print("  1. Configure Polygon.io API access (Step 1.2)")
        print("  2. Build data ingestion pipeline (Step 1.3)")
        print("  3. Validate data quality (Step 1.4)")
        return 0
    else:
        print("❌ Some dependencies failed verification:")
        print()
        for name, _, message in failed_checks:
            print(f"  - {message}")
        print()
        print("Please install missing dependencies:")
        print("  pip install -r requirements.txt")
        return 1

def test_basic_functionality():
    """Test basic functionality of key libraries."""
    print()
    print("Testing Basic Functionality:")
    print("-" * 70)
    
    try:
        import numpy as np
        arr = np.random.randn(100)
        print(f"✓ NumPy array operations: mean={arr.mean():.4f}, std={arr.std():.4f}")
    except Exception as e:
        print(f"✗ NumPy test failed: {e}")
        return False
    
    try:
        import pandas as pd
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=10),
            'value': np.random.randn(10)
        })
        print(f"✓ Pandas DataFrame operations: shape={df.shape}")
    except Exception as e:
        print(f"✗ Pandas test failed: {e}")
        return False
    
    try:
        from hmmlearn import hmm
        model = hmm.GaussianHMM(n_components=3)
        print(f"✓ HMM model creation: {model.n_components} states")
    except Exception as e:
        print(f"✗ HMM test failed: {e}")
        return False
    
    print()
    return True

if __name__ == '__main__':
    exit_code = verify_environment()
    
    if exit_code == 0:
        test_basic_functionality()
    
    sys.exit(exit_code)
