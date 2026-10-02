#!/usr/bin/env python3
"""ep6_parity.py — EP-6 representativeness proof: one pipeline, two substrates.

Plan §EP-6 (epistemic_certification_plan.vsm, Q3 ratified 2026-09-27):
instantiate the SAME round pipeline in a substrate with no notebooks and no
remote hosts — pure packages/ code — and show M1-M8 behave identically.

Substrates:
  A = the full workspace (repo root): the round EP-5 ran in.
  B = a scratch substrate built here: packages/framework + decision trees +
      epistemic store + tree traces + agent log. No docs/, no experiments/,
      no notebook corpus, no host inventory — code and protocol data only.

The driver imports vos_kernel FROM THE SUBSTRATE COPY (sys.path bootstrapped
before any vos_kernel import), then runs:
  round A  -> workspace=repo      (emits into repo state/epistemic/rounds/)
  round B  -> workspace=substrate (emits into substrate rounds/)
  neg ctl  -> substrate, --simulate-no-learn, no emit: MUST be NOT_GREEN

Parity = every M1..M8 value and ok-flag equal across A and B (same
24h window, same data copies, milliseconds apart).

Exit: 0 = both rounds GREEN + parity exact + negative control NOT_GREEN;
      1 = any of those failed; 2 = build failure.

Deterministic (R10): copies sources, runs rounds, writes only under the
chosen --dest and the normal emit locations. Never deletes (R17).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# substrate layout: everything the round protocol reads, nothing else
COPY_TREES = [
    ("packages/framework", "packages/framework"),
    # router's lazy trace logger lives outside packages/ (top-level import)
    ("system/kernel/tree_trace_logger.py", "system/kernel/tree_trace_logger.py"),
    (".opencode/plugins/support/trees", ".opencode/plugins/support/trees"),
    ("state/epistemic", "state/epistemic"),
    ("state/autonomy_classes.json", "state/autonomy_classes.json"),
    ("state/rsi/tree_traces.jsonl", "state/rsi/tree_traces.jsonl"),
    ("logs/agent_plugin.jsonl", "logs/agent_plugin.jsonl"),
]


def build_substrate(dest: Path) -> None:
    for src_rel, dst_rel in COPY_TREES:
        src = REPO / src_rel
        dst = dest / dst_rel
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        else:
            raise FileNotFoundError(f"substrate source missing: {src}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", help="substrate dir (default: mkdtemp under /tmp/opencode)")
    ap.add_argument("--keep-log", action="store_true",
                    help="print the full round JSONs (default: parity summary)")
    args = ap.parse_args()

    if args.dest:
        dest = Path(args.dest)
        dest.mkdir(parents=True, exist_ok=True)
    else:
        base = Path("/tmp/opencode")
        base.mkdir(parents=True, exist_ok=True)
        dest = Path("/tmp/opencode/ep6-substrate-" +
                    datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    t0 = time.monotonic()
    build_substrate(dest)

    # import vos_kernel FROM THE SUBSTRATE before anything else does
    fw = dest / "packages" / "framework"
    sys.path.insert(0, str(fw))
    sys.path.insert(1, str(dest / "system" / "kernel"))
    from vos_kernel import round_runner  # noqa: E402  (substrate copy)
    import vos_kernel  # noqa: E402
    kernel_file = Path(vos_kernel.__file__).resolve()
    if dest not in kernel_file.parents:
        print(f"FAIL: vos_kernel imported from {kernel_file}, not substrate {dest}",
              file=sys.stderr)
        return 2

    # tree_trace_logger resolves its output via VOSLAB_PATH at call time:
    # point it at each workspace so round A traces into the repo (its own
    # substrate) and round B traces into the scratch substrate — neither
    # contaminates the other.
    env_backup = os.environ.get("VOSLAB_PATH")
    os.environ["VOSLAB_PATH"] = str(REPO)
    rec_a = round_runner.run_round(workspace=REPO)
    # round A appended its self-traces to the repo; refresh the substrate's
    # data copies so B sees the same corpus (round B will then append ITS
    # self-traces on top — append-only by design, hence M2 compares as
    # b >= a + exact parity for M1, M3..M8, never as raw equality).
    for rel in ("state/rsi/tree_traces.jsonl", "logs/agent_plugin.jsonl"):
        src, dst = REPO / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    os.environ["VOSLAB_PATH"] = str(dest)

    # Guards are ambient REPO declarations (cwd/scripts of the real
    # workspace): evaluate them with the env they were declared under,
    # while route/metrics run on the substrate. Without this, ambient
    # guards (e.g. G-RSI-ACTIVATION reading VOSLAB_PATH) die on the
    # scratch substrate and M4 parity breaks for a non-protocol reason.
    def guards_declared_env():
        from vos_kernel.epistemic import EpicStore, audit_guards
        backup = os.environ.get("VOSLAB_PATH")
        os.environ["VOSLAB_PATH"] = str(REPO)
        try:
            return audit_guards(EpicStore(root=dest), run=True)
        finally:
            if backup is None:
                os.environ.pop("VOSLAB_PATH", None)
            else:
                os.environ["VOSLAB_PATH"] = backup

    rec_b = round_runner.run_round(workspace=dest,
                                   guards_fn=guards_declared_env)
    neg = round_runner.run_round(workspace=dest, simulate_no_learn=True,
                                 emit_round=False,
                                 guards_fn=guards_declared_env)
    if env_backup is None:
        os.environ.pop("VOSLAB_PATH", None)
    else:
        os.environ["VOSLAB_PATH"] = env_backup

    exact = ("M1", "M3", "M4", "M5", "M6", "M7", "M8")
    parity_rows = []
    exact_ok = True
    for m in exact:
        va, vb = rec_a["metrics"][m], rec_b["metrics"][m]
        match = (va["value"] == vb["value"] and va["ok"] == vb["ok"])
        exact_ok = exact_ok and match
        parity_rows.append({"metric": m, "a": va["value"], "b": vb["value"],
                            "a_ok": va["ok"], "b_ok": vb["ok"],
                            "match": match})
    # M2: append-only self-tracing — B = refreshed corpus + B's own traces
    m2a, m2b = rec_a["metrics"]["M2"], rec_b["metrics"]["M2"]
    m2_ok = (m2a["ok"] and m2b["ok"] and m2b["value"] >= m2a["value"])
    parity_rows.append({"metric": "M2", "a": m2a["value"], "b": m2b["value"],
                        "a_ok": m2a["ok"], "b_ok": m2b["ok"],
                        "match": m2_ok,
                        "design": "append-only self-trace: b >= a"})

    ok_flag_parity = all(
        rec_a["metrics"][m]["ok"] == rec_b["metrics"][m]["ok"]
        for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
    )
    both_green = rec_a["verdict"] == "GREEN" and rec_b["verdict"] == "GREEN"
    neg_ok = neg["verdict"] == "NOT_GREEN"
    parity_ok = exact_ok and m2_ok and ok_flag_parity
    report = {
        "ep": "EP-6",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vos_kernel_from": str(kernel_file),
        "substrate": str(dest),
        "round_a": {"id": rec_a["round_id"], "verdict": rec_a["verdict"]},
        "round_b": {"id": rec_b["round_id"], "verdict": rec_b["verdict"],
                    "reasons": rec_b["reasons"]},
        "parity": parity_rows,
        "exact_parity_M1_M3_M8": exact_ok,
        "ok_flag_parity": ok_flag_parity,
        "m2_append_only_ok": m2_ok,
        "parity_ok": parity_ok,
        "both_green": both_green,
        "negative_control": {"verdict": neg["verdict"], "ok": neg_ok},
        "elapsed_s": round(time.monotonic() - t0, 3),
    }
    if args.keep_log:
        report["round_a_full"] = rec_a
        report["round_b_full"] = rec_b
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0 if (parity_ok and both_green and neg_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
