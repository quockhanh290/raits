#!/bin/bash
# RAITS Quick Start Setup Script
# This script automates the initial environment setup for Project RAITS Phase 1

set -e  # Exit on error

echo "=========================================="
echo "RAITS Phase 1 - Quick Start Setup"
echo "=========================================="
echo ""

# Check if Python 3.10+ is available
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
REQUIRED_VERSION="3.10"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "❌ Error: Python 3.10+ is required. Found version: $(python3 --version)"
    echo "Please install Python 3.10 or higher and try again."
    exit 1
fi

echo "✓ Python version check passed: $(python3 --version)"
echo ""

# Create virtual environment
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "  Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
echo "✓ Virtual environment activated"
echo ""

# Upgrade pip
echo "Upgrading pip, setuptools, and wheel..."
pip install --upgrade pip setuptools wheel --quiet
echo "✓ Package managers upgraded"
echo ""

# Install dependencies
echo "Installing dependencies from requirements.txt..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
    echo "✓ Dependencies installed"
else
    echo "❌ Error: requirements.txt not found"
    exit 1
fi
echo ""

# Create project directory structure
echo "Creating project directory structure..."
python3 setup_project_structure.py
echo ""

# Initialize git repository
echo "Initializing Git repository..."
if [ ! -d ".git" ]; then
    git init
    echo "✓ Git repository initialized"
    
    if [ -f ".gitignore" ]; then
        git add .gitignore
        git commit -m "Initial commit: Add .gitignore" --quiet
        echo "✓ .gitignore committed"
    fi
else
    echo "  Git repository already exists"
fi
echo ""

# Verify environment
echo "Verifying environment setup..."
python3 verify_environment.py
VERIFY_EXIT_CODE=$?
echo ""

if [ $VERIFY_EXIT_CODE -eq 0 ]; then
    echo "=========================================="
    echo "✅ Setup Complete!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "  1. Activate virtual environment: source venv/bin/activate"
    echo "  2. Configure Polygon.io API key (Step 1.2)"
    echo "  3. Review step_1_1_environment_setup.md for detailed documentation"
    echo ""
    echo "Happy coding! 🚀"
else
    echo "=========================================="
    echo "⚠️  Setup completed with warnings"
    echo "=========================================="
    echo ""
    echo "Some dependencies may need manual installation."
    echo "Review the output above and install missing packages."
fi
