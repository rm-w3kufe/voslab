#!/usr/bin/env python3
"""vsm_timestamp.py — Generate deterministic timestamps for VSM documents.

Usage:
    python3 scripts/vsm_timestamp.py <file.vsm>
    python3 scripts/vsm_timestamp.py --git <file.vsm>
    python3 scripts/vsm_timestamp.py --hash <file.vsm>
"""

import sys
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone


def get_git_timestamp(file_path: Path) -> str:
    """Get the git commit date for a file."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ai", "--", str(file_path)],
            capture_output=True,
            text=True,
            cwd=file_path.parent
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse git date format: 2026-09-06 19:41:02 -0300
            git_date = result.stdout.strip()
            dt = datetime.strptime(git_date, "%Y-%m-%d %H:%M:%S %z")
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        pass
    return None


def get_hash_timestamp(file_path: Path) -> str:
    """Generate a deterministic timestamp from file content hash."""
    try:
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        # Use first 8 chars of hash as microseconds
        micros = int(content_hash[:8], 16)
        # Use a fixed base date
        base_date = datetime(2026, 8, 17, 2, 58, 3, tzinfo=timezone.utc)
        return base_date.replace(microsecond=micros % 1000000).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    if sys.argv[1] == "--git":
        file_path = Path(sys.argv[2])
        timestamp = get_git_timestamp(file_path)
        if timestamp:
            print(timestamp)
        else:
            print("No git timestamp found", file=sys.stderr)
            sys.exit(1)
    elif sys.argv[1] == "--hash":
        file_path = Path(sys.argv[2])
        timestamp = get_hash_timestamp(file_path)
        if timestamp:
            print(timestamp)
        else:
            print("Could not generate hash timestamp", file=sys.stderr)
            sys.exit(1)
    else:
        file_path = Path(sys.argv[1])
        # Try git first, fall back to hash
        timestamp = get_git_timestamp(file_path)
        if not timestamp:
            timestamp = get_hash_timestamp(file_path)
        if timestamp:
            print(timestamp)
        else:
            print("Could not generate timestamp", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
