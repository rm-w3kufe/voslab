#!/usr/bin/env python3
"""tmp_sweep — dry-run por defecto; rm solo con --enforce y solo archivos
candidatos en el JSON de reporte del MISMO día (lista ratificada).
Política: docs/plans/tmp_policy_2026_10_22.vsm (R17-safe).

Uso:
  python3 scripts/tmp_sweep.py                # refresca state/tmp_sweep_dry_run.json (sin rm)
  python3 scripts/tmp_sweep.py --enforce      # rm de los candidatos de clase A/B/C en el reporte de hoy
"""
from __future__ import annotations
import argparse, glob, json, os, subprocess, sys, time

BASE = "/tmp/opencode"
SPECS = [
    ("A_runbg_markers", "*.done", 14),
    ("A_runbg_markers", "*.failed", 14),
    ("B_tk_out", "tk_*.out", 7),
    ("C_logs_out", "*.log", 7),
    ("C_logs_out", "*.out", 7),
    ("C_logs_out", "*.body", 7),
    ("D_eval_artifacts", "bench_*.json", None),
    ("D_eval_artifacts", "*_out", None),
    ("D_eval_artifacts", "*_recs.json", None),
]
HARD_COND = lambda p: p.endswith(("current_focus.txt",))

def _age(p): return round((time.time() - os.path.getmtime(p)) / 86400, 2)
def _rsize(p):
    if os.path.isdir(p):
        try: return int(subprocess.run(["du","-sb",p],capture_output=True,text=True).stdout.split()[0])
        except Exception: return 0
    return os.path.getsize(p)

def scan() -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); seen = set(); cand = {}
    for cls, pat, cutoff in SPECS:
        for p in sorted(glob.glob(os.path.join(BASE, pat))):
            if HARD_COND(p) or p in seen: continue
            seen.add(p); a = _age(p)
            if cutoff is None or a >= cutoff:
                cand.setdefault(cls, []).append(
                    {"f": os.path.basename(p), "age_d": a, "bytes": _rsize(p),
                     "cutoff": cutoff if cutoff else "batch"})
    tb = sum(c["bytes"] for v in cand.values() for c in v)
    return {"ts": now, "mode": "dry_run", "base": BASE,
            "candidates": {k: {"n": len(v), "files": v} for k, v in cand.items()},
            "summary": {"total_candidates": sum(len(v) for v in cand.values()), "total_bytes": tb},
            "note": "clase E (datasets/labs/kernels/.venv) excluida: batch separado pendiente S5"}


def scan_e() -> dict:
    """Clase E: artefactos pesados >= 50MB. SOLO listado (R17: batch
    separado con lista ratificada; nunca rm directo)."""
    rows = []
    for entry in sorted(os.listdir(BASE)):
        p = os.path.join(BASE, entry)
        try:
            b = int(subprocess.run(["du","-sb",p], capture_output=True, text=True).stdout.split()[0])
        except Exception:
            b = 0
        if b >= 50 * 1024 * 1024:
            rows.append({"name": entry, "bytes": b,
                         "type": "dir" if os.path.isdir(p) else "file"})
    rows.sort(key=lambda r: r["bytes"], reverse=True)
    total = sum(r["bytes"] for r in rows)
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cls": "E", "base": BASE, "rule": ">= 50MB",
            "rows": rows,
            "summary": {"n": len(rows), "total_bytes": total,
                        "total_GiB": round(total/1024**3, 2)}}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enforce", action="store_true",
                    help="rm de los candidatos de clase A/B/C en el reporte de HOY (R17: requiere ratificación previa por conversación)")
    ap.add_argument("--scan-e", action="store_true",
                    help="genera lista clase E (>=50MB, solo listado, sin rm) en state/tmp_sweep_list_e.json")
    if ap.parse_args().scan_e:
        rep_e = scan_e()
        json.dump(rep_e, open("state/tmp_sweep_list_e.json","w"), indent=2, ensure_ascii=False)
        print("clase E:", rep_e["summary"]["n"], "items,", rep_e["summary"]["total_GiB"], "GiB")
        for r in rep_e["rows"][:12]:
            print(f"  {r['name']:<28}{r['bytes']/1024**3:>8.2f} GiB  {r['type']}")
        return 0
    rep = scan()
    if ap.parse_args().enforce:
        today = time.strftime("%Y-%m-%d")
        rep_date_ok = json.load(open("state/tmp_sweep_dry_run.json")).get("ts","").startswith(today)
        if not rep_date_ok:
            print("Fallo R17: no hay reporte dry-run de HOY. Correte el scan y pide Ratificación S5 primero.")
            return 2
        did = []
        for cls in ("A_runbg_markers", "B_tk_out", "C_logs_out"):
            for c in rep["candidates"].get(cls, {}).get("files", []):
                p = os.path.join(BASE, c["f"])
                try: os.remove(p); did.append(c["f"])
                except FileNotFoundError: pass
        for cls in rep["candidates"]:
            if cls == "A_runbg_markers": rep["candidates"][cls]["n"] -= sum(1 for d in did if d.endswith((".done",".failed")))
            if cls == "B_tk_out": rep["candidates"][cls]["n"] -= 0
        rep["mode"] = "enforced"; rep["removed"] = did
        h = "state/tmp_sweep_history.jsonl"
        with open(h, "a") as f: f.write(json.dumps(rep, ensure_ascii=False) + "\n")
        print(f"ENFORCED: {len(did)} eliminados (historial en {h})")
    json.dump(rep, open("state/tmp_sweep_dry_run.json","w"), indent=2, ensure_ascii=False)
    print("por clase:", {k: v["n"] for k, v in rep["candidates"].items()},
          "; total KB:", rep["summary"]["total_bytes"] // 1024)
    return 0

if __name__ == "__main__":
    sys.exit(main())
