#!/usr/bin/env python3
"""
EXP-PHI-01 Run 005 wrapper — Ollama local substrate (H5 sovereignty test).

Analogous to projects/claude-qwen-s1/client.py but for local Ollama on LXC 101.
Reads a VSL brief, inlines a referenced file, posts to Ollama /api/chat,
captures metrics, scores against ground_truth.json, prints structured JSON.

USAGE:
    python3 scripts/llm/run_phi01_ollama.py \\
        --brief docs/experiments/EXP-PHI-01/brief_inline.vsm \\
        --file  docs/guides/concepts.md \\
        --ground-truth docs/experiments/EXP-PHI-01/ground_truth.json \\
        [--ollama-url http://localhost:11434] \\
        [--model qwen2.5-coder:7b]

If Ollama is on LXC 101 and you run this from kali, open a tunnel first:
    ssh -L 11434:10.10.10.101:11434 -N n02 &

Or copy the script to n02 and run with --ollama-url http://10.10.10.101:11434.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


SYSTEM_PROMPT = """You have received a VSL brief from your S3 coordinator (Claude).

Follow the brief exactly. Your response MUST be a single JSON object with these keys:
- "status":  one of "DONE" | "BLOCKED" | "FLAGGED"
- "summary": brief description of what you did or why blocked/flagged
- "output":  the deliverable as specified in the brief's output_format

Constraints from the brief are absolute — do not cross them.
Respond with ONLY the JSON object. No prose, no markdown fences, no commentary.

Here is the brief:
"""


def load_brief_with_inline(brief_path: Path, file_path: Path) -> tuple[str, int]:
    """Load brief, inject file content into <<INJECTED_BY_WRAPPER>> placeholder.

    Returns: (composed brief text, file_byte_count)
    """
    brief_text = brief_path.read_text()
    file_text = file_path.read_text()
    if "<<INJECTED_BY_WRAPPER>>" not in brief_text:
        print(f"[wrapper] WARNING: brief has no <<INJECTED_BY_WRAPPER>> placeholder", file=sys.stderr)
    composed = brief_text.replace("<<INJECTED_BY_WRAPPER>>", file_text)
    return composed, len(file_text)


def call_ollama(url: str, model: str, system: str, user: str, timeout: int = 180) -> tuple[bool, dict, float]:
    """POST to Ollama /api/chat. Returns (ok, response_obj_or_error, latency_seconds)."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }).encode()

    endpoint = url.rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"content-type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
        latency = time.time() - t0
        return True, json.loads(body), latency
    except urllib.error.HTTPError as e:
        latency = time.time() - t0
        return False, {"http_error": e.code, "body": e.read().decode(errors="replace")}, latency
    except Exception as e:
        latency = time.time() - t0
        return False, {"exception": str(e)}, latency


def parse_model_response(content: str) -> tuple[bool, dict | str]:
    """Try to parse the model's text content as JSON. Returns (ok, parsed_or_raw)."""
    text = content.strip()
    if text.startswith("```"):
        # strip markdown fence
        lines = text.splitlines()
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))
    try:
        return True, json.loads(text)
    except json.JSONDecodeError:
        return False, content


def score_output(output: dict, ground_truth: dict) -> dict:
    """Compare model output to expected. Returns per-key match dict + overall pass."""
    expected = ground_truth["expected_output"]
    score = {}
    all_match = True
    for key, exp_val in expected.items():
        got = output.get(key)
        if isinstance(exp_val, list):
            match = isinstance(got, list) and set(map(str, got)) == set(map(str, exp_val))
        elif isinstance(exp_val, dict):
            match = isinstance(got, dict) and got == exp_val
        else:
            match = got == exp_val
        score[key] = {"expected": exp_val, "got": got, "match": match}
        if not match:
            all_match = False
    return {"all_match": all_match, "per_key": score}


def main() -> int:
    ap = argparse.ArgumentParser(description="EXP-PHI-01 Run 005 — Ollama wrapper")
    ap.add_argument("--brief", required=True, type=Path)
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--ground-truth", required=True, type=Path)
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--model", default="qwen2.5-coder:7b")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    brief_text, file_bytes = load_brief_with_inline(args.brief, args.file)
    brief_bytes = len(brief_text)

    print(f"[wrapper] brief={args.brief.name} bytes={brief_bytes} (file_inlined={file_bytes}b)", file=sys.stderr)
    print(f"[wrapper] ollama={args.ollama_url} model={args.model}", file=sys.stderr)
    print(f"[wrapper] sending request...", file=sys.stderr)

    t_post = time.time()
    ok, resp, latency = call_ollama(args.ollama_url, args.model, SYSTEM_PROMPT, brief_text, args.timeout)
    t_recv = time.time()

    if not ok:
        result = {
            "status": "API_FAIL",
            "closure_status": "API_FAIL",
            "failure_mode": "ollama_error",
            "error": resp,
            "latency_e2e": round(latency, 3),
            "t_post": t_post,
            "t_recv": t_recv,
            "brief_bytes": brief_bytes,
            "file_bytes_inlined": file_bytes,
        }
        print(json.dumps(result, indent=2))
        return 2

    raw_content = resp.get("message", {}).get("content", "")
    result_bytes = len(raw_content)
    parsed_ok, parsed = parse_model_response(raw_content)

    if not parsed_ok:
        result = {
            "status": "PARSE_FAIL",
            "closure_status": "PARSE_FAIL",
            "failure_mode": "non_json_response",
            "raw_content": raw_content[:500],
            "latency_e2e": round(latency, 3),
            "brief_bytes": brief_bytes,
            "result_bytes": result_bytes,
            "file_bytes_inlined": file_bytes,
            "ollama_metadata": {
                "total_duration_ns": resp.get("total_duration"),
                "eval_count": resp.get("eval_count"),
                "prompt_eval_count": resp.get("prompt_eval_count"),
            },
        }
        print(json.dumps(result, indent=2))
        return 3

    model_status = parsed.get("status", "UNKNOWN")
    model_output = parsed.get("output", {})
    ground_truth = json.loads(args.ground_truth.read_text())
    score = score_output(model_output, ground_truth)

    result = {
        "status": "DONE" if score["all_match"] else "PARTIAL",
        "closure_status": model_status,
        "h1_substrate_viability": "CONFIRMED" if score["all_match"] else f"PARTIAL ({sum(1 for v in score['per_key'].values() if v['match'])}/{len(score['per_key'])} keys match)",
        "latency_e2e_seconds": round(latency, 3),
        "brief_bytes": brief_bytes,
        "result_bytes": result_bytes,
        "file_bytes_inlined": file_bytes,
        "ollama_metadata": {
            "total_duration_ns": resp.get("total_duration"),
            "eval_count": resp.get("eval_count"),
            "prompt_eval_count": resp.get("prompt_eval_count"),
            "load_duration_ns": resp.get("load_duration"),
        },
        "model_response": parsed,
        "score": score,
    }
    print(json.dumps(result, indent=2))
    return 0 if score["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
