#!/usr/bin/env python3
"""verify_boot_ontology.py — coherence gate for the boot ontology (M2).

Checks the D_VERIFIER set (rules embedded below — the old design doc
docs/spec_revision/sandbox/boot_ontology_pattern.vsm was retired in the
system/ restructure) against the live tree and the boot manifest
(system/boot/boot_manifest.vsm, M1):

    (a) TYPE COHERENCE  — the boot order is defined ONCE. The current tree
        defines it 4× (D1: vsf-s3-planner.md, vsf-onboard-reminder.ts,
        scripts/vsf-onboard-reminder, CLAUDE.md). Every re-listing that does
        NOT cite the manifest is flagged (P5 cache rule). D2 (S3 prompt omits
        onboard.sh) surfaces as a divergent definition.
    (b) MECHANISM AUTHORITY — advisory mechanisms never veto. Any 'throw' in
        a plugin's tool.execute.before must be declared layer=gate in the
        manifest; an advisory (reminder/measure/check) plugin that throws is
        a violation.
    (c) REFERENCE RESOLUTION — every cited artifact/id exists. D3: the
        reminder points at CLAUDE.md (decoupled 2026-08-12). D4: the R15
        gate cites vsl_hard_rules_v1.R15 (retired; current = core_boot_
        primer.comms per RULES.md).
    (d) HASH CONSISTENCY — every file artifact in the manifest exists and
        its sha256[:16] matches the declared hash (extends the
        .primer_sources_manifest.json pattern).

ACCEPTANCE: when D1-D4 were open (M2), this verifier MUST FAIL (exit != 0)
on the CURRENT tree — that was the proof it detects them. After M4 (S3
prompt cites manifest) + M5 (CLAUDE.md cites manifest) + D3/D4 fixes, the
tree is REPAIRED: the verifier MUST PASS (exit 0) on the live tree, and the
fixtures in --self remain the proof it still detects the defect CLASSES.

Deterministic, stdlib-only. No LLM in this path (R10).

Usage:
    python3 scripts/vsl/verify_boot_ontology.py            # check (default)
    python3 scripts/vsl/verify_boot_ontology.py --json     # machine-readable
    python3 scripts/vsl/verify_boot_ontology.py --self     # unit checks a-d
                                                           # against fixtures

Exit codes: 0 = clean; 1 = VIOLATION; 2 = config error (no manifest).
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "system/boot/boot_manifest.vsm"  # post-migration (FND-BOOTOOLS-PATH-DRIFT-01)

# ── rule-id resolution map (RULES.md pointer table, PROTOCOL_VERSION 3) ──
# A plugin/prompt citing a v1 id fails resolution (D4). Current ids live in
# the canon blocks named by RULES.md.
CURRENT_RULE_IDS = {
    "R1": "hard_rules.R1_locality",
    "R4": "hard_rules.R4_verification",
    "R5": "hard_rules.R5_canon_over_recall",
    "R6": "hard_rules.R6_internal_first",
    "R7": "hard_rules.R7_state_db_wins",
    "R8": "regulation_layer.spof_pattern",
    "R9": "hard_rules.R9_no_silent_concession",
    "R10": "hard_rules.R10_llm_boundary",
    "R10.1": "hard_rules.R10_1_llm_tactics_not_enforcement",
    "R11": "hard_rules.R11_naming",
    "R13": "core_boot_primer.channels",
    "R15": "core_boot_primer.comms",
    "doc_sync": "hard_rules.doc_sync_practice",
}

# v1 namespaces that were retired in the 2026-08-03 compression / v3 move.
RETIRED_PREFIXES = ("vsl_hard_rules_v1.",)

# ── the boot-order phrase (D1 evidence: byte-identical re-listing) ──
BOOT_ORDER_MARKERS = [
    "all SIX boot docs",
    "all six boot docs",
    "dependency order: covenant",
    "covenant ≻ core_boot_primer",
]


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def load_manifest() -> dict | None:
    return load_manifest_from(str(MANIFEST))


def load_manifest_from(path: str | Path) -> dict | None:
    """Parse a manifest file (live or fixture) into {artifacts, text}."""
    p = Path(path)
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    artifacts = []
    for m in re.finditer(
        r'artifact\("([^"]+)",\s*layer=(\w+),\s*role=(\w+),\s*hash="([^"]+)"',
        txt,
    ):
        artifacts.append({
            "path": m.group(1),
            "layer": m.group(2),
            "role": m.group(3),
            "hash": m.group(4),
        })
    return {"artifacts": artifacts, "text": txt}


# ══════════════════════════════════════════════════════════════════════
# (a) TYPE COHERENCE — one definition of the boot order (P5 cache rule)
# ══════════════════════════════════════════════════════════════════════
def check_type_coherence(manifest_text: str, base: Path | None = None) -> list[str]:
    """The boot order must be declared ONCE. Every artifact that re-lists
    it WITHOUT citing the manifest is a violation (D1/D2)."""
    base = base or ROOT
    findings = []
    files = [
        base / ".opencode/agent/vsf-s3-planner.md",
        base / ".opencode/plugins/operational/vsf-onboard-reminder.ts",
        base / ".opencode/plugins/scripts/vsf-onboard-reminder",
        base / "CLAUDE.md",
    ]
    for f in files:
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        hits = [m for m in BOOT_ORDER_MARKERS if m in txt]
        if not hits:
            continue
        cites_manifest = ("boot_manifest" in txt) or ("boot/boot_manifest" in txt)
        if not cites_manifest:
            findings.append(
                f"INCOHERENT-DEF  {f.relative_to(base)} re-lists the boot "
                f"order ({', '.join(hits)}) WITHOUT citing boot_manifest.vsm "
                f"(P5 cache rule — boot order must be declared once)"
            )
    return findings


# ══════════════════════════════════════════════════════════════════════
# (b) MECHANISM AUTHORITY — advisory never vetoes
# ══════════════════════════════════════════════════════════════════════
def check_mechanism_authority(manifest_artifacts: list[dict],
                             base: Path | None = None) -> list[str]:
    """Any plugin with a throw in tool.execute.before must be declared
    layer=gate in the manifest. A declared advisory mechanism that throws
    is a violation."""
    base = base or ROOT
    findings = []
    for a in manifest_artifacts:
        p = base / a["path"]
        if not p.exists() or not str(p).endswith(".ts"):
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        # advisory mechanisms must never throw (D_VERIFIER check b)
        if a["layer"] != "gate" and re.search(r"throw\s+new\s+Error", txt):
            findings.append(
                f"UNAUTHORIZED-VETO  {a['path']} declared layer={a['layer']} "
                f"(advisory) but contains 'throw new Error' — advisory "
                f"mechanisms never veto; only declared S3 gates may block"
            )
        # declared gates MUST have a throw (they are the veto) — absence is
        # an inconsistency but NOT a D_VERIFIER violation (a gate that never
        # blocks is just a weak gate); skip.
    return findings


# ══════════════════════════════════════════════════════════════════════
# (c) REFERENCE RESOLUTION — every cited artifact/id exists (D3, D4)
# ══════════════════════════════════════════════════════════════════════
def check_reference_resolution(base: Path | None = None) -> list[str]:
    """Every rule-id citation resolves against RULES.md (current ids); every
    doc path citation exists. D3: CLAUDE.md pointer. D4: retired rule id."""
    base = base or ROOT
    findings = []

    # (c1) rule-id citations in plugins/prompts (D4)
    scan_files = [
        base / ".opencode/plugins/operational/vsf-onboard-reminder.ts",
        base / ".opencode/plugins/manual/vsf-agent-vsl-gate.ts",
        base / ".opencode/plugins/core/vsl-measure-before-write.ts",
        base / ".opencode/plugins/core/vsl-check-on-write.ts",
        base / ".opencode/agent/vsf-s3-planner.md",
        base / "CLAUDE.md",
    ]
    for f in scan_files:
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        # retired v1 ids anywhere in the text (D4) — the citation is often
        # wrapped as R15 (`vsl_hard_rules_v1.R15_cross_agent_vsl`), so the
        # retired-prefix match must be position-independent.
        for m in re.finditer(r"vsl_hard_rules_v1\.\w+", txt):
            findings.append(
                f"UNRESOLVED-ID  {f.relative_to(base)} cites retired "
                f"rule id '{m.group(0)}' — current R15 = core_boot_primer."
                f"comms (RULES.md PROTOCOL_VERSION 3)"
            )

    # (c2) CLAUDE.md as boot-manifest pointer (D3)
    for f in [base / ".opencode/plugins/operational/vsf-onboard-reminder.ts",
              base / ".opencode/plugins/scripts/vsf-onboard-reminder"]:
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        if "BOOT MANIFEST in CLAUDE.md" in txt or "CLAUDE.md carries the BOOT MANIFEST" in txt:
            findings.append(
                f"UNRESOLVED-REF  {f.relative_to(base)} points the boot "
                f"manifest at CLAUDE.md — decoupled from the OpenCode boot "
                f"since 2026-08-12 (OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1); "
                f"expected boot_manifest.vsm"
            )

    # (c3) every file artifact in the manifest exists (D3 class, general)
    # handled in check (d) — existence + hash in one pass.
    return findings


# ══════════════════════════════════════════════════════════════════════
# (d) HASH CONSISTENCY — manifest artifacts exist + sha256 matches
# ══════════════════════════════════════════════════════════════════════
def check_hash_consistency(manifest_artifacts: list[dict],
                          base: Path | None = None) -> list[str]:
    base = base or ROOT
    findings = []
    for a in manifest_artifacts:
        h = a["hash"]
        if h in ("SELF",) or h.startswith("child-repo") or h.startswith("runtime"):
            continue
        p = base / a["path"]
        if not p.exists():
            findings.append(f"MISSING  {a['path']} (declared in manifest)")
            continue
        real = sha16(p)
        if real != h:
            findings.append(
                f"STALE-HASH  {a['path']} manifest {h} ≠ disk {real}"
            )
    return findings


# ══════════════════════════════════════════════════════════════════════
# (e) MCP LIVENESS — declared mcp artifacts must be reachable services
# ══════════════════════════════════════════════════════════════════════
# The manifest declares state-canon / state-canon-infra as layer=mcp,
# role=serves, hash="runtime service (no file)". check_hash_consistency
# skips them (they are not files) — which is correct, but means a DEAD MCP
# passes every existing check. The boot load test (G_BOOT_CONSOLIDATION #8)
# requires the agent to boot against live instruments; a declared-but-dead
# server is a boot failure with green checks. This check closes that hole:
# for every artifact with layer=mcp, the process serving it must be alive.
#
# The two state servers share mcp_server.py — the artifact name is NOT in
# the cmdline (a bare substring match on "state-canon" false-positives off
# the shared state-canon-mcp/ directory). What distinguishes them is the
# --instance: the manifest's owner field names the domains each serves
# (tasks/focus/journal vs services/lxcs/chains/topology), which map to the
# concrete instance files below.
_MCP_INSTANCE = {
    "state-canon": "voslab_instance.py",  # live instance (2026-09-30): focus+journal (was tasks_provider)
    "state-canon-infra": "ssh_sqlite_ops.py",
}

def check_mcp_liveness(manifest_artifacts: list[dict],
                       base: Path | None = None) -> list[str]:
    """Every layer=mcp artifact must be a RUNNING service on this host.

    Detection: pgrep the shared mcp_server.py and match the artifact's
    domain instance (tasks_provider.py / ssh_sqlite_ops.py). Unknown mcp
    artifacts fall back to a cmdline substring match on the artifact name.
    """
    base = base or ROOT
    findings = []
    procs = None
    for a in manifest_artifacts:
        if a.get("layer") != "mcp":
            continue
        # the artifact path is the manifest author's name for the server
        name = a["path"]
        if procs is None:
            import subprocess
            try:
                r = subprocess.run(["pgrep", "-af", "mcp_server.py"],
                                   capture_output=True, text=True, timeout=10)
                procs = r.stdout.splitlines() if r.returncode == 0 else []
            except Exception:
                procs = []
        # known servers: match by the instance file that serves their domain
        inst = _MCP_INSTANCE.get(name)
        needle = inst if inst else name
        if not any(needle in cmd for cmd in procs):
            findings.append(
                f"MCP-DEAD  {name} (declared layer=mcp, role=serves, but no"
                f" mcp_server.py --instance {needle} process is running)")
    return findings


# ══════════════════════════════════════════════════════════════════════
# selftest — unit checks a-e against fixtures (must FAIL the current tree)
# ══════════════════════════════════════════════════════════════════════
def _make_fixture() -> Path:
    """A minimal broken boot tree in tmpdir: re-lists the order without the
    manifest (a), an advisory plugin that throws (b), a retired rule id +
    CLAUDE.md pointer (c), and a missing artifact + stale hash (d)."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="boot-ont-fixture-"))
    (d / ".opencode" / "agent").mkdir(parents=True, exist_ok=True)
    (d / ".opencode" / "plugins" / "scripts").mkdir(parents=True, exist_ok=True)
    (d / ".opencode" / "plugins").mkdir(parents=True, exist_ok=True)

    # (a) incoherent definition: re-lists order, no manifest citation
    (d / ".opencode" / "agent" / "vsf-s3-planner.md").write_text(
        "boot order: all SIX boot docs in dependency order: covenant\n",
        encoding="utf-8")
    # (a2) a file that DOES cite the manifest — must NOT be flagged
    (d / ".opencode" / "plugins" / "vsf-onboard-reminder.ts").write_text(
        "// all six boot docs — see boot_manifest.vsm\n",
        encoding="utf-8")

    # (b) advisory plugin with a throw (declared layer=reminder below) —
    #     written at the path check_mechanism_authority actually scans
    #     (2026-09-30 fix: fixture lived at plugins/ root while the scan
    #     list uses core/, so the fixture silently never flagged).
    (d / ".opencode" / "plugins" / "core").mkdir(parents=True, exist_ok=True)
    (d / ".opencode" / "plugins" / "core" / "vsl-measure-before-write.ts").write_text(
        "throw new Error('measure veto')\n", encoding="utf-8")

    # (c) retired rule id + CLAUDE.md pointer — same lesson: the D4 scan
    #     list expects plugins/manual/vsf-agent-vsl-gate.ts.
    (d / ".opencode" / "plugins" / "manual").mkdir(parents=True, exist_ok=True)
    (d / ".opencode" / "plugins" / "manual" / "vsf-agent-vsl-gate.ts").write_text(
        "R15 (`vsl_hard_rules_v1.R15_cross_agent_vsl`)\n", encoding="utf-8")
    (d / "CLAUDE.md").write_text("BOOT MANIFEST in CLAUDE.md\n",
                                 encoding="utf-8")
    (d / ".opencode" / "plugins" / "scripts" / "vsf-onboard-reminder").write_text(
        "// BOOT MANIFEST in CLAUDE.md — stale pointer\n", encoding="utf-8")

    # (d) manifest: missing artifact + stale hash
    (d / "boot_manifest.vsm").write_text(
        "@vsm 1.0\nmanifest(\"boot\") {\n"
        "  layer(L_CANON) {\n"
        "    entries: [\n"
        "      artifact(\"does/not/exist.vsm\", layer=canon, role=declares,"
        "               hash=\"deadbeef00000000\", owner=\"fixture\") {},\n"
        "    ],\n"
        "  }\n"
        "}\n",
        encoding="utf-8")

    # (e) mcp artifact declared but its server process is NOT running
    (d / "boot_manifest_mcp.vsm").write_text(
        "@vsm 1.0\nmanifest(\"boot\") {\n"
        "  layer(L_MCP) {\n"
        "    entries: [\n"
        "      artifact(\"fixture-mcp-nowhere\", layer=mcp, role=serves,"
        "               hash=\"runtime service (no file)\","
        "               owner=\"fixture\") {},\n"
        "    ],\n"
        "  }\n"
        "}\n",
        encoding="utf-8")
    return d


def selftest() -> int:
    """Run each check against (i) fixture trees it must flag, (ii) the LIVE
    tree where D1-D4 are confirmed. This is the acceptance proof: the
    verifier detects what it claims to detect — and does not flag a tree
    that cites the manifest."""
    import shutil
    ok = True

    # ── (i) fixtures: each check must flag its class of defect ──
    fx = _make_fixture()
    try:
        # (a) fixture flags the s3 prompt, NOT the manifest-citing reminder
        a_fx = check_type_coherence("", base=fx)
        flagged_s3 = any("vsf-s3-planner.md" in x for x in a_fx)
        falsely_flagged = any("vsf-onboard-reminder.ts" in x for x in a_fx)
        print(f"  (a) fixture: {len(a_fx)} finding(s)"
              + (f" — {a_fx[0][:60]}" if a_fx else ""))
        if not flagged_s3:
            print("    ✗ fixture should flag the S3-prompt re-listing")
            ok = False
        if falsely_flagged:
            print("    ✗ fixture flagged the manifest-citing reminder (false +)")
            ok = False

        # (b) fixture: advisory plugin with throw must be flagged
        arts_fx = [{"path": ".opencode/plugins/core/vsl-measure-before-write.ts",
                    "layer": "reminder", "role": "advisory", "hash": "x"},
                   {"path": ".opencode/plugins/manual/vsf-agent-vsl-gate.ts",
                    "layer": "gate", "role": "veto", "hash": "x"}]
        b_fx = check_mechanism_authority(arts_fx, base=fx)
        print(f"  (b) fixture: {len(b_fx)} finding(s)"
              + (f" — {b_fx[0][:60]}" if b_fx else ""))
        if not any("UNAUTHORIZED-VETO" in x for x in b_fx):
            print("    ✗ fixture advisory-throw should be flagged")
            ok = False
        if any("vsf-agent-vsl-gate" in x and "advisory" in x for x in b_fx):
            print("    ✗ fixture gate wrongly flagged as advisory")
            ok = False

        # (c) fixture: retired id + CLAUDE.md pointer
        c_fx = check_reference_resolution(base=fx)
        print(f"  (c) fixture: {len(c_fx)} finding(s)")
        for x in c_fx:
            print(f"      {x[:90]}")
        if not any("vsl_hard_rules_v1" in x for x in c_fx):
            print("    ✗ fixture retired-id should be flagged (D4)")
            ok = False
        if not any("CLAUDE.md" in x for x in c_fx):
            print("    ✗ fixture CLAUDE.md pointer should be flagged (D3)")
            ok = False

        # (d) fixture: missing artifact must be flagged
        mfx = load_manifest_from(str(fx / "boot_manifest.vsm"))
        d_fx = check_hash_consistency(mfx["artifacts"], base=fx)
        print(f"  (d) fixture: {len(d_fx)} finding(s)"
              + (f" — {d_fx[0][:60]}" if d_fx else ""))
        if not any("MISSING" in x for x in d_fx):
            print("    ✗ fixture missing artifact should be flagged")
            ok = False

        # (e) fixture: declared mcp with no serving process must be flagged
        mefx = load_manifest_from(str(fx / "boot_manifest_mcp.vsm"))
        e_fx = check_mcp_liveness(mefx["artifacts"], base=fx)
        print(f"  (e) fixture: {len(e_fx)} finding(s)"
              + (f" — {e_fx[0][:60]}" if e_fx else ""))
        if not any("MCP-DEAD" in x for x in e_fx):
            print("    ✗ fixture declared-but-dead mcp should be flagged")
            ok = False
    finally:
        shutil.rmtree(fx, ignore_errors=True)

    # ── (ii) live tree: REPAIRED after M4+M5 — must be clean ──
    manifest = load_manifest()
    if manifest is None:
        print("✗ SELFTEST: no manifest — config error")
        return 1
    arts = manifest["artifacts"]

    # (a) live-tree must be clean: S3 prompt (M4) + CLAUDE.md (M5) now
    #     cite boot_manifest.vsm — no re-listing without the manifest.
    a = check_type_coherence(manifest["text"])
    print(f"  (a) live-tree: {len(a)} finding(s)"
          + (f" — {a[0][:70]}" if a else ""))
    if a:
        print("    ✗ expected 0 incoherent definitions on the REPAIRED tree "
              "(M4 prompt + M5 CLAUDE.md cite the manifest)")
        ok = False

    # (b) gate.ts is declared layer=gate; reminder/measure/check advisory
    #     must NOT throw. Current tree: gate.ts is the only throw.
    b = check_mechanism_authority(arts)
    print(f"  (b) live-tree: {len(b)} finding(s)")
    # the current tree has no advisory throw — this check PASSES today; it is
    # the guard for FUTURE drift. No finding is the expected outcome here.
    if b:
        ok = False  # a finding means an advisory plugin throws — bad

    # (c) live-tree must be clean: D3 (CLAUDE.md pointer) and D4 (retired
    #     rule id) were fixed by the parent; any finding is future drift.
    c = check_reference_resolution()
    print(f"  (c) live-tree: {len(c)} finding(s)")
    for x in c:
        print(f"      {x[:100]}")
    d3 = any("CLAUDE.md" in x for x in c)
    d4 = any("vsl_hard_rules_v1" in x for x in c)
    if d3:
        print("    ✗ expected D3 (CLAUDE.md pointer) FIXED on the live tree")
        ok = False
    if d4:
        print("    ✗ expected D4 (retired rule id) FIXED on the live tree")
        ok = False

    # (d) manifest hashes must match the live tree (M1 verified 32/32)
    d = check_hash_consistency(arts)
    print(f"  (d) live-tree: {len(d)} finding(s)")
    if d:
        print(f"    ✗ expected 0 hash mismatches (M1 verified 32/32)")
        ok = False

    # (e) declared MCPs must be live services (state-canon, state-canon-infra)
    e = check_mcp_liveness(arts)
    print(f"  (e) live-tree: {len(e)} finding(s)"
          + (f" — {e[0][:70]}" if e else ""))
    if e:
        print("    ✗ expected 0 dead MCPs — the manifest declares servers")
        ok = False

    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--self" in args:
        return selftest()

    manifest_path = MANIFEST
    if "--manifest" in args:  # gate negative-control: verify a fixture copy
        i = args.index("--manifest")
        if i + 1 >= len(args):
            print("✗ --manifest requires a path", file=sys.stderr)
            return 2
        manifest_path = Path(args[i + 1])
    manifest = load_manifest_from(manifest_path)
    if manifest is None:
        print("✗ [boot-ontology] no manifest at "
              "system/boot/boot_manifest.vsm — "
              "run M1 first", file=sys.stderr)
        return 2

    arts = manifest["artifacts"]
    findings = []
    findings += check_type_coherence(manifest["text"])
    findings += check_mechanism_authority(arts)
    findings += check_reference_resolution()
    findings += check_hash_consistency(arts)
    findings += check_mcp_liveness(arts)

    if not findings:
        print("✓ [boot-ontology] clean: 0 violations "
              "(type-coherence, authority, references, hashes, mcp-liveness)")
        return 0

    print(f"✗ [boot-ontology] {len(findings)} violation(s):")
    for f in findings:
        print(f"    {f}")
    if "--json" in args:
        print(json.dumps({"violations": findings, "count": len(findings)}))

    return 1


if __name__ == "__main__":
    sys.exit(main())