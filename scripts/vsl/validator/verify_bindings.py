#!/usr/bin/env python3
"""
verify_bindings.py — Verify binding completeness for system/ documents.

Checks:
1. All @var references have bindings in instance.vsm
2. All bindings in instance.vsm point to existing files
3. No duplicate bindings

Usage:
    python3 scripts/vsl/validator/verify_bindings.py <file.vsm>
    python3 scripts/vsl/validator/verify_bindings.py --all
    python3 scripts/vsl/validator/verify_bindings.py --check
"""

import sys
import re
from pathlib import Path
from typing import Set, Dict, List, Tuple

# VSL keywords that are not file references
VSL_KEYWORDS = {
    '@vsm', '@status', '@param', '@ref', '@var', '@from_', '@to_', '@version',
    '@always', '@required', '@optional', '@governed', '@forbidden',
    '@analysis', '@channel', '@commit', '@condition', '@degraded',
    '@experimenter', '@formalization', '@free', '@full_vsm',
    '@human', '@idea_origin', '@n', '@pinned_version', '@strict', '@target', '@witness',
}

# Prefixes that indicate real file references
REAL_PREFIXES = {'doc_', 'dir_', 'src_', 'gate_', 'state_', 'connection_', 'ledger_', 'vault_', 'thermal_', 'events_'}


def find_repo_root() -> Path:
    """Find the repository root."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    return Path.cwd()


def extract_bindings_from_instance(instance_path: Path) -> Dict[str, str]:
    """Extract bindings from instance.vsm."""
    bindings = {}
    if not instance_path.exists():
        return bindings
    
    content = instance_path.read_text(encoding='utf-8')
    # Match lines like: binding_name: "path/to/file"
    pattern = r'^\s*(doc_\w+|dir_\w+|src_\w+|gate_\w+|state_\w+|connection_\w+|ledger_\w+|vault_\w+|thermal_\w+|events_\w+)\s*:\s*"([^"]+)"'
    
    for line in content.split('\n'):
        match = re.match(pattern, line)
        if match:
            name, path = match.groups()
            bindings[name] = path
    
    return bindings


def extract_references_from_file(file_path: Path) -> Set[str]:
    """Extract @var references from a file."""
    references = set()
    if not file_path.exists():
        return references
    
    content = file_path.read_text(encoding='utf-8')
    # Find all @word patterns
    for match in re.finditer(r'@(\w+)', content):
        ref = '@' + match.group(1)
        if ref not in VSL_KEYWORDS:
            references.add(ref)
    
    return references


def check_bindings_completeness(instance_path: Path, files: List[Path]) -> Tuple[int, int, List[str]]:
    """Check that all @var references have bindings."""
    bindings = extract_bindings_from_instance(instance_path)
    errors = 0
    warnings = 0
    messages = []
    
    for file_path in files:
        references = extract_references_from_file(file_path)
        for ref in references:
            binding_name = ref[1:]  # Remove @ prefix
            if binding_name not in bindings:
                # Check if it's a real reference (not a partial match)
                if any(binding_name.startswith(prefix) for prefix in REAL_PREFIXES):
                    errors += 1
                    messages.append(f"ERROR: {file_path.name} uses {ref} but no binding exists")
                else:
                    warnings += 1
                    messages.append(f"WARNING: {file_path.name} uses {ref} (may be partial match)")
    
    return errors, warnings, messages


def check_bindings_existence(instance_path: Path) -> Tuple[int, int, List[str]]:
    """Check that all bindings point to existing files."""
    bindings = extract_bindings_from_instance(instance_path)
    repo_root = find_repo_root()
    errors = 0
    warnings = 0
    messages = []
    
    for name, path in bindings.items():
        # Skip node: and spec_root: paths
        if path.startswith('node:') or path.startswith('spec_root:'):
            continue
        
        # Resolve path
        if path.startswith('*/'):
            resolved = repo_root / path[2:]
        else:
            resolved = repo_root / path
        
        if not resolved.exists():
            errors += 1
            messages.append(f"ERROR: Binding {name} points to non-existent file: {path}")
        else:
            warnings += 1
            messages.append(f"OK: Binding {name} → {path}")
    
    return errors, warnings, messages


def check_duplicate_bindings(instance_path: Path) -> Tuple[int, List[str]]:
    """Check for duplicate bindings."""
    bindings = extract_bindings_from_instance(instance_path)
    errors = 0
    messages = []
    
    # Check for duplicate values
    seen_values = {}
    for name, path in bindings.items():
        if path in seen_values:
            errors += 1
            messages.append(f"ERROR: Duplicate binding value: {name} and {seen_values[path]} both point to {path}")
        else:
            seen_values[path] = name
    
    return errors, messages


def verify_file(file_path: Path, verbose: bool = False) -> int:
    """Verify bindings for a single file."""
    repo_root = find_repo_root()
    # S3*-circle 2026-10-04: validate the LIVE corpus (system/), not the
    # frozen docs/spec_revision snapshot (predates workspace layout).
    instance_path = repo_root / 'system/instance/vsf-instance-v1/instance.vsm'
    
    errors = 0
    
    # Check file references
    e, w, msgs = check_bindings_completeness(instance_path, [file_path])
    errors += e
    if verbose:
        for msg in msgs:
            if 'ERROR' in msg:
                print(f"  {msg}")
    
    return errors


def verify_all(verbose: bool = False) -> int:
    """Verify bindings for all system/ files."""
    repo_root = find_repo_root()
    instance_path = repo_root / 'system/instance/vsf-instance-v1/instance.vsm'
    system_dir = repo_root / 'system'
    
    errors = 0
    
    # Find all .vsm files
    files = list(system_dir.rglob('*.vsm'))
    
    print(f"Checking {len(files)} files...")
    
    # Check bindings completeness
    e, w, msgs = check_bindings_completeness(instance_path, files)
    errors += e
    if verbose:
        for msg in msgs:
            if 'ERROR' in msg:
                print(f"  {msg}")
    
    # Check binding existence
    e, w, msgs = check_bindings_existence(instance_path)
    errors += e
    if verbose:
        for msg in msgs:
            if 'ERROR' in msg:
                print(f"  {msg}")
    
    # Check duplicate bindings
    e, msgs = check_duplicate_bindings(instance_path)
    errors += e
    if verbose:
        for msg in msgs:
            if 'ERROR' in msg:
                print(f"  {msg}")
    
    return errors


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify binding completeness')
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
        print(f"\n❌ {errors} binding errors found")
        return 1
    else:
        print("\n✅ All bindings OK")
        return 0


if __name__ == '__main__':
    sys.exit(main())
