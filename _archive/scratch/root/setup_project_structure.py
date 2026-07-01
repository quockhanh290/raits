#!/usr/bin/env python3
"""
RAITS Project Directory Structure Setup Script

This script creates the recommended directory structure for Project RAITS Phase 1.
Run this after creating your virtual environment.

Usage:
    python setup_project_structure.py
"""

from pathlib import Path
import sys

def create_directory_structure():
    """Create the complete RAITS project directory structure."""
    
    # Define directory structure
    directories = [
        'raits',
        'raits/data',
        'raits/data/raw',
        'raits/data/processed',
        'raits/data/cache',
        'raits/hmm',
        'raits/strategies',
        'raits/risk',
        'raits/utils',
        'raits/tests',
        'raits/tests/unit',
        'raits/tests/integration',
        'raits/logs',
        'raits/results',
        'notebooks',  # For Jupyter notebooks (exploration)
        'docs',  # For documentation
    ]
    
    # Define __init__.py files
    init_files = [
        'raits/__init__.py',
        'raits/data/__init__.py',
        'raits/hmm/__init__.py',
        'raits/strategies/__init__.py',
        'raits/risk/__init__.py',
        'raits/utils/__init__.py',
        'raits/tests/__init__.py',
        'raits/tests/unit/__init__.py',
        'raits/tests/integration/__init__.py',
    ]
    
    print("Creating RAITS project directory structure...")
    print("=" * 60)
    
    # Create directories
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"✓ Created: {directory}/")
        else:
            print(f"  Exists:  {directory}/")
    
    print()
    
    # Create __init__.py files
    for init_file in init_files:
        file_path = Path(init_file)
        if not file_path.exists():
            file_path.touch()
            print(f"✓ Created: {init_file}")
        else:
            print(f"  Exists:  {init_file}")
    
    print()
    print("=" * 60)
    print("✅ Project directory structure created successfully!")
    print()
    print("Directory tree:")
    print_directory_tree(Path('.'), prefix='', max_depth=3)

def print_directory_tree(directory: Path, prefix: str = '', max_depth: int = 3, current_depth: int = 0):
    """Print directory tree structure."""
    if current_depth >= max_depth:
        return
    
    if directory.name.startswith('.') or directory.name in ['venv', 'env', '__pycache__']:
        return
    
    contents = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    
    for i, item in enumerate(contents):
        is_last = i == len(contents) - 1
        current_prefix = '└── ' if is_last else '├── '
        print(f"{prefix}{current_prefix}{item.name}{'/' if item.is_dir() else ''}")
        
        if item.is_dir():
            extension = '    ' if is_last else '│   '
            print_directory_tree(item, prefix + extension, max_depth, current_depth + 1)

if __name__ == '__main__':
    try:
        create_directory_structure()
    except Exception as e:
        print(f"❌ Error creating directory structure: {e}", file=sys.stderr)
        sys.exit(1)
