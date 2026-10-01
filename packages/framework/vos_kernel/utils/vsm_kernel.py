"""vsm_kernel.py — Parametric VSM document generator (single source of truth).

Canonical version: vsm-1.2.1 / @vsm 1.2.1 (see scripts/vsl/validator/check.py).

WHY this module exists: the agent prompt references VSM header/footer
helpers, but no importable module provided them — so documents were
hand-written and failed validation (wrong version vsm-1.2, hardcoded
timestamps like T07:30:00Z, header/footer name mismatch). Every .vsm  # hardcoded-allow: documented example
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
    # TYPE may contain dots (S5 decision 2026-09-09, e.g. VSL-CORE-BOOT-v1.1)
    r"⟦\s*(\w+)\s*\|\s*(\w[\w.-]*)\s*\|\s*(vsm-[\d.]+)\s*\|"
    r"\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*⟧"
)
# Canonical hardcoded-timestamp patterns (CHECK-SCAN unification 2026-09-10).
# Single source of truth used by vsm_kernel, check.py and vsm_normalize.
# Union of the three historical sets (check.py, ~/packages canonical gate,
# vsm_kernel) so no shape falls through the cracks (false negatives) and
# every rule is covered by the test matrix in system/kernel/tests/.
# Theoretical limit (documented, not solvable statically): a real timestamp
# with normal shape (e.g. T16:22:24Z) is indistinguishable from a hardcoded
# one — the real net is parametric generation; detection is defense in depth.
# S5-ratified policy (backlog D-09, 2026-10-01): flag round seconds and
# placeholder DATES; a real hour-00 or minute-00 with non-round seconds is a
# genuine instant and passes. Detection catches hand-typed laziness (always
# :00 seconds), not time itself — generation (get_timestamp) is the real net.
HARDCODED_PATTERNS: list[tuple] = [
    (re.compile(r"T\d{2}:00:00Z"), "minute+second zero"),  # hardcoded-allow: detector guts
    (re.compile(r"T\d{2}:\d{2}:00Z"), "zero seconds (canonical gate)"),  # hardcoded-allow: detector guts/docs
    (re.compile(r"T12:00:00Z"), "noon placeholder"),  # hardcoded-allow: detector guts/docs
    (re.compile(r"2026-01-01T"), "year-start placeholder"),  # hardcoded-allow: detector guts/docs
    (re.compile(r"2025-01-01T"), "previous-year placeholder"),  # hardcoded-allow: detector guts/docs
    (re.compile(r"1970-01-01T"), "unix epoch"),  # hardcoded-allow: documented example
    (re.compile(r"2000-01-01T"), "y2k placeholder"),  # hardcoded-allow: detector guts/docs
    (re.compile(r"2099-"), "far-future placeholder"),  # hardcoded-allow: detector guts/docs
]


def is_hardcoded_timestamp(content: str) -> str | None:
    """Return the matching rule description, or None if clean."""
    for rx, desc in HARDCODED_PATTERNS:
        if rx.search(content):
            return desc
    return None


def get_version() -> str:
    """Canonical @vsm version: 1.2.1."""
    return VSM_VERSION


def get_timestamp(now: datetime | None = None) -> str:
    """Fresh UTC timestamp: the real time, never hardcoded.

    Real `now` is used. If it lands on a flagged shape (round second,
    placeholder date) it is nudged forward second by second until clean,
    capped at 59 iterations so a placeholder-date collision (e.g. a doc
    created on 2026-01-01) can never drift beyond +59s — past the cap the
    real time is returned as-is and detection fails loud downstream instead
    of the generator silently traveling to the future (D-09: the old open
    loop converged every 00:00-00:59Z instant to 01:01:01Z).
    """
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    for _ in range(59):
        s = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        if is_hardcoded_timestamp(s) is None:
            return s
        ts = ts + timedelta(seconds=1)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    hit = is_hardcoded_timestamp(content)
    if hit:
        errors.append(f"HARDCODED TIMESTAMP: {hit}")
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
