#!/usr/bin/env python3
"""covenant_cli.py — on-demand covenant evaluator (S3 seed on LXC 107).

Usage:
    python3 covenant_cli.py evaluate [--s5-trust F] [--autonomy F]
                                     [--pressure STR]
    python3 covenant_cli.py selftest

evaluate prints a JSON verdict and exits 0 (pass) / 2 (violations).
selftest runs fixed vectors (deterministic, no inputs needed).

Design note: on-demand, not a daemon loop. A daemon evaluating static
inputs would be theater; enforcement capability deployed + invoked per
event by callers (audit pipeline shells this CLI). Liveness is proven
by the hourly systemd timer running selftest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vos_kernel.covenant import CovenantEnforcer


def cmd_evaluate(args) -> int:
    enf = CovenantEnforcer()
    verdict = enf.evaluate(s5_trust=args.s5_trust,
                           op_autonomy=args.autonomy,
                           pressure=args.pressure)
    print(json.dumps({
        "passed": verdict.passed,
        "backend": enf._backend,
        "violations": [{"axiom": v.axiom, "message": v.message,
                        "severity": v.severity} for v in verdict.violations],
    }))
    return 0 if verdict.passed else 2


def cmd_selftest(_args) -> int:
    enf = CovenantEnforcer()
    # Fixed vectors: (s5_trust, autonomy, pressure, expect_pass)
    vectors = [
        (0.8, 0.5, None, True),           # nominal: pass
        (0.8, 0.5, "coercion", False),    # A0.1 pressure: violation
        (0.2, 0.1, None, False),          # TRUST: s5_trust < 0.3
        (0.5, 0.9, None, False),          # A5: autonomy > trust
    ]
    ok = True
    for s5, aut, pres, exp in vectors:
        got = enf.evaluate(s5_trust=s5, op_autonomy=aut,
                           pressure=pres).passed
        status = "ok" if got == exp else "MISMATCH"
        if got != exp:
            ok = False
        print(f"[{status}] s5={s5} aut={aut} pressure={pres} "
              f"-> passed={got} (expect {exp})")
    print(f"backend={enf._backend} selftest={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="S3 covenant evaluator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--s5-trust", type=float, default=0.8)
    ev.add_argument("--autonomy", type=float, default=0.5)
    ev.add_argument("--pressure", default=None)
    ev.set_defaults(func=cmd_evaluate)
    st = sub.add_parser("selftest")
    st.set_defaults(func=cmd_selftest)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
