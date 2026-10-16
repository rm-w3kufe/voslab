#!/usr/bin/env python3
# design: docs/plans/system_projection_2026_10_14.vsm
# route: session.idle/derived-resync (plugin) + cli/manual
# (EV-R2/W1: auto-resync de derived blocks — el gate queda como verificador
#  post-hoc; el resync es la consecuencia mecanica de un cambio de fuente.)
"""derived_resync.py — auto-resync of derived blocks (P-EV-R2).

DERIVED = mechanical consequence of a source file; no judgment needed:

  boot-pins   sha256[:16] pins in system/boot/boot_manifest.vsm for the
              string-path artifacts (kernel .py, plugins .ts, ...) vs disk.
              The treadmill this kills: every kernel edit left
              boot-manifest-valid RED until a human re-pinned (live demo
              2026-10-15: rsi_cycle.py stale again hours after P-B re-pin,
              because P-EV-R4 edited it).

  scripts-manifests  regen via shared/update_scripts_manifest.py when the
              scripts/ tree fingerprint changed (paths+sizes — cheap,
              deterministic R10).

JUDGMENT blocks (tasks drift, projection census) are REPORTED only, never
auto-written — R9/R10: the agent decides, the machine does not concede.

Modes:
  (default)  check: report drift, exit 1 if any, write nothing
  --apply    rewrite boot pins + regen scripts manifests + refresh stamp
  --json     machine-readable report

Deterministic, stdlib-only, CWD-independent (R10, R1).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "system" / "boot" / "boot_manifest.vsm"
STAMP = ROOT / "state" / "derived_resync_stamp.json"
SCRIPTS_MANIFEST_TOOL = ROOT / "scripts" / "shared" / "update_scripts_manifest.py"

# P4 (policy R16 ratified 2026-10-16, lump P-R16-BACKFILL): instruments
# that (re)write derived state — DECLARATIVE registry (no resync logic
# change); writers verified by write-ops scan 2026-10-16.
DERIVED_STATE_WRITERS = (
    ("scripts/shared/update_scripts_manifest.py",
     "system/scripts_manifest/*.json — regen de manifests"),
    ("scripts/vsl/tools/health_scan.py",
     "state/health_history.jsonl — serie de salud (append)"),
    ("scripts/state/attestation/check_agent_log.py",
     "<log>/*.census_cache — caché de censo (tmp + os.replace)"),
    ("system/kernel/alerting.py",
     "state/rsi/alerts.jsonl + state/rsi/trace*.json (gitignored)"),
    ("scripts/vsl/tools/derived_resync.py",
     "state/derived_resync_stamp.json — stamp de corrida (self)"),
    ("scripts/state/canon/drift_inventory.py",
     "state/drift_inventory.json — inventario de drift medido"),
    ("scripts/vsl/tools/doc_manifest.py",
     "state/doc_manifest.jsonl — census derivado de docs (DIRTY_EXCLUDES)"),
    ("system/kernel/tree_trace_logger.py",
     "state/rsi/session_summary.json — resumen mecánico de sesión"),
    ("system/kernel/vosi.py",
     "state/faults/detected_faults.json — salida de probes de detección"),
    ("scripts/doc_tracking/verify_docs.py",
     "state/doc_tracking/review_queue.jsonl + orphans.jsonl — queue derivada de verificación"),
    ("system/kernel/rsi_cycle.py",
     "state/rsi/l3_budget+l3_sightings stamps (derived) + observer_actions.jsonl (append)"),
)

# FASE-2 GATE (policy R16 ratified 2026-10-16): writers EXEMPT from the
# derived registry — PRIMARY records (irreproducible source of truth) or
# EXTERNAL targets (outside this workspace: /var/lib, /root). Scan-filter
# only; never invent an exemption: every entry carries its reason.
PRIMARY_OR_EXTERNAL_WRITERS = (
    ("scripts/state/lessons/lesson_capture.py", "primary: lecciones S5 (records)"),
    ("scripts/state/core/state_attest.py", "primary: attestations firmadas (CA)"),
    ("scripts/algedonic/ac_algedonic.py", "external: /var/lib/vsf (host)"),
    ("scripts/algedonic/vsf_bbs_poller.py", "external: /root (host)"),
    ("scripts/s3-allocation/kpi_spc.py", "external: /var/lib/vsf (host)"),
    ("scripts/state/monitoring/topology_reconcile.py", "external: /var/lib/vsf-state (host)"),
)
VERIFIER_DIR = ROOT / "scripts" / "vsl" / "validator"


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_manifest_parser():
    """Reuse the boot verifier's parser (single source for artifact form)."""
    if str(VERIFIER_DIR) not in sys.path:
        sys.path.insert(0, str(VERIFIER_DIR))
    from verify_boot_ontology import load_manifest_from  # type: ignore
    return load_manifest_from


def check_boot_pins(base: Path | None = None) -> list[dict]:
    """Drift report for string-path hash pins (skips SELF/child-repo/runtime)."""
    base = base or ROOT
    load = _load_manifest_parser()
    m = load(MANIFEST)
    if not m:
        return [{"path": str(MANIFEST), "error": "manifest missing"}]
    drift = []
    for a in m["artifacts"]:
        h = a["hash"]
        if h in ("SELF",) or not re.fullmatch(r"[0-9a-f]{16}", h):
            continue  # symbolic/non-file pins are not disk-hashed
        p = base / a["path"]
        if not p.exists():
            drift.append({"path": a["path"], "declared": h, "disk": None})
            continue
        real = sha16(p)
        if real != h:
            drift.append({"path": a["path"], "declared": h, "disk": real})
    return drift


def apply_boot_pins(drift: list[dict]) -> int:
    """Rewrite stale hash="..." values in the manifest text. Returns count."""
    if not drift:
        return 0
    txt = MANIFEST.read_text(encoding="utf-8")
    changed = 0
    for d in drift:
        path, new = d["path"], d.get("disk")
        if not new:
            continue  # missing file: report only, never delete the pin
        # The artifact stanza: path on the artifact( line, hash within the
        # next ~3 lines. Anchor on the quoted path, replace the first
        # hash="..." after it (stanzas are one-per-artifact, no reuse of
        # the same path string in the file).
        pat = re.compile(
            r'(artifact\(\s*"' + re.escape(path) + r'"'
            r'(?:(?!artifact\().)*?hash=")[0-9a-f]{16}(")',
            re.DOTALL,
        )
        txt, n = pat.subn(lambda _m: _m.group(1) + new + _m.group(2), txt, count=1)
        if n:
            changed += 1
    if changed:
        MANIFEST.write_text(txt, encoding="utf-8")
    return changed


def scripts_fingerprint(base: Path | None = None) -> str:
    """Cheap deterministic fingerprint of scripts/ (paths + sizes)."""
    base = (base or ROOT) / "scripts"
    rows = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
            rows.append(f"{p.relative_to(base)}:{p.stat().st_size}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


def read_stamp() -> dict:
    try:
        return json.loads(STAMP.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def apply_scripts_manifests() -> bool:
    """Regen both scripts manifests via the canonical tool. Returns ran-ok."""
    if not SCRIPTS_MANIFEST_TOOL.exists():
        return False
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_MANIFEST_TOOL)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    return r.returncode == 0


def resync(apply: bool = False) -> dict:
    """Check (or apply) all derived resyncs. Deterministic report dict."""
    report: dict = {"boot_pins": [], "scripts": {}, "tasks_drift": None}

    drift = check_boot_pins()
    report["boot_pins"] = drift
    report["boot_pins_stale"] = len(drift)
    if apply and drift:
        report["boot_pins_applied"] = apply_boot_pins(drift)
        report["boot_pins"] = check_boot_pins()  # post-apply: must be empty

    fp = scripts_fingerprint()
    stamp = read_stamp()
    stale = stamp.get("scripts_fp") != fp
    report["scripts"] = {
        "fingerprint": fp,
        "stamped": stamp.get("scripts_fp"),
        "stale": stale,
    }
    if apply and stale:
        ok = apply_scripts_manifests()
        report["scripts"]["regenerated"] = ok
        if ok:
            STAMP.parent.mkdir(parents=True, exist_ok=True)
            STAMP.write_text(json.dumps({
                "scripts_fp": fp,
                "boot_pins_drifted": len(drift),
            }) + "\n")
            report["scripts"]["stale"] = False

    # Judgment blocks: report only (R9 — no silent concession, no auto-write)
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "state" / "tasks" /
                                "tasks_reconcile.py")],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
        )
        out = (r.stdout or "").strip().splitlines()
        report["tasks_drift"] = {
            "rc": r.returncode,
            "summary": out[-1] if out else "",
        }
    except (OSError, subprocess.SubprocessError) as e:
        report["tasks_drift"] = {"error": str(e)}

    report["drift_total"] = (
        len(report["boot_pins"])
        + (1 if report["scripts"]["stale"] else 0)
    )
    report["ok"] = report["drift_total"] == 0
    return report


def main() -> int:
    apply = "--apply" in sys.argv
    as_json = "--json" in sys.argv
    report = resync(apply=apply)
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        mode = "APPLY" if apply else "CHECK"
        print(f"[derived-resync {mode}] drift_total={report['drift_total']}")
        for d in report["boot_pins"]:
            print(f"  boot-pin STALE {d['path']}: {d['declared']} -> {d.get('disk')}")
        if apply and report.get("boot_pins_applied"):
            print(f"  boot-pins rewritten: {report['boot_pins_applied']}")
        s = report["scripts"]
        print(f"  scripts fp={s['fingerprint']} stale={s['stale']}"
              + (f" regenerated={s['regenerated']}" if "regenerated" in s else ""))
        td = report.get("tasks_drift") or {}
        print(f"  tasks_reconcile rc={td.get('rc')} {td.get('summary', td.get('error', ''))}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
