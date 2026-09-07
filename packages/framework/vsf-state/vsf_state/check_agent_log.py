#!/usr/bin/env python3
# design: docs/spec_revision/system/s5-policy/agent-policy/agent-instruments-v1/agent_instruments.vsm
"""check_agent_log.py — validate the agent activation log (JSONL).

AGENT-CYCLE-OBSERVABILITY-2026-08-17 (directiva S5 rmw3: "observa y
mejora"): logs/agent_plugin.jsonl must be a valid append-only JSONL
activation log. Every line parses as JSON with fields
ts (ISO 8601 UTC ending in Z), instrument, hook, action, result; and
every DECLARED instrument appears at least once (a plugin that never
fires is dead code — the learning-cycle-scan lesson, 2026-08-17).

Exit: 0 valid, 1 invalid (first violation reported).
Deterministic (R10) — reads, never writes.
"""
import json
import sys


def validate(path: str, declared: str) -> int:
    seen = set()
    n = 0
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        # JSONL append-only with concurrent writers: the LAST line may be a
        # write in progress (no trailing newline yet). A line without '\n'
        # that is the final line = incomplete write, NOT corruption — skip
        # it (plugins fire on every tool call; reading mid-write is normal).
        # All COMPLETE lines are validated strictly.
        complete = lines[:-1] if lines and not lines[-1].endswith("\n") else lines
        for i, line in enumerate(complete):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  ✗ line {i}: invalid JSON — {e}", file=sys.stderr)
                return 1
            for field in ("ts", "instrument", "hook", "action", "result"):
                if field not in r:
                    print(f"  ✗ line {i}: missing field '{field}'", file=sys.stderr)
                    return 1
            ts = r["ts"]
            if not ts.endswith("Z") or len(ts) < 20:
                print(f"  ✗ line {i}: ts not ISO 8601 UTC ({ts})", file=sys.stderr)
                return 1
            seen.add(r["instrument"])
    except OSError as e:
        print(f"  ✗ cannot read {path}: {e}", file=sys.stderr)
        return 1

    missing = []
    for inst in declared.split():
        if inst not in seen:
            missing.append(inst)
    if missing:
        for inst in missing:
            print(f"  ✗ instrument '{inst}' NEVER fired — dead plugin?", file=sys.stderr)
        return 1
    print(f"  ✓ {n} records, {len(seen)} instruments, all declared present", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: check_agent_log.py <log.jsonl> <'declared instruments'>", file=sys.stderr)
        sys.exit(2)
    sys.exit(validate(sys.argv[1], sys.argv[2]))