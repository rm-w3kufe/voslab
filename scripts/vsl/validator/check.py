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


# Valid footer formats:
# 1. Short: ⟦ /name ⟧
# 2. Medium: ⟦ /name | version | timestamp ⟧
# 3. Full: ⟦ /name | type | version | timestamp ⟧
# Footer patterns - strict (no trailing whitespace allowed after ⟧)
FOOTER_SHORT = re.compile(r'⟦\s*/(\w+)\s*⟧$')
FOOTER_MEDIUM = re.compile(r'⟦\s*/(\w+)\s*\|\s*(vsm-[\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧$')
FOOTER_FULL = re.compile(r'⟦\s*/(\w+)\s*\|\s*(\w[\w-]*)\s*\|\s*(vsm-[\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧$')

# Header format: ⟦ name | TYPE-v1 | vsm-1.2.1 | timestamp ⟧
HEADER = re.compile(r'⟦\s*(\w+)\s*\|\s*(\w[\w-]*)\s*\|\s*(vsm-[\d.]+)\s*\|\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧')


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
    
    # Check for hardcoded timestamps - these are POLICY BREACHES
    hardcoded_patterns = [
        (r'T\d{2}:00:00Z', "timestamp ends with :00:00"),
        (r'T00:\d{2}:\d{2}Z', "timestamp starts with T00:"),
        (r'T\d{2}:00:\d{2}Z', "timestamp has :00: in minutes"),
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
