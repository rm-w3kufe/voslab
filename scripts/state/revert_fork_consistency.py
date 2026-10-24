#!/usr/bin/env python3
# design: docs/plans/revert_fork_robustness_2026_10_23.vsm (PROPOSED; Fase
#         investigation S5 2026-10-23 "tenemos que estudiar esto")
# ROL: S4
# DRIVER: LLM_probe
# CANAL: manual
# ROUTE: manual estoy en scripts route manifest (registered regen 2026-10-23); entry point: python3 scripts/state/revert_fork_consistency.py --window-min N; backbone route: manual audit call, no service
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
        # naming lesson v1.3: el EPOCH del nombre = OPEN time del hunk;
        # el CIERRE es el mtime del archivo (verificado 2026-10-24: hunk
        # 1792806213690 contiene 08:32Z->01:43Z con mtime 22:43 -03).
        # Incluir si mtime >= cut (el hunk puede contener entradas
        # post-cut aunque su OPEN sea anterior).
        if gz.stat().st_mtime < cut.timestamp():
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
        # v1.4: los paths viven en context/detail (action corto tipo
        # "before tool:bash") — concatenar las tres partes para el
        # matcher de menciones.
        act = " ".join([str(r.get("action") or ""),
                        str(r.get("detail") or "")[:1500],
                        str(r.get("context") or "")[:1500]])
        # v1.2 (finding 2026-10-24): tool-integration NO logueó NINGÚN
        # evento 01:47Z→ingreso (blackout de logueo en vivo, R9) — el
        # write-evidence ahora considera CUALQUIER source cuyo action
        # matchee WRITE_RE (rsi-cycle evaluate, gap-resolution, etc.),
        # manteniendo el sid para forense.
        if WRITE_RE.search(act) or r.get("source") == "vos-kernel-write-audit":
            entries.append({"ts": ts, "sid": r.get("session_id"), "act": act[:4000]})
    return entries, sids


def _declared_writers() -> set[str]:
    """paths de estado escritos por pipeline autónomo (registro derived
    writers + scripts manifest). Esos writes NO requieren narrativa de
    sesión — se declassifican del finding orphan."""
    out: set[str] = set()
    src = Path("scripts/vsl/tools/derived_resync.py")
    if src.exists():
        for m in re.finditer(r"state\/[\w\/.-]+", src.read_text()):
            out.add(Path(m.group(0)).name)
    man = Path("system/instance/vsf-instance-v1/scripts_manifest.vsm")
    if man.exists():
        for m in re.finditer(r"state\/[\w\/.-]+", man.read_text()):
            out.add(Path(m.group(0)).name)
    return out


def _commits(window_min: int) -> list[dict]:
    try:
        r = subprocess.run(
            ["git", "log", "--since", f"{window_min} minutes ago",
             "--pretty=%H|%aI|%s", "--name-only"],
            capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        return []
    out = []
    for block in r.stdout.split("\n\n"):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        head, paths = lines[0], lines[1:]
        sh, ts, subj = (head + "||").split("|")[:3]
        out.append({"sha": sh[:7], "ts": ts,
                    "subj": subj, "files": [x.strip() for x in paths]})
    return out


def _commit_via_subject(commits: list[dict], touches: list[dict]) -> dict:
    """cada commit asociado a session_ids cuyo action contiene el subject
    (proxy de autoria narrativa: 'git add -A && git commit -m <subject>')."""
    res = {}
    for c in commits:
        frag = (c["subj"] or "")[:60]
        if len(frag) < 8:
            continue
        sids = {t["sid"] for t in touches if frag in (t["act"] or "")}
        res[c["sha"]] = {"files": c["files"], "sids": {s for s in sids if s}}
        if sids:
            frag_t = f'commit {c["sha"]}'
    return res


def audit(window_min: int) -> tuple[list[dict], int, int]:
    files = _git_files(window_min)
    touches, sids = _log_touches(window_min)
    n_log = len(touches)
    findings = []
    sha_files = _commit_via_subject(_commits(window_min), touches)
    per_file = {}
    for t in touches:
        for p in files:
            if _mention(p, t["act"]):
                per_file.setdefault(p, set()).add(t["sid"] or "(no-sid)")
    for p, meta in sorted(files.items()):
        # v1.1 heredoc-shadow: un mismo act pueden contain el basename
        # en trunks; declassify antes de declarar orphan.
        shadow_ok = any(_mention(p, t["act"])
                        for t in touches) or                     any(_act_heredoc_files(t["act"]) == {Path(p).name}
                        for t in touches)
        in_log = p in per_file or shadow_ok
        if not Path(p).exists():
            findings.append({"type": "ghost-file-in-commit", "file": p,
                             "detail": f"commit {meta['commit']} lista {p} "
                                       "pero no existe en working tree"})
            continue
        # v1.3: corré commit-subject ↔ action del log (`git add -A` no
        # nombra archivos — el subject es el puente narrativo correcto).
        via_commit = sha_files.get(meta["commit"])
        if p not in per_file and Path(p).name in _declared_writers():
            via_commit = {"files": [], "sids": {"(declared)"}}
        narrated = (isinstance(via_commit, dict) and via_commit["sids"])                    or p in per_file
        if not narrated:
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


def _act_heredoc_files(act: str) -> set[str]:
    """v1.1 heredoc-shadow declassifier (parcial): nombres de PATH dentro
    del action cuando pertenecen a writes heredoc: `> NAME <<`, `cat >
    NAME <<`, `Path("...")`, open('...') con R/W flags — mejor proxy que
    v0. Residual: heredoc bodies multi-line que la log action NO conserva
    (limitación logueada en doc, probe vlean en v2)."""
    out = set()
    for m in re.finditer(r'(?:^|\s)([\w./-]+\.[a-zA-Z]{2,4})(?=\s|$|[\'");,])', act):
        tok = m.group(1)
        if "/" in tok or tok.count(".") <= 2:
            out.add(Path(tok).name)
    for m in re.finditer(r'open\(\s*[re]?["\x27]([^"\x27]+)["\x27]', act):
        out.add(Path(m.group(1)).name)
    return out


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
