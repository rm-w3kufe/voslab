#!/usr/bin/env python3
"""
EXP-PHI-02 wrapper — computed/interpreted brief field split.

Tests H7 (split_fidelity), H8 (compression), H9 (capability_taxonomy).
Core principle: variety belongs to the layer competent to handle it.
  Computed fields (deterministic) → wrapper executes before sending to LLM.
  Interpreted fields (semantic)   → LLM executes only these.

Resolves H6 (EXP-PHI-01): closure ≠ correctness. Split design prevents
LLM counting bias by removing counting tasks from LLM scope entirely.

PHI-01 baseline: brief_bytes ~8000, latency ~12s (full file inlined for counting).
H8 accept: brief_bytes_v2 < 4000, latency_v2 < 4s.

USAGE:
    # Ollama tunnel needed for T1 (events.jsonl on LXC 101):
    ssh -L 11434:localhost:11434 -N root@n02 &

    python3 scripts/llm/run_phi02_split.py --task all
    python3 scripts/llm/run_phi02_split.py --task T2 --verbose
    python3 scripts/llm/run_phi02_split.py --task all --out docs/experiments/EXP-PHI-02/results/

    # T1 needs events.jsonl locally — fetch first:
    ssh root@n02 "pct exec 101 -- tail -200 /var/lib/vsf/vsf_nucleus/events.jsonl" \\
        > /tmp/vsf_events_phi02.jsonl
    python3 scripts/llm/run_phi02_split.py --task T1 --events /tmp/vsf_events_phi02.jsonl
"""

import argparse, json, re, sys, time
import urllib.request, urllib.error
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT     = Path(__file__).resolve().parent.parent
RESULTS_DIR   = REPO_ROOT / "docs/experiments/EXP-PHI-02/results"
OLLAMA_URL    = "http://localhost:11434"
MODEL         = "qwen2.5-coder:1.5b"
TIMEOUT_S     = 600  # 1.5b on CPU: 200-word response ~315s (25s prompt_eval + 290s generation)
PHI01_BASELINE_BRIEF_BYTES = 8000
PHI01_BASELINE_LATENCY_S   = 12.0

SYSTEM_PROMPT = """You are receiving a VSL brief from your S3 coordinator.

The brief contains two sections:
1. COMPUTED (pre-filled by wrapper — DO NOT recompute these):
   These values are already correct. Use them as context only.

2. YOUR TASK — fill in ONLY the interpreted fields:
   Return ONLY a JSON object with the keys: summary, key_themes, cybersyn_mapping.

Rules:
- summary: string, ≤200 words, plain prose
- key_themes: array of ≤5 strings
- cybersyn_mapping: object mapping key terms from the text to S-levels (S1/S2/S3/S3*/S4/S5)
  Include 3-6 mappings. Only map terms that appear in the text.
- Respond with ONLY the JSON object. No prose before or after, no markdown fences."""

# ─── TASK DEFINITIONS ────────────────────────────────────────────────────────

def _repo(rel: str) -> Path:
    return REPO_ROOT / rel

TASKS = {
    "T1": {
        "name":     "events.jsonl analysis",
        "source":   None,  # set via --events flag (tail -200 from LXC 101)
        "patterns": [r'"viable":true', r'"viable":false', r'angustia', r'"regime":"stasis"'],
        "cybersyn_ref": {"kernel_tick": "S1", "trust_axes": "S3", "algedonic": "S5"},
    },
    "T2": {
        "name":    "ethics_vigilance spec",
        "source":  _repo("docs/spec/ethics_vigilance/spec.vsm"),
        "patterns": [r'TPR', r'FPR', r'A0[^.]', r'A0\.1', r'watchdog'],
        "cybersyn_ref": {"watchdog": "S5", "A0_classifier": "S4", "dims[53/54]": "S1"},
    },
    "T3": {
        "name":    "covenant",
        "source":  _repo("docs/governance/covenant.vsm"),
        "patterns": [r'axiom', r'A[0-9]\.', r'⟦.*⟧', r'covenant'],
        "cybersyn_ref": {"axioms": "S5", "S4_proposals": "S4", "algedonic": "S5"},
    },
    "T4": {
        "name":    "psi_protocol spec",
        "source":  _repo("docs/spec/psi_protocol/spec.vsm"),
        "patterns": [r'theta_PSI', r'stasis_cos', r'L[123]_', r'angustia'],
        "cybersyn_ref": {"L1_observe": "S4", "L2_support": "S4", "L3_escalate": "S5"},
    },
    "T5": {
        "name":    "n02_runbook",
        "source":  _repo("docs/infra/n02_runbook.vsm"),
        "patterns": [r'LXC \d+', r'ssh root', r'systemctl', r'pct exec'],
        "cybersyn_ref": {"LXC 101": "S1", "LXC 107": "S3*", "LXC 109": "S5"},
    },
}

# ─── COMPUTED LAYER ──────────────────────────────────────────────────────────

def compute_fields(text: str, patterns: list) -> dict:
    words  = text.split()
    top20  = Counter(words).most_common(20)
    regex  = [{"pattern": p, "count": len(re.findall(p, text))} for p in patterns]
    return {
        "line_count":        len(text.splitlines()),
        "word_count":        len(words),
        "token_frequencies": dict(top20),
        "regex_matches":     regex,
    }

# ─── BRIEF BUILDER ───────────────────────────────────────────────────────────

def build_brief(task_name: str, computed: dict) -> str:
    freq_str = ", ".join(f'"{k}": {v}' for k, v in list(computed["token_frequencies"].items())[:10])
    regex_str = " | ".join(f'{r["pattern"]}×{r["count"]}' for r in computed["regex_matches"])
    return (
        f"TASK: Analyse the VSF document: {task_name}\n\n"
        f"COMPUTED (wrapper-executed — context only, DO NOT recompute):\n"
        f"  line_count: {computed['line_count']}\n"
        f"  word_count: {computed['word_count']}\n"
        f"  top tokens: {{{freq_str}}}\n"
        f"  patterns: {regex_str}\n\n"
        f"YOUR TASK — return ONLY a JSON object:\n"
        f'{{"summary": "...", "key_themes": [...], "cybersyn_mapping": {{...}}}}'
    )

# ─── OLLAMA CALL ─────────────────────────────────────────────────────────────

def call_ollama(url: str, brief: str, verbose: bool) -> tuple[bool, dict, float]:
    payload = json.dumps({
        "model":   MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": brief},
        ],
        "stream":  False,
        "options": {"temperature": 0.0, "num_predict": 150},  # cap at ~120 words to fit in TIMEOUT_S
    }).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=payload,
        headers={"content-type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = json.loads(resp.read())
            latency = time.time() - t0
            text = body.get("message", {}).get("content", "")
            if verbose:
                print(f"  [qwen raw] {text[:200]}")
            # strip markdown fences and find outermost JSON object
            stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            start = stripped.find("{")
            if start >= 0:
                # scan forward for balanced closing brace
                depth = 0
                end = -1
                for i, ch in enumerate(stripped[start:], start):
                    if ch == "{": depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0: end = i + 1; break
                if end > start:
                    try:
                        parsed = json.loads(stripped[start:end])
                        return True, parsed, latency
                    except json.JSONDecodeError:
                        pass
            return False, {"_raw": text[:500]}, latency
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return False, {"_error": str(e)}, time.time() - t0

# ─── SCORER ──────────────────────────────────────────────────────────────────

def score_computed(computed: dict) -> dict:
    # Computed fields are always correct (wrapper is deterministic).
    # Validation: all expected keys present and values are non-negative integers/lists.
    ok = (
        isinstance(computed["line_count"], int) and computed["line_count"] >= 0
        and isinstance(computed["word_count"], int) and computed["word_count"] >= 0
        and isinstance(computed["token_frequencies"], dict)
        and isinstance(computed["regex_matches"], list)
    )
    return {"fidelity_computed": 1.0 if ok else 0.0, "implementation_ok": ok}

def check_interpreted_structure(parsed: dict) -> dict:
    has_summary  = isinstance(parsed.get("summary"), str) and len(parsed["summary"]) > 0
    has_themes   = isinstance(parsed.get("key_themes"), list) and 0 < len(parsed["key_themes"]) <= 5
    has_mapping  = isinstance(parsed.get("cybersyn_mapping"), dict) and len(parsed["cybersyn_mapping"]) >= 2
    return {
        "structure_ok":     has_summary and has_themes and has_mapping,
        "summary_present":  has_summary,
        "themes_present":   has_themes,
        "mapping_present":  has_mapping,
        "mapping_count":    len(parsed.get("cybersyn_mapping", {})),
        "summary_words":    len(parsed.get("summary", "").split()),
        "themes_count":     len(parsed.get("key_themes", [])),
        "note": "fidelity_interpreted requires human rating (0-1 per field) — stored for review",
    }

# ─── RUN ONE TASK ────────────────────────────────────────────────────────────

def run_task(task_id: str, task: dict, text: str, ollama_url: str, verbose: bool) -> dict:
    if verbose:
        print(f"\n── {task_id}: {task['name']} ──")

    # 1. Compute fields deterministically
    computed = compute_fields(text, task["patterns"])

    # 2. Build brief (interpreted fields only for LLM)
    brief = build_brief(task["name"], computed)
    brief_bytes = len(brief.encode())

    if verbose:
        print(f"  brief_bytes={brief_bytes} (PHI-01 baseline={PHI01_BASELINE_BRIEF_BYTES})")

    # 3. Call Qwen
    ok, parsed, latency = call_ollama(ollama_url, brief, verbose)

    # 4. Score
    c_score = score_computed(computed)
    i_check = check_interpreted_structure(parsed) if ok else {"structure_ok": False, "error": str(parsed)}

    result = {
        "task_id":          task_id,
        "task_name":        task["name"],
        "ts":               datetime.now(timezone.utc).isoformat(),
        "computed":         computed,
        "computed_score":   c_score,
        "brief_bytes":      brief_bytes,
        "brief_bytes_ratio": round(brief_bytes / PHI01_BASELINE_BRIEF_BYTES, 2),
        "latency_s":        round(latency, 3),
        "latency_ratio":    round(latency / PHI01_BASELINE_LATENCY_S, 2),
        "llm_ok":           ok,
        "interpreted":      parsed if ok else None,
        "interpreted_check": i_check,
        "cybersyn_ref":     task.get("cybersyn_ref", {}),
        "h7_pass": c_score["fidelity_computed"] == 1.0,
        "h8_brief_pass": brief_bytes < PHI01_BASELINE_BRIEF_BYTES / 2,
        "h8_latency_pass": latency < PHI01_BASELINE_LATENCY_S / 3,
    }

    if verbose:
        print(f"  latency={latency:.2f}s (ratio={result['latency_ratio']}×baseline)")
        print(f"  H7={'PASS' if result['h7_pass'] else 'FAIL'} "
              f"H8_bytes={'PASS' if result['h8_brief_pass'] else 'FAIL'} "
              f"H8_latency={'PASS' if result['h8_latency_pass'] else 'FAIL'}")
        print(f"  structure_ok={i_check.get('structure_ok')} "
              f"mapping_count={i_check.get('mapping_count', '?')}")

    return result

# ─── AGGREGATE ───────────────────────────────────────────────────────────────

def aggregate(results: list) -> dict:
    n = len(results)
    if n == 0:
        return {}
    h7_pass  = sum(r["h7_pass"] for r in results)
    h8b_pass = sum(r["h8_brief_pass"] for r in results)
    h8l_pass = sum(r["h8_latency_pass"] for r in results)
    return {
        "n_tasks":              n,
        "H7_split_fidelity":   {"pass": h7_pass, "total": n, "verdict": "PASS" if h7_pass == n else "FAIL"},
        "H8_brief_bytes":      {"median": sorted(r["brief_bytes"] for r in results)[n//2],
                                "baseline": PHI01_BASELINE_BRIEF_BYTES,
                                "pass": h8b_pass, "total": n,
                                "verdict": "PASS" if h8b_pass >= n * 0.8 else "FAIL"},
        "H8_latency":          {"median": sorted(r["latency_s"] for r in results)[n//2],
                                "baseline": PHI01_BASELINE_LATENCY_S,
                                "pass": h8l_pass, "total": n,
                                "verdict": "PASS" if h8l_pass >= n * 0.8 else "FAIL"},
        "H9_capability_note":  "Populate capability_matrix.json after human rating of interpreted fields",
        "interpreted_for_review": [
            {"task_id": r["task_id"], "interpreted": r["interpreted"],
             "structure": r["interpreted_check"]}
            for r in results if r.get("interpreted")
        ],
    }

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EXP-PHI-02: computed/interpreted brief split")
    parser.add_argument("--task",      default="all", help="T1/T2/T3/T4/T5 or 'all'")
    parser.add_argument("--events",    default=None,  help="local path to events.jsonl (for T1)")
    parser.add_argument("--ollama-url", default=OLLAMA_URL)
    parser.add_argument("--out",       default=str(RESULTS_DIR), help="results directory")
    parser.add_argument("--repo-root", default=None, help="override REPO_ROOT for source file paths")
    parser.add_argument("--verbose",   action="store_true")
    args = parser.parse_args()

    if args.repo_root:
        repo_root = Path(args.repo_root)
        for tid, task in TASKS.items():
            if task.get("source") is not None:
                try:
                    rel = task["source"].relative_to(REPO_ROOT)
                except ValueError:
                    rel = Path(str(task["source"]).lstrip("/"))
                task["source"] = repo_root / rel

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    task_ids = list(TASKS.keys()) if args.task == "all" else [args.task.upper()]

    results = []
    for tid in task_ids:
        if tid not in TASKS:
            print(f"[phi02] unknown task {tid}", file=sys.stderr); continue

        task = TASKS[tid]

        # Resolve source text
        if tid == "T1":
            if not args.events:
                print(f"[phi02] T1 needs --events (fetch with: ssh root@n02 "
                      f"'pct exec 101 -- tail -200 /var/lib/vsf/vsf_nucleus/events.jsonl' "
                      f"> /tmp/vsf_events_phi02.jsonl)", file=sys.stderr)
                continue
            text = Path(args.events).read_text()
        else:
            src = task["source"]
            if not src or not Path(src).exists():
                print(f"[phi02] {tid}: source not found: {src}", file=sys.stderr); continue
            text = Path(src).read_text()

        result = run_task(tid, task, text, args.ollama_url, args.verbose)
        results.append(result)

        # Write per-task result
        task_file = out_dir / f"phi02_{tid.lower()}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
        task_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        if args.verbose:
            print(f"  → {task_file}")

    if not results:
        print("[phi02] no results", file=sys.stderr); sys.exit(1)

    # Aggregate
    agg = aggregate(results)
    agg_file = out_dir / f"phi02_aggregate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    agg_file.write_text(json.dumps(agg, indent=2, ensure_ascii=False))

    print(f"\n── EXP-PHI-02 SUMMARY ──")
    print(f"  H7 split_fidelity: {agg['H7_split_fidelity']['verdict']} "
          f"({agg['H7_split_fidelity']['pass']}/{agg['H7_split_fidelity']['total']})")
    print(f"  H8 brief_bytes:    {agg['H8_brief_bytes']['verdict']} "
          f"(median={agg['H8_brief_bytes']['median']}B vs baseline={PHI01_BASELINE_BRIEF_BYTES}B)")
    print(f"  H8 latency:        {agg['H8_latency']['verdict']} "
          f"(median={agg['H8_latency']['median']:.2f}s vs baseline={PHI01_BASELINE_LATENCY_S}s)")
    print(f"  Results: {agg_file}")
    print(f"  ⚠  H9 capability_matrix: rate interpreted fields manually → capability_matrix.json")

if __name__ == "__main__":
    main()
