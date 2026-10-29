#!/usr/bin/env python3
"""
verify_versioning.py — Verify versioning compliance for system/ documents.

Checks:
1. All documents have @vsm version
2. Version format is valid (MAJOR.MINOR)
3. Footer matches header
4. Date is ISO 8601 format

Usage:
    python3 scripts/vsl/validator/verify_versioning.py <file.vsm>
    python3 scripts/vsl/validator/verify_versioning.py --all
    python3 scripts/vsl/validator/verify_versioning.py --check
"""

import sys
import re
from pathlib import Path
from typing import Tuple


def find_repo_root() -> Path:
    """Find the repository root."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return Path.cwd()


def extract_header_info(file_path: Path) -> Tuple[str, str, str, str]:
    """Extract header info: name, type, version, date."""
    if not file_path.exists():
        return '', '', '', ''
    
    content = file_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    
    if not lines:
        return '', '', '', ''
    
    header = lines[0].strip()
    # Match: ⟦ name | TYPE | version | date ⟧
    # TYPE can contain hyphens and dots
    match = re.match(r'⟦\s*([\w.]+)\s*\|\s*([\w.-]+)\s*\|\s*(vsm-[\d.]+)\s*\|\s*([\d-]+(?:T[\d:]+(?:\.\d+)?Z)?)\s*⟧', header)
    
    if match:
        return match.groups()
    
    return '', '', '', ''


def extract_footer_info(file_path: Path) -> Tuple[str, str, str, str]:
    """Extract footer info: name, type, version, date."""
    if not file_path.exists():
        return '', '', '', ''
    
    content = file_path.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    
    if not lines:
        return '', '', '', ''
    
    footer = lines[-1].strip()
    # Match: ⟦ /name | TYPE | version | date ⟧
    # TYPE can contain hyphens and dots
    match = re.match(r'⟦\s*/([\w.]+)\s*(?:\|\s*([\w.-]+)\s*\|\s*(vsm-[\d.]+)\s*\|\s*([\d-]+T[\d:]+Z)\s*)?⟧', footer)
    
    if match:
        return match.groups()
    
    return '', '', '', ''


def check_version_exists(file_path: Path) -> Tuple[bool, str]:
    """Check that file has @vsm version."""
    name, type_, version, date = extract_header_info(file_path)
    if not version:
        return False, f"ERROR: {file_path.name} has no @vsm version"
    return True, f"OK: {file_path.name} has @vsm {version}"


def check_version_format(file_path: Path) -> Tuple[bool, str]:
    """Check that @vsm version format is valid."""
    name, type_, version, date = extract_header_info(file_path)
    if version and not re.match(r'^vsm-\d+\.\d+(\.\d+)?$', version):
        return False, f"ERROR: {file_path.name} has invalid @vsm format '{version}'"
    return True, f"OK: {file_path.name} has valid @vsm format {version}"


def check_date_format(file_path: Path) -> Tuple[bool, str]:
    """Check that date format is valid (ISO 8601)."""
    name, type_, version, date = extract_header_info(file_path)
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?Z)?$', date):
        return False, f"ERROR: {file_path.name} has invalid date format '{date}'"
    return True, f"OK: {file_path.name} has valid date format {date}"


def check_header_footer_match(file_path: Path) -> Tuple[bool, str]:
    """Check that header and footer match.

    vsm-1.2.1 §closure changed the closing footer to a NAME-ONLY closure
    ⟦ /name ⟧ (the header keeps the 4-field form). A name-only footer carries
    no type/version/date, so only the name is compared; a legacy 4-field
    footer is compared in full.
    """
    h_name, h_type, h_version, h_date = extract_header_info(file_path)
    f_name, f_type, f_version, f_date = extract_footer_info(file_path)

    if not h_name:
        return False, f"ERROR: {file_path.name} has invalid header format"

    if not f_name:
        return False, f"ERROR: {file_path.name} has invalid footer format"

    # Name-only footer: only the name is meaningful.
    if not f_type and not f_version and not f_date:
        if h_name != f_name:
            return False, (f"ERROR: {file_path.name} name mismatch: "
                           f"{h_name} vs {f_name}")
        return True, f"OK: {file_path.name} header/footer name match"

    mismatches = []
    if h_name != f_name:
        mismatches.append(f"name: {h_name} vs {f_name}")
    if h_type != f_type:
        mismatches.append(f"type: {h_type} vs {f_type}")
    if h_version != f_version:
        mismatches.append(f"version: {h_version} vs {f_version}")
    if h_date != f_date:
        mismatches.append(f"date: {h_date} vs {f_date}")

    if mismatches:
        return False, (f"ERROR: {file_path.name} header/footer mismatch: "
                       f"{', '.join(mismatches)}")

    return True, f"OK: {file_path.name} header/footer match"


def verify_file(file_path: Path, verbose: bool = False) -> int:
    """Verify versioning for a single file."""
    errors = 0
    
    checks = [
        check_version_exists,
        check_version_format,
        check_date_format,
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
    """Verify versioning for all system/ files."""
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
    
    parser = argparse.ArgumentParser(description='Verify versioning compliance')
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
        print(f"\n❌ {errors} versioning errors found")
        return 1
    else:
        print("\n✅ All versioning OK")
        return 0


if __name__ == '__main__':
    sys.exit(main())
