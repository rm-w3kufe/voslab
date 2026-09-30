#!/usr/bin/env python3
"""RSI activation health check (guard G-RSI-ACTIVATION).

Verifies that an S5-approved predicate survives process boundaries and
evaluates with real context:
  1. Fresh RSICycle registers fix_task_has_work (activated queue entry
     must reload — FND-RSI-ACTIVATION-EPHEMERAL-01).
  2. Evaluation with adjustment_needed context yields TRUE
     (context passthrough — FND-RSI-CTX-PASSTHROUGH-BROKEN-01).
  3. fix_op_AND (never approved) stays unregistered (approval gate).
  4. L4_AUTO ceiling stays False (no auto-activation).

Prints a single JSON line: {"status": "ok"|"fail", ...}. rc 0/1.
"""
import json
import sys
from pathlib import Path

VOSLAB = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VOSLAB / "system" / "kernel"))


def main() -> int:
    out = {"status": "fail", "checks": {}}
    try:
        from rsi_cycle import RSICycle
        import rsi_cycle

        cycle = RSICycle()
        node = {"predicate": "fix_task_has_work", "inject_context": True}
        on = cycle.engine.evaluate(
            node, {"adjustment_needed": True}, enforce_limits=True
        )
        out["checks"]["registered"] = True
        out["checks"]["effect_on"] = str(on.truth)

        if str(on.truth) != "Truth.TRUE" or not on.certified:
            out["fail_reason"] = "fix_task_has_work did not evaluate TRUE with ctx"
            print(json.dumps(out))
            return 1

        try:
            cycle.engine.evaluate(
                {"predicate": "fix_op_AND", "inject_context": True},
                {}, enforce_limits=True,
            )
            out["fail_reason"] = "fix_op_AND registered without approval"
            print(json.dumps(out))
            return 1
        except ValueError:
            out["checks"]["unapproved_absent"] = True

        if rsi_cycle.L4_AUTO is not False:
            out["fail_reason"] = f"L4_AUTO={rsi_cycle.L4_AUTO!r} (must be False)"
            print(json.dumps(out))
            return 1
        out["checks"]["l4_auto_false"] = True

        out["status"] = "ok"
        print(json.dumps(out))
        return 0
    except Exception as e:  # pragma: no cover — guard failure path
        out["fail_reason"] = f"{type(e).__name__}: {e}"
        print(json.dumps(out))
        return 1


if __name__ == "__main__":
    sys.exit(main())
