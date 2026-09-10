#!/usr/bin/env python3
"""
check.py — VSM validator script.

This script validates .vsm files for:
- VSM format compliance (headers, footers)
- Version correctness (vsm-1.2.1)
- Timestamp generation (no hardcoded timestamps)
- Structure validation

Usage:
    python3 scripts/vsl/validator/check.py <file.vsm>

Exit codes:
    0: Validation passed or advisory issues
    1: Policy breach (version violation, etc.)
"""

import sys
import re
from pathlib import Path

# Canonical hardcoded-timestamp detection lives in
# packages/framework/vos_kernel/utils/vsm_kernel.py (single source).
# Fallback mirror below is ONLY for standalone runs; test_parity in
# system/kernel/tests/ fails if the two ever diverge.
try:
    _ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_ROOT / "packages" / "framework"))
    from vos_kernel.utils.vsm_kernel import is_hardcoded_timestamp as _canon
    _CANON = True
except Exception:
    _CANON = False
    _canon = None


# Valid footer formats:
# 1. Short: ⟦ /name ⟧
# 2. Medium: ⟦ /name | version | timestamp ⟧
# 3. Full: ⟦ /name | type | version | timestamp ⟧
# Footer patterns - strict (no trailing whitespace allowed after ⟧)
FOOTER_SHORT = re.compile(r'⟦\s*/(\w+)\s*⟧$')
FOOTER_MEDIUM = re.compile(r'⟦\s*/(\w+)\s*\|\s*(vsm-[\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧$')
FOOTER_FULL = re.compile(r'⟦\s*/(\w+)\s*\|\s*(\w[\w.-]*)\s*\|\s*(vsm-[\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧$')

# Header format: ⟦ name | TYPE-v1 | vsm-1.2.1 | timestamp ⟧
# TYPE may contain dots (e.g. VSL-CORE-BOOT-v1.1) — S5 decision 2026-09-09.
HEADER = re.compile(r'⟦\s*(\w+)\s*\|\s*(\w[\w.-]*)\s*\|\s*(vsm-[\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧')


def validate_vsm_file(filepath: str) -> dict:
    """Validate a VSM file.
    
    Args:
        filepath: Path to .vsm file
        
    Returns:
        Dict with validation results
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "advisory": []
    }
    
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Cannot read file: {e}")
        return result
    
    lines = content.split('\n')
    
    # Check for header
    header_match = HEADER.search(content)
    if not header_match:
        result["errors"].append("Missing or invalid header")
        result["valid"] = False
    else:
        version = header_match.group(3)
        if version != "vsm-1.2.1":
            result["errors"].append(f"Wrong version in header: {version} (expected: vsm-1.2.1)")
            result["valid"] = False
    
    # Check for @vsm declaration
    vsm_match = re.search(r'@vsm\s+([\d.]+)', content)
    if not vsm_match:
        result["errors"].append("Missing @vsm declaration")
        result["valid"] = False
    else:
        version = vsm_match.group(1)
        if version != "1.2.1":
            result["errors"].append(f"Wrong @vsm version: {version} (expected: 1.2.1)")
            result["valid"] = False
    
    # Check for @status declaration
    if "@status" not in content:
        result["warnings"].append("Missing @status declaration")
    
    # Check for footer - SHORT format is PREFERRED
    footer_full_match = FOOTER_FULL.search(content)
    footer_medium_match = FOOTER_MEDIUM.search(content)
    footer_short_match = FOOTER_SHORT.search(content)
    
    if footer_short_match:
        # Short format: ⟦ /name ⟧ - PREFERRED
        # Check header/footer name match
        if header_match:
            header_name = header_match.group(1)
            footer_name = footer_short_match.group(1)
            if header_name != footer_name:
                result["errors"].append(f"Header/footer name mismatch: {header_name} != {footer_name}")
                result["valid"] = False
    
    elif footer_medium_match:
        # Medium format: ⟦ /name | version | timestamp ⟧ - Advisory
        version = footer_medium_match.group(2)
        if version != "vsm-1.2.1":
            result["errors"].append(f"Wrong version in footer: {version} (expected: vsm-1.2.1)")
            result["valid"] = False
        
        result["advisory"].append("Footer uses medium format (should be short: ⟦ /name ⟧)")
        
        # Check header/footer name match
        if header_match:
            header_name = header_match.group(1)
            footer_name = footer_medium_match.group(1)
            if header_name != footer_name:
                result["errors"].append(f"Header/footer name mismatch: {header_name} != {footer_name}")
                result["valid"] = False
    
    elif footer_full_match:
        # Full format: ⟦ /name | type | version | timestamp ⟧ - Advisory
        version = footer_full_match.group(3)
        if version != "vsm-1.2.1":
            result["errors"].append(f"Wrong version in footer: {version} (expected: vsm-1.2.1)")
            result["valid"] = False
        
        result["advisory"].append("Footer uses full format (should be short: ⟦ /name ⟧)")
        
        # Check header/footer name match
        if header_match:
            header_name = header_match.group(1)
            footer_name = footer_full_match.group(1)
            if header_name != footer_name:
                result["errors"].append(f"Header/footer name mismatch: {header_name} != {footer_name}")
                result["valid"] = False
    
    else:
        result["errors"].append("Missing or invalid footer")
        result["valid"] = False
    
    # Check for hardcoded timestamps - these are POLICY BREACHES.
    # Canonical rules (vsm_kernel); fallback mirror if import failed.
    if _CANON:
        hit = _canon(content)
        if hit:
            result["errors"].append(f"HARDCODED TIMESTAMP: {hit} (POLICY BREACH)")
            result["valid"] = False
    else:
        hardcoded_patterns = [
            (r'T\d{2}:00:00Z', "minute+second zero"),  # hardcoded-allow: fallback mirror of canonical set
            (r'T00:\d{2}:\d{2}Z', "midnight hour"),  # hardcoded-allow: fallback mirror of canonical set
            (r'T\d{2}:00:\d{2}Z', "zero minute"),  # hardcoded-allow: fallback mirror of canonical set
            (r'T\d{2}:\d{2}:00Z', "zero seconds (canonical gate)"),  # hardcoded-allow: fallback mirror of canonical set
            (r'T12:00:00Z', "noon placeholder"),  # hardcoded-allow: fallback mirror of canonical set
            (r'2026-01-01T', "year-start placeholder"),  # hardcoded-allow: fallback mirror of canonical set
            (r'2025-01-01T', "previous-year placeholder"),  # hardcoded-allow: fallback mirror of canonical set
            (r'1970-01-01T', "unix epoch"),  # hardcoded-allow: fallback mirror of canonical set
            (r'2000-01-01T', "y2k placeholder"),  # hardcoded-allow: fallback mirror of canonical set
            (r'2099-', "far-future placeholder"),  # hardcoded-allow: fallback mirror of canonical set
        ]
        for pattern, desc in hardcoded_patterns:
            if re.search(pattern, content):
                result["errors"].append(f"HARDCODED TIMESTAMP: {desc} (POLICY BREACH)")
                result["valid"] = False

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: check.py <file.vsm>")
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    # Check if file exists
    if not Path(filepath).exists():
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    
    # Validate
    result = validate_vsm_file(filepath)
    
    # R18-BLOCK marker (S5 decision 2026-09-09): version violations are
    # policy breaches and MUST block write-time (the orchestrator gates on
    # this marker). Grammar/encoding failures stay marker-free = advisory.
    if any("Wrong version" in e for e in result["errors"]):
        print("[R18-BLOCK] version violation: edited doc is not at "
              "vsm-1.2.1 / @vsm 1.2.1")

    # Print results
    if result["errors"]:
        print("ERRORS:")
        for error in result["errors"]:
            print(f"  - {error}")
    
    if result["warnings"]:
        print("WARNINGS:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    
    if result["advisory"]:
        print("ADVISORY:")
        for advisory in result["advisory"]:
            print(f"  - {advisory}")
    
    if result["valid"]:
        print("PASS: VSM validation passed")
        sys.exit(0)
    else:
        print("FAIL: VSM validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
