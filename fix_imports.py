"""
Quick fix for import errors in Step 1.4 files

Run this to automatically fix the import statements.
"""

import os
from pathlib import Path

def fix_imports():
    """Fix import statements in validator and example files."""
    
    # Get project root
    project_root = Path.cwd()
    
    print("Fixing imports in RAITS data files...")
    print(f"Project root: {project_root}")
    
    # File to fix
    validator_file = project_root / 'raits' / 'data' / 'raits_data_validator.py'
    example_file = project_root / 'example_data_validation.py'
    
    files_fixed = 0
    
    # Fix validator file
    if validator_file.exists():
        print(f"\n1. Fixing {validator_file}...")
        
        with open(validator_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix main imports
        content = content.replace(
            'from raits_data_models import',
            'from raits.data.raits_data_models import'
        )
        
        # Fix example imports
        content = content.replace(
            'from raits_mock_data import',
            'from raits.data.raits_mock_data import'
        )
        
        with open(validator_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("   ✓ Fixed raits_data_validator.py")
        files_fixed += 1
    else:
        print(f"   ✗ File not found: {validator_file}")
    
    # Fix example file
    if example_file.exists():
        print(f"\n2. Fixing {example_file}...")
        
        with open(example_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix imports
        content = content.replace(
            'from raits_data_pipeline import',
            'from raits.data.raits_data_pipeline import'
        )
        
        content = content.replace(
            'from raits_data_validator import',
            'from raits.data.raits_data_validator import'
        )
        
        with open(example_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("   ✓ Fixed example_data_validation.py")
        files_fixed += 1
    else:
        print(f"   ✗ File not found: {example_file}")
    
    print(f"\n{'='*60}")
    if files_fixed == 2:
        print("✅ All imports fixed!")
        print("\nNow run:")
        print("  python verify_step_1_complete.py")
    elif files_fixed > 0:
        print(f"⚠️  Fixed {files_fixed}/2 files")
        print("Some files may be missing - check file locations")
    else:
        print("❌ No files found to fix")
        print("\nMake sure you're in the RAITS project directory:")
        print("  cd C:\\Users\\kdo\\OneDrive - Enfinite\\RAITS")
        print("  python fix_imports.py")


if __name__ == '__main__':
    fix_imports()
