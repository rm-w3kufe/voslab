"""test_no_shell_exec.py — NEXT-3 thin slice: no shell spawns in plugins.

Only execFile/execFileSync may be imported from node:child_process
(shell-string exec is a command-injection shape; the 2026-08 sweep
fixed it once, this test keeps it fixed). Pure file reads — hermetic.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = ROOT / ".opencode"

ALLOWED_CHILD_PROCESS_IMPORTS = {"execFile", "execFileSync"}


def _ts_files():
    return [p for p in PLUGINS.rglob("*.ts")
            if "node_modules" not in p.parts and "__pycache__" not in p.parts]


def test_only_execfile_imported():
    offenders = []
    for p in _ts_files():
        for i, line in enumerate(p.read_text(encoding="utf-8",
                                             errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith("//") or s.startswith("*"):
                continue
            if "node:child_process" in s and "import" in s:
                names = s.replace("{", " ").replace("}", " ").replace(",", " ")
                imported = {w for w in names.split()
                            if w not in ("import", "from",
                                         '"node:child_process"',
                                         "'node:child_process'")}
                bad = imported - ALLOWED_CHILD_PROCESS_IMPORTS
                if bad:
                    offenders.append(f"{p.relative_to(ROOT)}:{i}: {sorted(bad)}")
    assert offenders == [], f"shell-capable imports: {offenders}"


def test_no_shell_string_spawn():
    import re
    # execP(`...`) / exec(`...`) with a template literal = shell string.
    # execFile with a template first-arg is shell-free (no parsing), so
    # only bare exec/execSync names count.
    rx = re.compile(r"(?<![A-Za-z])exec(Sync)?\s*\(\s*`")
    offenders = []
    for p in _ts_files():
        for i, line in enumerate(p.read_text(encoding="utf-8",
                                             errors="replace").splitlines(), 1):
            s = line.strip()
            if s.startswith("//") or s.startswith("*"):
                continue
            if rx.search(line):
                offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert offenders == [], f"shell-string spawns: {offenders}"
