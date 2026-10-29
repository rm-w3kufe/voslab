#!/usr/bin/env python3
"""
design: docs/design/sources/vsl-encoding-cycle-design-v1/vsl_encoding_cycle_design.vsm
(R16_impl_with_design — FASE-1-ENFORCEMENT-2026-08-22)

migrate_to_vsm12.py — Migración batch a VSM 1.2 compliance.

FASE-1-ENFORCEMENT-2026-08-22: Unified timestamp format.

Este script migra archivos .vsm a compliance con VSM 1.2:
1. Convierte date-only headers a timestamp
2. Corrige ¬ en prosa a NOT (excepto en fórmulas)
3. Verifica que cada archivo pase todos los gates

Uso:
  python3 scripts/vsl/migrate_to_vsm12.py [--dry-run] [--fix-¬] [file ...]

Si no se especifican archivos, migra todos los .vsm en spec_revision/
(excluyendo archive/).

Requisitos:
  - scripts/vsl/verify_encoding.py
  - scripts/vsl/not_prose_gate.py
  - scripts/vsl/tokenizer.py
"""
from __future__ import annotations
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = "docs/spec_revision"
EXCLUDE_DIRS = {"archive"}

# Timestamp format: YYYY-MM-DDTHH:MM:SSZ
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Regex for date-only in header: ⟦ ... | YYYY-MM-DD ⟧
RE_DATE_ONLY_HEADER = re.compile(
    r"(⟦[^⟧]*\|\s*)(\d{4}-\d{2}-\d{2})(\s*⟧)"
)

# Regex for NOT in prose (not in formulas)
# Prose patterns: "does NOT have", "NOT word", "is NOT the", etc.
RE_PROSE_NOT = re.compile(
    r"(?<![∀∃¬∧∨⟹⟺∈∉⊂⊆⊄⊃∪∩∅=≠≡≢≈≤≥>+−·Σℝℚℱ{⟨→↔←⟸::=⟦✓◐◯✗?§VSLΩΦ∅⊥⊤])"
    r"¬"
    r"(?![∀∃¬∧∨⟹⟺∈∉⊂⊆⊄⊃∪∩∅=≠≡≢≈≤≥>+−·Σℝℚℱ{⟨→↔←⟸::=⟦✓◐◯✗?§VSLΩΦ∅⊥⊤])"
)


def get_timestamp() -> str:
    """Get current UTC timestamp in VSM 1.2 format."""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def migrate_timestamp(content: str, filepath: Path) -> tuple[str, bool]:
    """
    Migrate date-only header to timestamp.
    
    Returns:
        Tuple of (migrated_content, was_changed)
    """
    def replace_date(match: re.Match) -> str:
        prefix = match.group(1)
        date_str = match.group(2)
        suffix = match.group(3)
        
        # Check if it's already a timestamp (has T)
        if "T" in date_str:
            return match.group(0)
        
        # Convert date-only to timestamp
        timestamp = get_timestamp()
        return f"{prefix}{timestamp}{suffix}"
    
    new_content = RE_DATE_ONLY_HEADER.sub(replace_date, content)
    return new_content, new_content != content


def migrate_prose_not(content: str, filepath: Path) -> tuple[str, bool]:
    """
    Migrate NOT in prose to NOT.
    
    Only fixes NOT that appears in prose context, not in formulas.
    
    Returns:
        Tuple of (migrated_content, was_changed)
    """
    lines = content.split("\n")
    new_lines = []
    changed = False
    
    for i, line in enumerate(lines, 1):
        # Skip comment lines (// at start or after whitespace)
        stripped = line.lstrip()
        if stripped.startswith("//"):
            new_lines.append(line)
            continue
        
        # Skip lines that are clearly formulas (contain =, ⟹, ∀, ∃, etc.)
        # This is a heuristic - formulas typically have these operators
        formula_indicators = ["=", "⟹", "∀", "∃", "∈", "∉", "⊂", "⊆", "∪", "∩"]
        if any(ind in line for ind in formula_indicators):
            new_lines.append(line)
            continue
        
        # Fix ¬ in prose
        new_line = line
        # Pattern: "does ¬have", "¬word", "is ¬the", etc.
        # But not: "¬∀", "¬∃", "¬(…)", etc. (these are formulas)
        
        # Simple heuristic: if ¬ is followed by a letter (not a symbol)
        # and not preceded by a formula symbol, it's likely prose
        if "¬" in line:
            # Check if it's in a formula context
            # Formulas typically have: ¬(, ¬∀, ¬∃, ¬∈, etc.
            # Prose typically has: ¬word, does ¬word, is ¬word
            
            # Replace ¬ followed by a letter with NOT
            new_line = re.sub(r"¬([a-zA-Z])", r"NOT \1", line)
            
            # Replace ¬ at end of word with NOT
            new_line = re.sub(r"(\w)¬(\w)", r"\1 NOT \2", new_line)
            
            if new_line != line:
                changed = True
        
        new_lines.append(new_line)
    
    return "\n".join(new_lines), changed


def verify_file(filepath: Path) -> tuple[bool, list[str]]:
    """
    Verify a file passes all VSM 1.2 gates.
    
    Returns:
        Tuple of (passed, list_of_errors)
    """
    errors = []
    rel_path = str(filepath.relative_to(ROOT))
    
    # 1. Structure (tokenizer)
    result = subprocess.run(
        ["python3", "scripts/vsl/tokenizer.py", "--check", rel_path],
        capture_output=True, text=True, cwd=ROOT
    )
    if result.returncode != 0:
        errors.append(f"Structure: {result.stderr.strip()}")
    
    # 2. Encoding (timestamp)
    result = subprocess.run(
        ["python3", "scripts/vsl/verify_encoding.py", rel_path],
        capture_output=True, text=True, cwd=ROOT
    )
    if result.returncode != 0:
        errors.append(f"Encoding: {result.stderr.strip()}")
    
    # 3. Not-prose gate
    result = subprocess.run(
        ["python3", "scripts/vsl/not_prose_gate.py", rel_path],
        capture_output=True, text=True, cwd=ROOT
    )
    if result.returncode != 0:
        errors.append(f"Not-prose: {result.stderr.strip()}")
    
    return len(errors) == 0, errors


def migrate_file(filepath: Path, dry_run: bool = False, fix_not: bool = False) -> dict:
    """
    Migrate a single file to VSM 1.2 compliance.
    
    Returns:
        Dictionary with migration results
    """
    result = {
        "file": str(filepath.relative_to(ROOT)),
        "timestamp_changed": False,
        "not_changed": False,
        "verified": False,
        "errors": []
    }
    
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        result["errors"].append(f"Read error: {e}")
        return result
    
    # Migrate timestamp
    new_content, ts_changed = migrate_timestamp(content, filepath)
    result["timestamp_changed"] = ts_changed
    
    # Migrate ¬ in prose (if enabled)
    if fix_not:
        new_content, not_changed = migrate_prose_not(new_content, filepath)
        result["not_changed"] = not_changed
    
    # Apply changes
    if new_content != content:
        if dry_run:
            result["errors"].append("DRY RUN: would change file")
        else:
            filepath.write_text(new_content, encoding="utf-8")
            result["errors"].append("File updated")
    
    # Verify
    passed, errors = verify_file(filepath)
    result["verified"] = passed
    if errors:
        result["errors"].extend(errors)
    
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Migrate .vsm files to VSM 1.2")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed")
    parser.add_argument("--fix-not", action="store_true", help="Fix NOT in prose to NOT")
    parser.add_argument("files", nargs="*", help="Files to migrate (default: all in spec_revision)")
    args = parser.parse_args()
    
    # Find files to migrate
    if args.files:
        files = [ROOT / f for f in args.files]
    else:
        files = []
        for f in ROOT.rglob("*.vsm"):
            # Exclude archive/
            rel = f.relative_to(ROOT)
            if any(part in EXCLUDE_DIRS for part in rel.parts):
                continue
            files.append(f)
    
    print(f"=== VSM 1.2 Migration ===")
    print(f"Files to migrate: {len(files)}")
    print(f"Dry run: {args.dry_run}")
    print(f"Fix NOT in prose: {args.fix_not}")
    print()
    
    results = []
    for f in sorted(files):
        print(f"Migrating: {f.relative_to(ROOT)}")
        result = migrate_file(f, args.dry_run, args.fix_not)
        results.append(result)
        
        if result["timestamp_changed"]:
            print(f"  ✓ Timestamp migrated")
        if result["not_changed"]:
            print(f"  ✓ ¬ in prose fixed")
        if result["verified"]:
            print(f"  ✓ Verified")
        else:
            print(f"  ✗ Errors: {result['errors']}")
        print()
    
    # Summary
    timestamp_changed = sum(1 for r in results if r["timestamp_changed"])
    not_changed = sum(1 for r in results if r["not_changed"])
    verified = sum(1 for r in results if r["verified"])
    
    print(f"=== Summary ===")
    print(f"Timestamp migrated: {timestamp_changed}")
    print(f"¬ in prose fixed: {not_changed}")
    print(f"Verified: {verified}/{len(results)}")
    
    return 0 if verified == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
