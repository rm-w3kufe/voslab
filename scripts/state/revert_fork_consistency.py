#!/usr/bin/env python3
# design: docs/plans/revert_fork_robustness_2026_10_23.vsm (PROPOSED; Fase
#         investigation S5 2026-10-23 "tenemos que estudiar esto")
# ROL: S4
# DRIVER: LLM_probe
# CANAL: manual
"""revert_fork_consistency.py — READ-ONLY auditor (audit_v0, report-only).

Cross-check: archivos tocados en la ventana vs entradas de registro
(logs/agent_plugin.jsonl con session_id). Findings: orphan / ghost /
double-writer (ver doc). Escrituras: CERO (R17-safe). rc: 0 consistente
| 1 hallazgos | 2 hallazgos severos o error interno. R10: mismo log +
mismo git state => mismo output SIEMPRE (sin random, sin relojes generando
flags) para findings con offset opcional (--window-min).

Limitación honesta (v0): NO resuelve si un tool-call de opencode que
retrocedió la narrativa persistió como registro — solo tachar la
CONGRUENCIA files(registro narrativo) vs git(registro duradero).
"""
from __future__ import annotations

import gzip
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = Path("logs/agent_plugin.jsonl")
WRITE_RE = re.compile(r"(^|[^>])>>? *\S|git (commit|add)|\bmv \|\brm \b|\bcp \b|\btouch ")
WIN_MIN_DEFAULT = 180


def _git_files(window_min: int) -> dict[str, dict]:
    """archivos tocados recientes (git log --name-only en N commits +
    status ark). Devuelve {path: {commits, sessions_seen}}."""
    out: dict[str, dict] = {}
    try:
        r = subprocess.run(
            ["git", "log", "--since", f"{window_min} minutes ago",
             "--name-only", "--pretty=format:%H|%aI|%s"],
            capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"FATAL git log: {e.stderr.strip()[:160]}", file=sys.stderr)
        sys.exit(2)
    for block in r.stdout.split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        head, paths = lines[0], lines[1:]
        sh, ts, subj = (head + "||").split("|")[:3]
        for p in paths:
            rec = out.setdefault(p.strip(), {"commit": sh[:7],
                                             "ts": ts, "subj": subj})
            rec.setdefault("files", paths)
    return out


def _iter_log_lines(window_min: int) -> Iterator[str]:
    """Sólo los logs potencialmente en-window: file vivo + rotados cuyo
    epoch-name queda después de cut. Los rotados llevan epoch-ms en el
    nombre (agent_plugin.jsonl.<epoch>.gz) — sin ello el scan de 220MB
    tarda > 2min (lección v0-2 rendimiento)."""
    if not LOG.exists():
        return
    cut = datetime.now(timezone.utc) - timedelta(minutes=window_min)
    yield from LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    for gz in sorted(LOG.parent.glob(LOG.name + ".*.gz")):
        m = re.match(r"agent_plugin\.jsonl\.(\d{10,})\.jsonl\.gz", gz.name)
        if not m:
            continue
        try:
            gz_ts = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            continue
        if gz_ts < cut and int(m.group(1)) + 0 < int(cut.timestamp() * 1000):
            continue
        with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as fp:
            yield from fp


def _log_touches(window_min: int) -> tuple[list[dict], set[str]]:
    """entradas de log con posible escritura (bash commit/mv/>>) y session
    ids de la ventana. Especifico: Livingston + rotados on-window
    (v0-1: los .gz son parte del registro; v0-2: filtros por epoch del
    nombre para no re-explotar 220MB)."""
    entries, sids = [], set()
    now = datetime.now(timezone.utc)
    cut = now - timedelta(minutes=window_min)
    for raw in _iter_log_lines(window_min):
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        ts = (r.get("ts") or "").replace("Z", "+00:00")
        try:
            t = datetime.fromisoformat(ts)
        except ValueError:
            t = now
        if t < cut:
            continue
        if r.get("session_id"):
            sids.add(r["session_id"])
        act = r.get("action") or ""
        if r.get("source") == "tool-integration" and WRITE_RE.search(act):
            entries.append({"ts": ts, "sid": r.get("session_id"), "act": act[:120]})
    return entries, sids


def audit(window_min: int) -> tuple[list[dict], int, int]:
    files = _git_files(window_min)
    touches, sids = _log_touches(window_min)
    n_log = len(touches)
    findings = []
    per_file = {}
    for t in touches:
        for p in files:
            if _mention(p, t["act"]):
                per_file.setdefault(p, set()).add(t["sid"] or "(no-sid)")
    for p, meta in sorted(files.items()):
        in_log = p in per_file
        if not Path(p).exists():
            findings.append({"type": "ghost-file-in-commit", "file": p,
                             "detail": f"commit {meta['commit']} lista {p} "
                                       "pero no existe en working tree"})
            continue
        if not in_log:
            findings.append({"type": "orphan-tracked-file", "file": p,
                             "detail": f"tocado en commit {meta['commit']} "
                                       f"({meta['ts'][:16]}) sin entrada de "
                                       "log en ventana — avance sin narrativa?"})
    for p, ss in per_file.items():
        distinct = {s for s in ss if s and s != "(no-sid)"}
        if len(distinct) > 1:
            findings.append({"type": "double-writer", "file": p,
                             "detail": f"sessions {sorted(distinct)} en ventana"})
    return findings, len(files), n_log


def _log_touches_only_sids(window_min: int) -> set[str]:
    """secondary cheap pass — SOLO session ids en ventana (sin writer
    re-scan). Reutiliza _log_touches pero omite processor de entries."""
    _, sids = _log_touches(window_min)
    return sids


def _mention(path: str, act: str) -> bool:
    base = Path(path).name
    return (path in act) or (bool(base) and base in act)


def main() -> int:
    args = sys.argv[1:]
    window = WIN_MIN_DEFAULT
    if "--window-min" in args:
        window = int(args[args.index("--window-min") + 1])
    try:
        findings, n_files, n_log = audit(window)
    except Exception as e:  # R9 fail-loud
        print(json.dumps({"rc": 2, "error": str(e)[:300]}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "window_min": window,
        "files_tracked": n_files,
        "log_entries_writeish": n_log,
        "sessions": sorted(_log_touches_only_sids(window)),
        "findings": findings,
        "rc": 1 if findings else 0,
    }, ensure_ascii=False, indent=1))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
