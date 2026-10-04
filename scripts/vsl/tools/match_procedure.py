#!/usr/bin/env python3
"""match_procedure.py — canonical scenario-memory suggestion matcher (CC-4).

One Python source of suggestion scoring for BOTH consumers:
  - scenario-memory handler (session.idle)  → action/confidence/detail
  - scenario-memory gap-bridge (gaps)       → matches[] (GapSuggestion shape)

Reads the CANONICAL scenario store (vsf_rsi.scenario_memory — the live
510-record agent store), NOT the dead learning_records/procedures/ dir
(empty since the TS writer was removed 2026-09-24; FND-GAP-BRIDGE-STALE-01).

CLI (contract compatible with socratic-engine match-procedure):
  python3 scripts/vsl/tools/match_procedure.py match-procedure --input '<json>'
  python3 scripts/vsl/tools/match_procedure.py --input '<json>'

Output:
  {"action": "reuse"|"adapt"|"skip", "confidence": <0..1>,
   "matches_count": <int>, "detail": "<str>",
   "matches": [{"procedureId", "confidence", "source", "suggestion",
                "metadata"}]}

Deterministic (R10): same input → byte-identical output. No wall-clock,
no randomness: scoring uses only store contents (count, quality) and the
payload (file basename, instrument).
"""

from __future__ import annotations

import json
import pathlib
import sys

# ── resolve canonical vsf_rsi (store owner) ──────────────────────────────
_RSI_CANDIDATES = [
    pathlib.Path(__import__("os").environ.get("RSI_PATH", "")) if __import__("os").environ.get("RSI_PATH") else None,
    (pathlib.Path(__file__).resolve().parents[3] / "packages" / "public" / "vsf-rsi"),
    pathlib.Path(__file__).resolve().parents[3] / "packages" / "public" / "vsf-rsi",
]
for _cand in _RSI_CANDIDATES:
    if _cand and (_cand / "vsf_rsi" / "scenario_memory.py").exists():
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break

try:
    from vsf_rsi import scenario_memory as sm
except ImportError as exc:  # fail-soft contract: skip, never crash the handler
    print(json.dumps({
        "action": "skip", "confidence": 0.0, "matches_count": 0,
        "detail": f"scenario store unavailable: {exc}"[:160],
        "matches": [],
    }))
    sys.exit(0)

FILE_HINT_KEYS = ("file_path", "filePath", "file", "path")


def _payload(argv: list[str]) -> dict:
    """Parse [--input] <json> (subcommand style optional)."""
    if argv and argv[0] == "match-procedure":
        argv = argv[1:]
    if "--input" in argv:
        i = argv.index("--input")
        raw = argv[i + 1] if i + 1 < len(argv) else "{}"
    elif argv:
        raw = argv[0]
    else:
        raw = "{}"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _basename_from_context(context: dict) -> str:
    for key in FILE_HINT_KEYS:
        val = context.get(key)
        if isinstance(val, str) and val:
            return pathlib.PurePath(val).name.lower()
    return ""


def _source_of(confidence: float) -> str:
    if confidence >= 0.8:
        return "reused"
    if confidence >= 0.6:
        return "adapted"
    return "new"


def _score_store(basename: str, instrument: str, records: list) -> list:
    """Score store records: exact file-signature hits > instrument family.

    Deterministic: score depends only on record contents (count-independent
    per-record quality + structural match), never on time.
    """
    matches = []
    family = "" if instrument in ("", "unknown") else instrument.lower()
    for rec in records:
        sig = str(rec.get("fault_signature", "")).lower()
        decision = str(rec.get("decision", "")).lower()
        quality = float(rec.get("quality", 0.5) or 0.5)
        score = 0.0
        if basename and (basename in sig or basename in decision):
            score = 0.7 + 0.3 * quality          # direct evidence: this file failed before
        elif family and sig.startswith(family + "."):
            score = 0.4 + 0.3 * quality           # same instrument family
        if score > 0:
            matches.append((rec.get("id", sig or "unknown"), round(min(score, 1.0), 3),
                            rec.get("correction_path", ""), {"quality": quality,
                                                             "fault_signature": sig}))
    return matches


def _score_patterns(min_occurrences: int) -> list:
    """Recurring fault patterns (learn()) → adaptation suggestions."""
    matches = []
    try:
        patterns = sm.learn(min_occurrences=min_occurrences)
    except Exception:
        return matches
    for p in patterns:
        count = int(p.get("count", 0))
        avg_q = float(p.get("avg_quality", 0.5))
        confidence = round(min(1.0, count / 5.0) * 0.6 + avg_q * 0.4, 3)
        matches.append((p.get("fault_signature", "unknown"), confidence,
                        p.get("correction_path", ""),
                        {"count": count, "avg_quality": avg_q}))
    return matches


def match_procedure(payload: dict) -> dict:
    instrument = str(payload.get("instrument") or "unknown")
    context = payload.get("context") or {}
    if not isinstance(context, dict):
        context = {}
    basename = _basename_from_context(context)

    try:
        records = sm._load_all()
    except Exception as exc:
        return {"action": "skip", "confidence": 0.0, "matches_count": 0,
                "detail": f"store unreadable: {exc}"[:160], "matches": []}

    if not records:
        return {"action": "skip", "confidence": 0.0, "matches_count": 0,
                "detail": "no scenarios recorded yet", "matches": []}

    raw = _score_store(basename, instrument, records) + _score_patterns(2)
    # de-duplicate by procedureId keeping highest confidence (stable order)
    best: dict[str, tuple] = {}
    for pid, conf, suggestion, meta in raw:
        if pid not in best or conf > best[pid][1]:
            best[pid] = (pid, conf, suggestion, meta)
    ranked = sorted(best.values(), key=lambda t: (-t[1], t[0]))

    matches = [
        {"procedureId": pid, "confidence": conf, "source": _source_of(conf),
         "suggestion": suggestion, "metadata": meta}
        for pid, conf, suggestion, meta in ranked[:5]
    ]
    if not matches:
        return {"action": "skip", "confidence": 0.0, "matches_count": 0,
                "detail": "no scenario matches this context", "matches": []}

    top = matches[0]
    action = "reuse" if top["confidence"] >= 0.8 else (
        "adapt" if top["confidence"] >= 0.6 else "skip")
    detail = (f"{top['procedureId']} conf={top['confidence']} "
              f"-> {top['suggestion'][:80]}")
    return {"action": action, "confidence": top["confidence"],
            "matches_count": len(matches), "detail": detail, "matches": matches}


def main(argv: list[str]) -> int:
    print(json.dumps(match_procedure(_payload(argv)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
