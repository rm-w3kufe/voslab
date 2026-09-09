#!/usr/bin/env python3
"""vsm_normalize.py — Signature-only normalizer for .vsm documents.

Design: docs/plans/write_hook_autofix.vsm (S5-approved advisory phase).

Shows (dry-run, default) or applies (--apply) repairs LIMITED to signature
lines. Body lines are NEVER touched. --apply refuses unless EVERY changed
line is a signature line (header / @vsm / footer) and header/footer names
match. Missing footer or name mismatch = report only, exit 2.

Repairs:
  1. version -> vsm-1.2.1 (header) and @vsm 1.2.1
  2. timestamp -> fresh get_timestamp() (never hardcoded shapes)
  3. footer -> short form ⟦ /name ⟧ (medium/full footers only; the header
     name is authoritative — a mismatched name is reported, not renamed)

Usage:
  vsm_normalize.py <file.vsm>            # dry-run: unified diff, exit 0
  vsm_normalize.py --apply <file.vsm>    # apply signature-only fix

Exit codes:
  0 — clean, or dry-run diff printed (advisory gate: never blocks)
  1 — unreadable file / usage error
  2 — repairs needed but --apply refused (non-signature changes required)
"""
from __future__ import annotations

import difflib
import importlib.util
import re
import sys
from pathlib import Path

# ─── Load the parametric kernel (vOSlab copy, explicit path) ────────────────
_KERNEL = Path(__file__).resolve().parents[3] / "packages" / "framework" \
    / "vos_kernel" / "utils" / "vsm_kernel.py"


def _load_kernel():
    try:
        from vos_kernel.utils.vsm_kernel import (  # type: ignore
            VSM_TAG, VSM_VERSION, get_timestamp,
        )
        return VSM_TAG, VSM_VERSION, get_timestamp
    except ImportError:
        spec = importlib.util.spec_from_file_location("vsmk", str(_KERNEL))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.VSM_TAG, mod.VSM_VERSION, mod.get_timestamp


VSM_TAG, VSM_VERSION, get_timestamp = _load_kernel()

HEADER_RE = re.compile(
    r"^(?P<pre>.*⟦\s*)(?P<name>\w+)(\s*\|\s*)(?P<type>\w[\w-]*)"
    r"(\s*\|\s*)(?P<ver>vsm-[\d.]+)(\s*\|\s*)(?P<ts>\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}Z)(\s*⟧.*)$"
)
VSM_DECL_RE = re.compile(r"^(\s*@vsm\s+)([\d.]+)(\s*)$")
FOOTER_FULL_RE = re.compile(
    r"^(?P<pre>.*⟦\s*/)(?P<name>\w+)(\s*\|\s*\w[\w-]*\s*\|\s*)"
    r"(?P<ver>vsm-[\d.]+)(\s*\|\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    r"(\s*⟧.*)$"
)
FOOTER_MED_RE = re.compile(
    r"^(?P<pre>.*⟦\s*/)(?P<name>\w+)(\s*\|\s*)(?P<ver>vsm-[\d.]+)"
    r"(\s*\|\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)(\s*⟧.*)$"
)
FOOTER_SHORT_RE = re.compile(r"⟦\s*/(\w+)\s*⟧")


def normalize_lines(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (fixed_lines, changed_kinds, problems).

    changed_kinds entries: 'header' | 'vsm-decl' | 'footer'.
    problems: human-readable issues found but NOT auto-fixed.
    """
    fixed = list(lines)
    changed: list[str] = []
    problems: list[str] = []
    header_name: str | None = None
    fresh_ts = get_timestamp()

    for i, line in enumerate(fixed):
        m = HEADER_RE.match(line)
        if m and header_name is None:
            header_name = m.group("name")
            new = (
                f"{m.group('pre')}{m.group('name')} | {m.group('type')} | "
                f"{VSM_TAG} | {fresh_ts} ⟧"
            )
            # preserve any trailing content after ⟧ (keep it simple: full-line)
            if new != line.rstrip("\n"):
                fixed[i] = new + ("\n" if line.endswith("\n") else "")
                changed.append("header")
            continue
        vm = VSM_DECL_RE.match(line.rstrip("\n"))
        if vm and vm.group(2) != VSM_VERSION:
            fixed[i] = f"{vm.group(1)}{VSM_VERSION}{vm.group(3)}" + (
                "\n" if line.endswith("\n") else "")
            changed.append("vsm-decl")

    # Footer pass (needs header name first)
    for i, line in enumerate(fixed):
        if FOOTER_FULL_RE.match(line) or FOOTER_MED_RE.match(line):
            m = FOOTER_FULL_RE.match(line) or FOOTER_MED_RE.match(line)
            assert m is not None
            fname = m.group("name")
            if header_name is None:
                problems.append("footer present but no header found")
                continue
            if fname != header_name:
                problems.append(
                    f"header/footer name mismatch: {header_name} != {fname} "
                    "(not renamed — fix by hand)"
                )
                continue
            short = f"⟦ /{header_name} ⟧"
            if line.strip() != short:
                fixed[i] = short + ("\n" if line.endswith("\n") else "")
                changed.append("footer")
        elif FOOTER_SHORT_RE.search(line) and header_name is not None:
            m = FOOTER_SHORT_RE.search(line)
            assert m is not None
            if m.group(1) != header_name:
                problems.append(
                    f"header/footer name mismatch: {header_name} != "
                    f"{m.group(1)} (not renamed — fix by hand)"
                )

    if header_name is not None and not any(
        FOOTER_SHORT_RE.search(l) or FOOTER_FULL_RE.match(l)
        or FOOTER_MED_RE.match(l) for l in fixed
    ):
        problems.append("missing footer (not appended — add ⟦ /%s ⟧ by hand)"
                        % header_name)

    return fixed, changed, problems


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if len(paths) != 1:
        print(__doc__.split("Usage:")[1].split("Exit codes:")[0].strip(),
              file=sys.stderr)
        return 1
    path = Path(paths[0])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"vsm_normalize: cannot read {path}: {e}", file=sys.stderr)
        return 1

    lines = text.splitlines(keepends=True)
    fixed, changed, problems = normalize_lines(lines)

    if not changed and not problems:
        return 0  # clean

    diff = "".join(difflib.unified_diff(
        lines, fixed,
        fromfile=f"{path} (actual)", tofile=f"{path} (normalized)",
    ))
    if diff:
        print(diff, end="" if diff.endswith("\n") else "\n")
    for p in problems:
        print(f"vsm_normalize: {p}", file=sys.stderr)

    if not apply:
        return 0  # dry-run is advisory: never blocks
    if problems or not changed:
        return 2  # needs human hands
    path.write_text("".join(fixed), encoding="utf-8")
    print(f"vsm_normalize: applied signature-only fix to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
