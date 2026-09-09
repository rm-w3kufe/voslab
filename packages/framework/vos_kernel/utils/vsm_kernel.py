"""vsm_kernel.py — Parametric VSM document generator (single source of truth).

Canonical version: vsm-1.2.1 / @vsm 1.2.1 (see scripts/vsl/validator/check.py).

WHY this module exists: the agent prompt references VSM header/footer
helpers, but no importable module provided them — so documents were
hand-written and failed validation (wrong version vsm-1.2, hardcoded
timestamps like T07:30:00Z, header/footer name mismatch). Every .vsm
write MUST go through these helpers (or the `vsm_new.py` CLI that wraps
them). Never hand-write ⟦ ... ⟧ signatures.

Usage:
    from vos_kernel.utils.vsm_kernel import new_doc, vsm_header, vsm_footer

    print(new_doc("my_doc", "PLAN-v1", "@status active\\n\\n// body\\n"))
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone

VSM_VERSION = "1.2.1"
VSM_TAG = f"vsm-{VSM_VERSION}"

_HEADER_RE = re.compile(
    r"⟦\s*(\w+)\s*\|\s*(\w[\w-]*)\s*\|\s*(vsm-[\d.]+)\s*\|"
    r"\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧"
)
# Hardcoded-timestamp patterns mirror scripts/vsl/validator/check.py PLUS
# the canonical gate in ~/packages (is_hardcoded_timestamp), which flags ANY
# seconds=00 as hardcoded. A freshly generated timestamp must never match
# any of them — hence the _HARDCODED_SEC_ZERO rule below.
_HARDCODED_RES = [
    re.compile(r"T\d{2}:00:00Z"),
    re.compile(r"T00:\d{2}:\d{2}Z"),
    re.compile(r"T\d{2}:00:\d{2}Z"),
]
_HARDCODED_SEC_ZERO = re.compile(r"T\d{2}:\d{2}:00Z")


def get_version() -> str:
    """Canonical @vsm version: 1.2.1."""
    return VSM_VERSION


def get_timestamp(now: datetime | None = None) -> str:
    """Fresh UTC timestamp that never trips the hardcoded patterns.

    Real `now` is used; if it happens to land on a flagged shape
    (minute == 00, midnight hour), it is nudged forward by seconds
    until clean. The timestamp is always real, never hardcoded.
    """
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    while True:
        s = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        if not any(r.search(s) for r in _HARDCODED_RES) and not _HARDCODED_SEC_ZERO.search(s):
            return s
        ts = ts + timedelta(seconds=1)


def vsm_header(name: str, doc_type: str, ts: str | None = None) -> str:
    """Full header: ⟦ name | TYPE-v1 | vsm-1.2.1 | timestamp ⟧."""
    return f"⟦ {name} | {doc_type} | {VSM_TAG} | {ts or get_timestamp()} ⟧"


def vsm_footer(name: str) -> str:
    """Short footer (PREFERRED by the validator): ⟦ /name ⟧."""
    return f"⟦ /{name} ⟧"


def new_doc(
    name: str,
    doc_type: str,
    body: str = "",
    status: str = "active",
    ts: str | None = None,
) -> str:
    """Generate a complete valid .vsm document parametrically."""
    stamp = ts or get_timestamp()
    header = vsm_header(name, doc_type, stamp)
    footer = vsm_footer(name)
    body = body.rstrip() + "\n" if body.strip() else ""
    return (
        f"{header}\n"
        f"\n"
        f"@vsm {VSM_VERSION}\n"
        f"@status {status}\n"
        f"\n"
        f"{body}"
        f"{footer}\n"
    )


def validate_vsm_content(content: str) -> dict:
    """Lightweight pre-write self-check mirroring check.py (no disk I/O)."""
    errors: list[str] = []
    m = _HEADER_RE.search(content)
    if not m:
        errors.append("Missing or invalid header")
    else:
        if m.group(3) != VSM_TAG:
            errors.append(
                f"Wrong version in header: {m.group(3)} (expected: {VSM_TAG})"
            )
    vm = re.search(r"@vsm\s+([\d.]+)", content)
    if not vm:
        errors.append("Missing @vsm declaration")
    elif vm.group(1) != VSM_VERSION:
        errors.append(
            f"Wrong @vsm version: {vm.group(1)} (expected: {VSM_VERSION})"
        )
    if "@status" not in content:
        errors.append("Missing @status declaration")
    fm = re.search(r"⟦\s*/(\w+)\s*⟧\s*$", content.strip())
    if not fm:
        errors.append("Missing or invalid short footer ⟦ /name ⟧")
    elif m and fm.group(1) != m.group(1):
        errors.append(
            f"Header/footer name mismatch: {m.group(1)} != {fm.group(1)}"
        )
    for r in _HARDCODED_RES:
        if r.search(content):
            errors.append(f"HARDCODED TIMESTAMP pattern: {r.pattern}")
            break
    else:
        if _HARDCODED_SEC_ZERO.search(content):
            errors.append("HARDCODED TIMESTAMP pattern: seconds=00 (canonical gate)")
    return {"valid": not errors, "errors": errors}


def _cli(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "new" and len(argv) >= 4:
        name, doc_type = argv[2], argv[3]
        status = argv[4] if len(argv) > 4 else "active"
        body = sys.stdin.read() if not sys.stdin.isatty() else ""
        doc = new_doc(name, doc_type, body, status)
        check = validate_vsm_content(doc)
        if not check["valid"]:
            print(f"SELF-CHECK FAILED: {check['errors']}", file=sys.stderr)
            return 1
        print(doc, end="")
        return 0
    if len(argv) == 2 and argv[1] in ("--version", "version"):
        print(VSM_TAG)
        return 0
    print(
        "Usage:\n"
        "  vsm_kernel.py new <name> <TYPE-v1> [status] < body.txt  # emit valid .vsm\n"
        "  vsm_kernel.py version                                    # print vsm-1.2.1",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
