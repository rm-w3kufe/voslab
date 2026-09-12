#!/usr/bin/env python3
"""clone_preflight.py — read-only checker for a vOSlab scratch instance.

Usage:
    python3 scripts/ops/clone_preflight.py <clone-path> [--main PATH] [--json]

Verifies a filesystem clone created by S5 (kernel never writes outside
its own workspace, so S5 runs `git clone` in shell; this script only
READS the candidate and reports). Exit 0 = ready, 1 = blocking issues
(warnings never block).

Checks:
  1. clone is a git repo with shared ancestry to main
  2. no anchor file still points at MAIN (opencode.json, the two MCP
     bridges; docs/archive is exempt — frozen history)
  3. opencode.json absolute paths resolve inside CLONE or to shared
     infra (state-canon-mcp, ssh targets, /var/lib) — never into MAIN
  4. current_focus.json parses (reports active refs, if any)
  5. clone .git/info/exclude keeps scratch state local
     (focus, logs, trust, journal, rate files)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ANCHOR_FILES = [
    "opencode.json",
    ".opencode/mcp/parse_query_mcp.py",
    ".opencode/mcp/socratic_mcp_with_bridge.py",
]

EXCLUDE_WANT = [
    "current_focus.json",
    "logs/",
    ".trust_state.json",
    "state_journal.db",
    ".rate_limit",
]


def sh(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(list(args), capture_output=True, text=True,
                           timeout=30)
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return 99, str(e)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_json = "--json" in sys.argv[1:]
    main_root = Path(__file__).resolve().parents[2]
    if "--main" in sys.argv:
        try:
            main_root = Path(sys.argv[sys.argv.index("--main") + 1]).resolve()
        except Exception:
            pass
    if not args:
        print("usage: clone_preflight.py <clone-path> [--main PATH] [--json]",
              file=sys.stderr)
        return 2
    clone = Path(args[0]).resolve()

    issues: list[str] = []
    warnings: list[str] = []
    info: dict = {"clone": str(clone), "main": str(main_root)}

    if clone == main_root:
        issues.append("clone path equals main workspace (nothing to check)")
    if not (clone / ".git").exists():
        issues.append("not a git repo (no .git/)")
        return _report(info, issues, warnings, want_json)

    rc, head_c = sh("git", "-C", str(clone), "rev-parse", "HEAD")
    rc2, head_m = sh("git", "-C", str(main_root), "rev-parse", "HEAD")
    if rc or rc2:
        issues.append("cannot resolve HEAD in clone and main")
    else:
        info["clone_head"] = head_c[:12]
        info["main_head"] = head_m[:12]
        r1, _ = sh("git", "-C", str(main_root), "merge-base",
                   "--is-ancestor", head_c, head_m)
        r2, _ = sh("git", "-C", str(clone), "merge-base",
                   "--is-ancestor", head_m, head_c)
        if r1 != 0 and r2 != 0:
            issues.append("no shared ancestry between clone and main")
        elif r2 == 0 and r1 != 0:
            warnings.append("clone is ahead of main (scratch work present)")

    main_s = str(main_root)
    # Separator-aware: the scratch dir is usually MAIN + suffix
    # (vOSlab-scratch), so a naive substring hits every repointed
    # path. Only a MAIN occurrence NOT continued by [-/\w] counts.
    import re
    main_hit = re.compile(re.escape(main_s) + r"(?![-\w])")
    for rel in ANCHOR_FILES:
        p = clone / rel
        if not p.is_file():
            warnings.append(f"missing anchor file: {rel}")
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            issues.append(f"unreadable anchor file {rel}: {e}")
            continue
        if main_hit.search(text):
            issues.append(f"{rel} still points at MAIN ({main_s})")

    oc = clone / "opencode.json"
    if oc.is_file():
        try:
            cfg = json.loads(oc.read_text(encoding="utf-8"))
            blob = json.dumps(cfg)
            # crude absolute-path harvest: quoted strings starting with /
            import re as _re
            for path in set(_re.findall(r"\"(/[^\"\\]+)\"", blob)):
                if path.startswith(str(clone)):
                    continue
                if path.startswith("/home/rmw3/state-canon-mcp"):
                    continue
                if "@" in path or path.startswith("/var/lib"):
                    continue
                if path == main_s or path.startswith(main_s + "/"):
                    issues.append(f"opencode.json path leaks into MAIN: {path}")
                else:
                    warnings.append(f"opencode.json absolute path: {path}")
        except Exception as e:
            issues.append(f"opencode.json unparsable: {e}")

    focus = clone / "current_focus.json"
    if focus.is_file():
        try:
            data = json.loads(focus.read_text(encoding="utf-8"))
            act = [e.get("ref") for e in data
                   if isinstance(e, dict) and e.get("status") == "active"]
            info["focus_entries"] = len(data)
            info["focus_active"] = act
            if act:
                warnings.append(f"clone has active focus entries: {act}")
        except Exception as e:
            issues.append(f"current_focus.json unparsable: {e}")
    else:
        warnings.append("no current_focus.json in clone")

    excl = clone / ".git" / "info" / "exclude"
    try:
        ext = excl.read_text(encoding="utf-8") if excl.is_file() else ""
        for want in EXCLUDE_WANT:
            if want not in ext:
                warnings.append(f"clone .git/info/exclude lacks {want} "
                                f"(scratch state may leak into sync)")
    except OSError:
        warnings.append("cannot read clone .git/info/exclude")

    return _report(info, issues, warnings, want_json)


def _report(info: dict, issues: list, warnings: list, want_json: bool) -> int:
    if want_json:
        print(json.dumps({"info": info, "issues": issues,
                          "warnings": warnings}, indent=1))
    else:
        print(f"clone: {info.get('clone')}")
        print(f"main:  {info.get('main')}")
        for k in ("clone_head", "main_head", "focus_entries",
                  "focus_active"):
            if k in info:
                print(f"{k}: {info[k]}")
        for w in warnings:
            print(f"WARN: {w}")
        for i in issues:
            print(f"BLOCK: {i}")
        print("READY" if not issues else "NOT READY")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
