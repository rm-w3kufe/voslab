#!/usr/bin/env python3
"""harness.py — shared runner for vOS capability benchmarks (H1-H5 + ARC).

Design:
- Every suite is a function returning a result dict with:
    {"suite": str, "claim": str, "metrics": dict, "passed": bool,
     "threshold": str, "seed": int, "duration_s": float}
- Seeds fixed and recorded (deterministic replay).
- run_all() executes suites, writes results/baseline_v1.json (committed,
  small) and full traces to logs/ (excluded from git).
- Exit code 0 iff every suite passes (CI-gatable).

Falsifiability: each suite states its claim + numeric threshold UP FRONT.
A suite that cannot fail is theater, not measurement.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"
VOSLAB = BENCH_DIR.parent

# Repos under test (pinned at runtime, recorded in env block).
REPOS = {
    "voslab": Path("/home/rmw3/vOSlab"),
    "vsf-rsi": Path("/home/rmw3/packages/public/vsf-rsi"),
    "socratic-engine": Path("/home/rmw3/socratic-engine"),
    "vos-kernel-pkg": Path("/home/rmw3/packages/framework/vos_kernel"),
}

DEFAULT_SEED = 20260922


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_sha(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def git_clean(repo: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() == ""
    except Exception:
        return False


def env_block() -> dict:
    return {
        "timestamp": utcnow(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repos": {
            name: {"sha": git_sha(p), "clean": git_clean(p)}
            for name, p in REPOS.items()
        },
        "env_vars": {
            k: os.environ.get(k, "")
            for k in ("VOSLAB_PATH", "VSI_RSI_STORE", "N02_SSH")
        },
    }


def run_suite(name: str, fn, seed: int = DEFAULT_SEED) -> dict:
    """Execute one suite, catching crashes as failures (never silent)."""
    t0 = time.monotonic()
    try:
        result = fn(seed=seed)
        assert isinstance(result, dict), "suite must return dict"
        result.setdefault("suite", name)
        result.setdefault("seed", seed)
    except Exception as e:  # noqa: BLE001 — crash = failed measurement
        import traceback
        result = {
            "suite": name,
            "claim": "suite executes without crashing",
            "metrics": {"error": f"{type(e).__name__}: {e}"},
            "passed": False,
            "threshold": "no exception",
            "seed": seed,
            "traceback": traceback.format_exc(limit=8),
        }
    result["duration_s"] = round(time.monotonic() - t0, 2)
    return result


def write_results(results: list[dict], tag: str = "baseline_v1") -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {"env": env_block(), "results": results,
               "overall_pass": all(r["passed"] for r in results)}
    # Stable hash for replay identity (excludes durations).
    canonical = json.dumps(
        [{k: v for k, v in r.items() if k != "duration_s"} for r in results],
        sort_keys=True,
    )
    payload["replay_hash"] = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    path = RESULTS_DIR / f"{tag}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def summarize(results: list[dict]) -> str:
    lines = []
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"[{mark}] {r['suite']}: {r.get('claim','')}")
        for k, v in r.get("metrics", {}).items():
            lines.append(f"       {k} = {v}")
        lines.append(f"       threshold: {r.get('threshold','')}")
    lines.append(f"OVERALL: {'PASS' if all(r['passed'] for r in results) else 'FAIL'}")
    return "\n".join(lines)
