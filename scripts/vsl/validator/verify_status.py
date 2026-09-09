#!/usr/bin/env python3
"""
verify_status.py — Verify status transitions for system/ documents.

Checks:
1. All documents have @status field
2. Status values are valid (proposed, active, ratified, archived)
3. Status transitions are valid (no archived → active, etc.)

Usage:
    python3 scripts/vsl/validator/verify_status.py <file.vsm>
    python3 scripts/vsl/validator/verify_status.py --all
    python3 scripts/vsl/validator/verify_status.py --check
"""

import sys
import re
from pathlib import Path
from typing import Set, Dict, List, Tuple

# Valid status values
VALID_STATUSES = {'proposed', 'active', 'ratified', 'archived'}

# Valid transitions
VALID_TRANSITIONS = {
    'proposed': {'active', 'archived'},
    'active': {'ratified', 'archived'},
    'ratified': {'archived'},
    'archived': set(),  # Cannot transition from archived
}


def find_repo_root() -> Path:
    """Find the repository root."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return Path.cwd()


def extract_status(file_path: Path) -> str:
    """Extract @status from a file."""
    if not file_path.exists():
        return ''
    
    content = file_path.read_text(encoding='utf-8')
    for line in content.split('\n'):
        match = re.match(r'^@status\s+(\w+)', line)
        if match:
            return match.group(1)
    
    return ''


def extract_vsm_version(file_path: Path) -> str:
    """Extract @vsm version from a file."""
    if not file_path.exists():
        return ''
    
    content = file_path.read_text(encoding='utf-8')
    for line in content.split('\n'):
        match = re.match(r'^@vsm\s+(\d+\.\d+)', line)
        if match:
            return match.group(1)
    
    return ''


def check_status_exists(file_path: Path) -> Tuple[bool, str]:
    """Check that file has @status field."""
    status = extract_status(file_path)
    if not status:
        return False, f"ERROR: {file_path.name} has no @status field"
    return True, f"OK: {file_path.name} has @status {status}"


def check_status_valid(file_path: Path) -> Tuple[bool, str]:
    """Check that @status value is valid."""
    status = extract_status(file_path)
    if status and status not in VALID_STATUSES:
        return False, f"ERROR: {file_path.name} has invalid @status '{status}'"
    return True, f"OK: {file_path.name} has valid @status {status}"


def check_version_exists(file_path: Path) -> Tuple[bool, str]:
    """Check that file has @vsm version."""
    version = extract_vsm_version(file_path)
    if not version:
        return False, f"ERROR: {file_path.name} has no @vsm version"
    return True, f"OK: {file_path.name} has @vsm {version}"


def check_version_format(file_path: Path) -> Tuple[bool, str]:
    """Check that @vsm version format is valid."""
    version = extract_vsm_version(file_path)
    if version and not re.match(r'^\d+\.\d+$', version):
        return False, f"ERROR: {file_path.name} has invalid @vsm format '{version}'"
    return True, f"OK: {file_path.name} has valid @vsm format {version}"


def check_header_footer_match(file_path: Path) -> Tuple[bool, str]:
    """Check that header and footer match."""
    if not file_path.exists():
        return False, f"ERROR: {file_path.name} does not exist"
    
    content = file_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    
    if len(lines) < 2:
        return False, f"ERROR: {file_path.name} has less than 2 lines"
    
    header = lines[0].strip()
    footer = lines[-1].strip()
    
    # Extract name from header: ⟦ name | TYPE | version | date ⟧
    header_match = re.match(r'⟦\s*([\w.]+)\s*\|', header)
    # Extract name from footer: ⟦ /name ⟧ (name-only, vsm-1.2.1 §closure) or
    # the legacy ⟦ /name | TYPE | version | date ⟧. Only the name is compared.
    footer_match = re.match(r'⟦\s*/([\w.]+)', footer)
    
    if not header_match or not footer_match:
        return False, f"ERROR: {file_path.name} has invalid header/footer format"
    
    header_name = header_match.group(1)
    footer_name = footer_match.group(1)
    
    if header_name != footer_name:
        return False, f"ERROR: {file_path.name} header/footer mismatch: {header_name} vs {footer_name}"
    
    return True, f"OK: {file_path.name} header/footer match"


def verify_file(file_path: Path, verbose: bool = False) -> int:
    """Verify status for a single file."""
    errors = 0
    
    checks = [
        check_status_exists,
        check_status_valid,
        check_version_exists,
        check_version_format,
        check_header_footer_match,
    ]
    
    for check in checks:
        ok, msg = check(file_path)
        if not ok:
            errors += 1
            if verbose:
                print(f"  {msg}")
        elif verbose:
            print(f"  {msg}")
    
    return errors


def verify_all(verbose: bool = False) -> int:
    """Verify status for all system/ files."""
    repo_root = find_repo_root()
    system_dir = repo_root / 'docs/spec_revision/system'
    
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
    
    parser = argparse.ArgumentParser(description='Verify status transitions')
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
        print(f"\n❌ {errors} status errors found")
        return 1
    else:
        print("\n✅ All statuses OK")
        return 0


if __name__ == '__main__':
    sys.exit(main())
