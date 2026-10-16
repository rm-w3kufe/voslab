#!/usr/bin/env python3
# design: docs/evaluation/system_evaluation_2026_10_14.vsm
# route: gate_suite (NC battery extractor-vacuity) + cli/manual
# (EV-R3 — rubrica D5-C1/D5-C3: un extractor que no extrae debe GRIITAR,
#  nunca devolver vacio silencioso que el consumidor lee como "saludable")
"""extractor_vacuity.py — anti-vacuity battery (P-EV-R3).

The defect CLASS (EV-R3): an extractor's data source vanishes — moved
corpus, dead subprocess, ROOT path off-by-one after a move — and the
extractor emits EMPTY output with rc=0. Every consumer reads "0 findings /
no incoherent" as healthy. Two live instances found building this battery:

  1. version_scan.py resolved ROOT via dirname³ (written for its old home
     scripts/vsl/) after the move to scripts/vsl/tools/ → CORPUS pointed
     at <repo>/scripts/docs/spec_revision (nonexistent) → zero lines,
     rc=0 → vsm-version-coherent PASSed VACUOUSLY since the migration
     (FND-VERSION-SCAN-ROOT-OFFBYONE, fixed same round).
  2. the check's `< <(python3 scanner 2>/dev/null)` + grep loop ate
     scanner crashes (empty stream → incoherent stayed 0 → PASS with
     ZERO lines scanned — fixed in vsf-version-coherent same round).

Battery: run each extractor, require POSITIVE EVIDENCE (count > 0).
Crash, empty stream, zero counts — all fail the probe → exit 1 naming
the vacuous extractor (GRIITA). "Empty" is never "healthy".

Modes:
  (default)      live-tree probes (all four extractors)
  --target DIR   fixture probes (retargetable extractor vs DIR) — used by
                 the gate's negative control: an EMPTY target must be
                 REJECTED (exit != 0); empty ≠ healthy.

Probes (deterministic R10: no clock, no randomness, same input → same
verdict):
  version_scan     stdout ≥1 doc lines AND DISTRIBUTION sums >0
  lifecycle_census --json total > 0
  dep_graph        build() edges > 0 AND why > 0
  doc_manifest     stats total_vsf > 0

Exit: 0 = every probe non-vacuous; 1 = vacuous (probe names printed).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "scripts" / "vsl" / "tools"


def _run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(
            [sys.executable, *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, (r.stdout or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, f"EXEC-ERROR {e}"


def probe_version_scan(target: Path | None = None) -> tuple[bool, str]:
    """Scanner must emit doc lines AND a non-empty distribution.

    target=None → live default walk (CORPUS). target → driver walks the
    fixture itself (0 .vsm files = source vanished = vacuous).
    """
    scanner = str(TOOLS / "version_scan.py")
    if target is not None:
        files = sorted(
            str(p) for p in target.rglob("*.vsm")
            if "archive" not in p.relative_to(target).parts
        )
        if not files:
            return False, f"source vanished: 0 .vsm under {target}"
        rc, out = _run([scanner, "--dist", *files])
    else:
        rc, out = _run([scanner, "--dist"])
    lines = [l for l in out.splitlines() if l.strip()]
    dist_line = next((l for l in lines if l.startswith("DISTRIBUTION")), "")
    dist_sum = 0
    for pair in dist_line.split()[1:]:
        try:
            dist_sum += int(pair.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            pass
    if not lines:
        return False, f"scanner emitted 0 lines (rc={rc}) — vacuous"
    if dist_sum <= 0:
        return False, f"DISTRIBUTION empty (rc={rc}) — scanner counted nothing"
    return True, f"{len(lines)} doc lines, distribution sum={dist_sum}"


def probe_lifecycle_census() -> tuple[bool, str]:
    rc, out = _run([str(TOOLS / "lifecycle_census.py"), "--json"])
    if rc != 0:
        return False, f"census rc={rc} — no evidence"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return False, "census stdout not JSON — extractor broken"
    total = int(data.get("total", 0) or 0)
    if total <= 0:
        return False, "census total=0 — vacuous"
    return True, f"census total={total}"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"probe_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def probe_dep_graph() -> tuple[bool, str]:
    try:
        mod = _load(TOOLS / "dep_graph.py")
        edges, why = mod.build()   # raises on dead symbol_table (CC-2 class)
    except Exception as e:  # noqa: BLE001 — any failure = no evidence
        return False, f"build() failed: {type(e).__name__}: {e}"
    if not edges or not why:
        return False, f"edges={len(edges)} why={len(why)} — vacuous"
    return True, f"edges={len(edges)} why={len(why)}"


def probe_doc_manifest() -> tuple[bool, str]:
    rc, out = _run([str(TOOLS / "doc_manifest.py"), "stats"])
    if rc != 0:
        return False, f"doc_manifest stats rc={rc} — no evidence"
    try:
        data = json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return False, "stats stdout not JSON — extractor broken"
    total = int(data.get("total_vsf", 0) or 0)
    if total <= 0:
        return False, "total_vsf=0 — vacuous"
    return True, f"total_vsf={total}"


def run_battery(target: Path | None = None) -> int:
    probes: list[tuple[str, object]] = [("version_scan", lambda: probe_version_scan(target))]
    if target is None:
        probes += [
            ("lifecycle_census", probe_lifecycle_census),
            ("dep_graph", probe_dep_graph),
            ("doc_manifest", probe_doc_manifest),
        ]
    failed = 0
    mode = f"target={target}" if target else "live"
    print(f"[extractor-vacuity] battery ({mode})")
    for name, fn in probes:
        try:
            ok, detail = fn()  # type: ignore[operator]
        except Exception as e:  # noqa: BLE001 — probe crash = no evidence
            ok, detail = False, f"probe raised {type(e).__name__}: {e}"
        mark = "ok " if ok else "VACUOUS"
        print(f"  {mark} {name}: {detail}")
        if not ok:
            failed += 1
    print(f"[extractor-vacuity] {len(probes) - failed}/{len(probes)} probes non-vacuous")
    return 1 if failed else 0


def main() -> int:
    target: Path | None = None
    if "--target" in sys.argv:
        idx = sys.argv.index("--target")
        try:
            target = Path(sys.argv[idx + 1])
        except IndexError:
            print("usage: extractor_vacuity.py [--target DIR]", file=sys.stderr)
            return 2
        if not target.is_dir():
            # source vanished — exactly the vacuity class, fail loud
            print(f"[extractor-vacuity] target missing: {target}", file=sys.stderr)
            return 1
    return run_battery(target=target)


if __name__ == "__main__":
    sys.exit(main())
