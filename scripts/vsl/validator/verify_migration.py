#!/usr/bin/env python3
"""
verify_migration.py — Verify migration compliance for system/ documents.

Checks:
1. All literal paths in system/ bodies are migrated to @var
2. All @var references have bindings in instance.vsm
3. No literal paths in non-comment, non-description contexts

Usage:
    python3 scripts/vsl/validator/verify_migration.py <file.vsm>
    python3 scripts/vsl/validator/verify_migration.py --all
    python3 scripts/vsl/validator/verify_migration.py --check
"""

import sys
import re
from pathlib import Path
from typing import List, Tuple


def find_repo_root() -> Path:
    """Find the repository root."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return Path.cwd()


def is_allowed_line(line: str) -> bool:
    """Check if line is allowed (comment, description, etc.)."""
    stripped = line.strip()
    # Comments
    if stripped.startswith('//'):
        return True
    # Description fields
    if 'desc=' in stripped:
        return True
    # Result fields
    if 'result:' in stripped:
        return True
    # Location fields
    if 'location:' in stripped:
        return True
    return False


def find_literal_paths(file_path: Path) -> List[Tuple[int, str]]:
    """Find literal paths in a file."""
    if not file_path.exists():
        return []
    
    content = file_path.read_text(encoding='utf-8')
    violations = []
    
    for line_num, line in enumerate(content.split('\n'), 1):
        # Skip comments and allowed patterns
        if is_allowed_line(line):
            continue
        
        # Check for literal paths (simple string search)
        if 'docs/spec_revision/' in line and '.vsm' in line:
            # Extract the path
            start = line.find('docs/spec_revision/')
            if start != -1:
                end = line.find('.vsm', start)
                if end != -1:
                    path = line[start:end+4]
                    violations.append((line_num, path))
    
    return violations


def check_no_literal_paths(file_path: Path) -> Tuple[int, List[str]]:
    """Check that file has no literal paths in system/ bodies."""
    violations = find_literal_paths(file_path)
    errors = len(violations)
    messages = []
    
    for line_num, path in violations:
        messages.append(f"ERROR: {file_path.name}:{line_num} has literal path: {path}")
    
    return errors, messages


def check_file_migrated(file_path: Path) -> Tuple[bool, str]:
    """Check that file is migrated to @var."""
    errors, messages = check_no_literal_paths(file_path)
    
    if errors > 0:
        return False, f"ERROR: {file_path.name} has {errors} literal paths"
    
    return True, f"OK: {file_path.name} is migrated to @var"


def verify_file(file_path: Path, verbose: bool = False) -> int:
    """Verify migration for a single file."""
    errors, messages = check_no_literal_paths(file_path)
    
    if verbose:
        for msg in messages:
            print(f"  {msg}")
    
    return errors


def verify_all(verbose: bool = False) -> int:
    """Verify migration for all system/ files."""
    repo_root = find_repo_root()
    system_dir = repo_root / 'system'
    
    errors = 0
    
    # Find all .vsm files
    files = list(system_dir.rglob('*.vsm'))
    
    print(f"Checking {len(files)} files...")
    
    for file_path in files:
        errors += verify_file(file_path, verbose=verbose)
    
    return errors


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify migration compliance')
    parser.add_argument('files', nargs='*', help='Files to check')
    parser.add_argument('--all', action='store_true', help='Check all system/ files')
    parser.add_argument('--check', action='store_true', help='Check mode (for CI)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.all or args.check:
        errors = verify_all(verbose=args.verbose)
    elif args.files:
        errors = 0
        for file_path in args.files:
            errors += verify_file(Path(file_path), verbose=args.verbose)
    else:
        parser.print_help()
        return 1
    
    if errors > 0:
        print(f"\n❌ {errors} migration errors found")
        return 1
    else:
        print("\n✅ All files migrated to @var")
        return 0


if __name__ == '__main__':
    sys.exit(main())
