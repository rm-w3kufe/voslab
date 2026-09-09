#!/usr/bin/env python3
"""Make a verification claim executable, or refuse it.

WHY THIS EXISTS
---------------
R4 says "a claim of success is not evidence of success; require an independent
check." It was recorded 2026-08-03 and has no gate. Every other load-bearing
rule in this repo does: R9 -> verify_boot_primer, D7 -> symbol_table --d7,
grammar -> vsl_parser --strict, R15 -> envelope check. R4 was the one rule
enforced by intention alone, and on 2026-08-10 it failed five times in one
session, once by committing a live credential while asserting that a gate
prevented exactly that.

R4.1, 2026-08-11: the CLAIM_WORDS trigger has its own loophole -- the SAME
session that built this gate tripped it twice, reworded the commit message
to drop the trigger word, and committed anyway, still without citing a
check. Wording is not a security boundary. Separately, rmw3 named a second,
older failure mode: work dispatched to another agent ([S], DS) gets closed
as done/closed on the strength of that agent's own report, with nothing
structural requiring the closer to have independently re-run anything --
"the hole we've fallen into since the beginning of the work." So this gate
now fires on a SECOND, structural condition, independent of the message's
wording: the staged diff moves a task's status to done/closed for a task
whose agent/owner field marks it [S]-dispatched. See
_dispatched_task_closures() below. Both conditions share one requirement
(name real checks) and one escape hatch (none -- if you cannot make the
claim executable, do not make it, and do not close the task instead).

THE MECHANISM
-------------
Every one of those failures measured a PROXY for the claim instead of the
claim. A proxy has a detectable signature: it satisfies the positive assertion
AND its own negative control, because it does not discriminate.

    grep -qs "$TOK" ...      TOK empty  -> still matches
    git ls-files <file>      commit blocked -> file still listed
    ✓-printing size check    bc missing -> still prints ✓
    grep | head -8           pattern present -> still empty

So a check is only accepted here if it declares BOTH:

    expect_pass : the state that must hold
    expect_fail : a deliberately-false variant that MUST NOT hold

If expect_fail passes, the check is measuring something that cannot tell true
from false, and the runner rejects it as INVALID — not as failing. That is the
distinction that matters: a proxy is not a wrong answer, it is a non-answer.

CONTRACT
--------
A check is an executable under checks/ that responds to one argument:

    ./checks/<id>  pass     exit 0 if the claimed state holds
    ./checks/<id>  fail     exit 0 if the deliberately-false variant holds
                            (the runner REQUIRES this to exit non-zero)

Usage:
    python3 scripts/vsl/verify_claim.py <id> [<id>...]   # run named checks
    python3 scripts/vsl/verify_claim.py --all
    python3 scripts/vsl/verify_claim.py --trailers <file>  # for the git hook
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECKS = ROOT / "checks"
CLAIM_WORDS = ("verified", "verificado", "confirmed", "confirmado",
               "measured", "medido", "proven", "probado")

# R4.1: a task closing as done/closed whose agent/owner marks it [S]-dispatched.
# Deliberately a text-level heuristic over the diff HUNK, not a TASKS.vsm
# parse -- this runs at every commit touching TASKS.vsm, and a full parse
# (the vslline/tasks_provider machinery) is the wrong tool for "does this
# hunk smell like closing dispatched work", the same way grep, not a
# compiler, is the right tool for a pre-commit lint. False negatives (a
# closure this misses) are the accepted failure mode; a false positive here
# only costs a Verified-By line, never blocks something that shouldn't be.
#
# 2026-08-11 validation (docs/deploy/2026-08-11_ds_dispatch_r4_1_dispatch_
# closure_gate_validation.vsm) found real live-text evasions, fixed here:
#   - agent=[H+S] (real task A0-MODEL-REACTIVATE) -- bracket group containing
#     S, not just a bare S
#   - agent = "ds-s1" / agent: "ds" (real form-B/discovery blocks) -- quoted
#     and colon forms, hyphenated ds-s1
#   - owner=[S] unquoted (natural, previously required a quote)
#   - status: complete -- a real token_done synonym per the vocabulary census
#     (docs/deploy/2026-08-10_ds_task_status_vocabulary_census.vsm)
# Residual, accepted: a form-B task whose [S] owner line is >8 lines from its
# status line (4 of 17 real dispatched form-B tasks) still evades the hunk
# window; a full block parse is out of scope for a git-hook lint by design.
# CLOSED 2026-08-19 (R4-1-RESIDUAL-FAR-OWNER-EVASION): the detector now ALSO
# parses the FULL task block in TASKS.vsm for the owner when a hunk closes a
# status — the -U8 context window no longer gates correctness. The block
# parse is O(block) on the changed tasks only (the hunk names them), so the
# hook cost stays flat.
_STATUS_CLOSE_RE = re.compile(r'status\s*[:=]\s*"?\b(done|closed|complete)\b', re.I)
_DISPATCH_OWNER_RE = re.compile(
    r'(agent\s*[:=]\s*"?\[[^\]]*S[^\]]*\]"?)|'      # agent=[S] / [H+S] / "[S]" / "[H+S]"
    r'(agent\s*[:=]\s*"[^"]*\[S\])|'                 # agent = "…[S]…"
    r'(owner\s*[:=]\s*"[^"]*\[S\])|'                 # owner = "…[S]…"
    r'(owner\s*[:=]\s*"?\[[^\]]*S[^\]]*\]"?)|'       # owner=[S] / owner = "[H+S]"
    r'(agent\s*[:=]\s*"?ds(-s1)?"?\b)',             # agent=ds / agent: "ds" / agent = "ds-s1"
    re.I)
_TASK_NAME_RE = re.compile(r'\btask\(\s*"?([A-Z0-9][A-Z0-9_.-]*)', re.I)


def _task_block_owner(task_name: str, tasks_text: str) -> bool:
    """True if the FULL block of `task(<name>)` in `tasks_text` declares a
    [S]-dispatched owner. This is the R4-1 residual fix: the hunk context
    (-U8) cannot see an owner >8 lines below the status, but the block can.
    The block is located by the task( line and ends at the next `task(`
    line or an unbalanced closing brace — same boundaries the archive
    extractor uses."""
    m = re.search(rf'\btask\(\s*"?{re.escape(task_name)}"?\s*[):]', tasks_text)
    if not m:
        # task name may appear with a suffix/paren difference — try a looser
        # match on the exact token at a task( boundary
        m = re.search(rf'\btask\([^)]*?\b{re.escape(task_name)}\b', tasks_text)
    if not m:
        return False
    start = m.start()
    # block end: next task( line at column 0 OR EOF — tasks are top-level
    nxt = re.search(r'\n\s*task\(', tasks_text[start + len(m.group(0)):])
    end = start + len(m.group(0)) + (nxt.start() if nxt else 3000)
    block = tasks_text[start:end]
    return bool(_DISPATCH_OWNER_RE.search(block))


def _dispatched_task_closures(diff_text: str, tasks_text: str = "") -> list[str]:
    """Hunks in a TASKS.vsm diff where an ADDED line moves status to
    done/closed AND the task's owner is a [S]-dispatched agent. Returns a
    short label per hit, for the error message -- empty if none found.

    Owner detection: (1) the hunk itself (context included, so the agent=
    line doesn't have to itself be a +line); (2) NEW — the FULL task block
    in TASKS.vsm (R4-1-RESIDUAL-FAR-OWNER-EVASION, 2026-08-19): an owner
    >8 lines below the status evades the -U8 hunk window but not the block
    parse. `tasks_text` is the current TASKS.vsm content; the block lookup
    only fires for tasks the hunk actually closes, so the hook stays flat.

    Splits on `@@ ` whether or not a file-header preamble precedes it — real
    `git diff` output has one (diff --git/index/---/+++ lines); a bare hunk
    (this module's own test fixtures, or a diff fed in some other way) does
    not. `[1:]`-style "always skip the first chunk" silently discarded the
    only hunk in the no-preamble case — caught by this module's own
    checks/r4-1-dispatch-gate-valid pass-mode fixture before it ever reached
    a real commit."""
    hits: list[str] = []
    for hunk in re.split(r'(?:^|\n)@@ ', diff_text):
        if not hunk.strip():
            continue
        added = "\n".join(l[1:] for l in hunk.splitlines()
                           if l.startswith("+") and not l.startswith("+++"))
        if not _STATUS_CLOSE_RE.search(added):
            continue
        owner_in_hunk = bool(_DISPATCH_OWNER_RE.search(hunk))
        # NEW (R4-1 fix): owner may live in the full block, not the hunk
        owner_in_block = False
        if not owner_in_hunk and tasks_text:
            for tm in _TASK_NAME_RE.finditer(hunk):
                if _task_block_owner(tm.group(1), tasks_text):
                    owner_in_block = True
                    break
        if owner_in_hunk or owner_in_block:
            first_line = hunk.splitlines()[0] if hunk.splitlines() else "?"
            hits.append(first_line.split("@@")[0].strip()[:70] or "?")
    return hits


def _tasks_text() -> str:
    """Current TASKS.vsm content (working copy) — used by the R4-1 residual
    fix to parse the FULL block of a task a hunk closes, so an owner >8
    lines below the status is still seen (R4-1-RESIDUAL-FAR-OWNER-EVASION,
    2026-08-19)."""
    try:
        return (ROOT / "TASKS.vsm").read_text(encoding="utf-8")
    except Exception:
        return ""


def _staged_tasks_diff() -> str:
    try:
        p = subprocess.run(
            ["git", "diff", "--cached", "-U8", "--", "TASKS.vsm"],
            capture_output=True, text=True, timeout=30, cwd=ROOT)
        return p.stdout
    except Exception:
        return ""   # fail open on the DETECTION step -- never block a
                     # commit because git itself misbehaved; the existing
                     # CLAIM_WORDS path still catches wording-based claims


def run(check: Path, mode: str) -> tuple[int, str]:
    try:
        p = subprocess.run([str(check), mode], capture_output=True, text=True,
                           timeout=180, cwd=ROOT)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def verify(check: Path) -> bool:
    """A check is VALID only if pass passes and fail fails."""
    rc_pass, out_pass = run(check, "pass")
    rc_fail, out_fail = run(check, "fail")

    if rc_fail == 0:
        print(f"  ✗ INVALID  {check.name}")
        print(f"      its negative control PASSED — this check cannot tell true")
        print(f"      from false, so its positive result means nothing.")
        if out_fail:
            print(f"      fail-mode said: {out_fail.splitlines()[0][:90]}")
        return False
    if rc_pass != 0:
        print(f"  ✗ FAIL     {check.name}  (rc={rc_pass})")
        for l in out_pass.splitlines()[:3]:
            print(f"      {l[:96]}")
        return False
    print(f"  ✓ {check.name}"
          + (f"  — {out_pass.splitlines()[0][:70]}" if out_pass else ""))
    return True


def collect(ids: list[str]) -> list[Path]:
    out = []
    for i in ids:
        # sub-repo checks (R13 child): a check living under child/checks/ is
        # cited as child/checks/<id>; resolve ROOT-relative without the
        # leading checks/ prefix. Plain ids resolve under checks/.
        if i.startswith("child/checks/"):
            p = ROOT / i
        else:
            p = CHECKS / i
        if not p.exists():
            print(f"  ✗ MISSING  checks/{i} — a claim naming a check that does "
                  f"not exist is not a verified claim", file=sys.stderr)
            out.append(None)
        else:
            out.append(p)
    return out


def from_trailers(msg_file: str) -> int:
    """Git hook mode. If the message CLAIMS verification, OR the staged diff
    closes a [S]-dispatched task as done/closed, evidence is required — named
    checks that run clean. Prose is not evidence, and neither is "DS said it
    passed" — that is the whole point of R4(.1), and this is where it stops
    being advice."""
    msg = Path(msg_file).read_text(encoding="utf-8", errors="replace")
    body = "\n".join(l for l in msg.splitlines() if not l.startswith("#"))
    claims = [w for w in CLAIM_WORDS if w in body.lower()]
    trailers = [l.split(":", 1)[1] for l in body.splitlines()
                if l.lower().startswith("verified-by:")]
    ids = [i.strip() for t in trailers for i in t.split(",") if i.strip()]
    closures = _dispatched_task_closures(_staged_tasks_diff(),
                                         tasks_text=_tasks_text())

    if not claims and not closures:
        return 0
    if not ids:
        reasons = []
        if claims:
            reasons.append(f"claims verification "
                            f"({', '.join(sorted(set(claims))[:3])})")
        if closures:
            reasons.append(f"closes {len(closures)} [S]-dispatched task(s) "
                            f"as done/closed ({closures[0]}"
                            f"{', …' if len(closures) > 1 else ''})")
        print(f"\n❌ R4.1 gate: this commit {' and '.join(reasons)} "
              f"but names no check.", file=sys.stderr)
        print("   Add:  Verified-By: <check-id>[, <check-id>]", file=sys.stderr)
        print("   and put the check under checks/ with a negative control.",
              file=sys.stderr)
        if closures:
            print("   Closing dispatched work on the report alone is exactly"
                  " what R4.1 exists to stop — re-run something yourself.",
                  file=sys.stderr)
        print("   If the claim cannot be made executable, do not make it.",
              file=sys.stderr)
        return 1

    why = []
    if claims:
        why.append("message claims verification")
    if closures:
        why.append(f"{len(closures)} dispatched-task closure(s)")
    print(f"  R4.1 gate: {' + '.join(why)} — running {len(ids)} check(s)")
    checks = collect(ids)
    if any(c is None for c in checks):
        return 1
    ok = all(verify(c) for c in checks)
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "--trailers":
        return from_trailers(args[1])
    if args[0] == "--all":
        found = sorted(p for p in CHECKS.iterdir()
                       if p.is_file() and not p.name.startswith(".")
                       and p.name != "README.md") if CHECKS.exists() else []
        if not found:
            print("  no checks registered")
            return 0
        return 0 if all(verify(c) for c in found) else 1
    checks = collect(args)
    if any(c is None for c in checks):
        return 1
    return 0 if all(verify(c) for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
