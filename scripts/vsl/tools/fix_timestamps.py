#!/usr/bin/env python3
"""
fix_timestamps.py — Update old VSM timestamps to current time.
Addresses MED-001 and MED-006 in technical_debt_registry.vsm.

This script finds all .vsm files with timestamps older than 24 hours
and updates them to the current time.
"""
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_vsm_files(root: str) -> list:
    """Find all .vsm files in the workspace."""
    vsm_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden dirs and __pycache__
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
        for f in filenames:
            if f.endswith('.vsm'):
                vsm_files.append(os.path.join(dirpath, f))
    return vsm_files


def extract_timestamp(content: str) -> tuple:
    """Extract timestamp from VSM header. Returns (timestamp_str, match_object)."""
    # Match the timestamp in the header: ⟦ name | TYPE | version | TIMESTAMP ⟧
    # More flexible pattern that handles various spacing
    pattern = r'(⟦[^|]+\|\s*\S+\s*\|\s*\S+\s*\|\s*)(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)(\s*⟧)'
    match = re.search(pattern, content)
    if match:
        return match.group(2), match
    return None, None


def is_old_timestamp(ts_str: str, max_hours: int = 24) -> bool:
    """Check if timestamp is older than max_hours."""
    try:
        ts_time = datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        current_time = datetime.now(timezone.utc)
        diff_hours = abs((current_time - ts_time).total_seconds()) / 3600
        return diff_hours > max_hours
    except ValueError:
        return False


def update_timestamp(content: str, old_ts: str, new_ts: str) -> str:
    """Replace old timestamp with new timestamp in content."""
    return content.replace(old_ts, new_ts)


def main():
    root = os.getcwd()
    if len(sys.argv) > 1:
        root = sys.argv[1]
    
    print(f"Scanning {root} for .vsm files with old timestamps...")
    
    vsm_files = find_vsm_files(root)
    print(f"Found {len(vsm_files)} .vsm files")
    
    updated = 0
    skipped = 0
    errors = 0
    
    current_ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    
    for filepath in vsm_files:
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            old_ts, match = extract_timestamp(content)
            if old_ts is None:
                skipped += 1
                continue
            
            if is_old_timestamp(old_ts):
                new_content = update_timestamp(content, old_ts, current_ts)
                with open(filepath, 'w') as f:
                    f.write(new_content)
                print(f"  UPDATED: {filepath}")
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  ERROR: {filepath}: {e}")
            errors += 1
    
    print(f"\nResults: {updated} updated, {skipped} skipped, {errors} errors")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
