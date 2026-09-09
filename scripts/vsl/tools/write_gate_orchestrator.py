#!/usr/bin/env python3
"""write_gate_orchestrator.py — run every registered write-time gate on a file.

design: docs/spec_revision/system/s5-policy/agent-policy/agent-write-gates-v1/write_gates.vsm
(AGENT-WRITE-GATES-v1, S5 rmw3 2026-08-17). R16_impl_with_design.

WHY (lesson DAEMON-GATE-AFTER-EARLY-EXIT-2026-08-17): gates used to be
injected ad-hoc into the daemon script. Each new policy collided with the
base flow (an early `exit 0` on the base check silently killed the injected
gate), with the observer's label (the plugin wrapped every failure as
[DEMONIO R18], hiding the real cause), and with scope (corpus scan per
write instead of per-file). This orchestrator makes the failure mode
STRUCTURALLY impossible:

  * it reads the registry (write_gates.vsm) — the ONLY source of truth
    for which gates run, in what order, with which labels
  * it runs EVERY gate INDEPENDENTLY — gate N never sees gate M's exit
    code, so no gate can be killed by another's early-exit
  * it labels the CAUSE: each gate carries its own [DEMONIO <label>]
    from the registry; the orchestrator does not invent labels
  * write-time gates MUST be mode=per-file (O(1), R18 latency) — the
    orchestrator refuses corpus-mode gates at write time
  * ADDING a policy = registering a gate in write_gates.vsm; the daemon
    script and this orchestrator are NOT edited.

Exit semantics:
  * 0 — no gate blocked (advisory reports may exist; they are printed
        but do not fail the write)
  * 1 — at least one gate blocked; stderr carries EVERY blocked gate's
        report with its own [DEMONIO <label>] tag, in registry order
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "docs/spec_revision/system/s5-policy/agent-policy/agent-write-gates-v1/write_gates.vsm"


class Gate:
    def __init__(self, name: str, raw: str):
        self.name = name
        # minimal structural parse of the gate(...) block inside the VSL
        # map. Fields are `key: value,` or `key: "value",` — extract by
        # regex over the block text. If a required field is missing we
        # FAIL LOUD (block): a mis-registered gate is a policy defect.
        self.cmd = self._field(raw, "cmd")
        self.mode = self._field(raw, "mode", default="per-file")
        self.label = self._field(raw, "label", default=name.upper())
        self.block_on = self._field(raw, "block_on", default="nonzero")
        self.advisory = self._field(raw, "advisory", default="false") == "true"
        self.owner = self._field(raw, "owner", default="?")
        self.desc = self._field(raw, "desc", default="")

    @staticmethod
    def _field(raw: str, key: str, default: str | None = None) -> str | None:
        m = re.search(rf"^\s*{re.escape(key)}:\s*(.*?),?\s*$", raw, re.M)
        if not m:
            return default
        v = m.group(1).strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        return v

    def blocks_on(self, rc: int, output: str) -> bool:
        """Interpret block_on: 'nonzero' | 'contains:<marker>'."""
        if self.block_on == "nonzero":
            return rc != 0
        marker = self.block_on.removeprefix("contains:")
        return marker in output

    def cmd_with(self, path: str) -> list[str]:
        parts = self.cmd.split()
        exe = parts[0]
        if exe.startswith("python3"):
            return ["python3", str(ROOT / parts[1])] + parts[2:] + [path]
        return [str(ROOT / exe)] + parts[1:] + [path]


def load_gates() -> list[Gate]:
    text = REGISTRY.read_text(encoding="utf-8")
    blocks = re.findall(r'gate\("([^"]+)"\)\s*\{([^}]*)\}', text)
    gates = [Gate(n, b) for n, b in blocks]
    if not gates:
        print("write_gate_orchestrator: registry has NO gates — a write-time "
              "daemon that verifies nothing is a policy breach. Fix "
              "write_gates.vsm.", file=sys.stderr)
        sys.exit(1)
    return gates


def main() -> int:
    # __list — machine-readable gate census for checks/write-gates-valid:
    # one line per gate, pipe-separated fields. This is the SAME parse the
    # orchestrator runs for verification, so the check and the daemon can
    # never disagree about which gates exist.
    if len(sys.argv) == 2 and sys.argv[1] == "__list":
        gates = load_gates()
        for g in gates:
            print(f"{g.name}|{g.cmd}|{g.mode}|{g.label}|{g.block_on}|{g.advisory}")
        return 0

    if len(sys.argv) != 2:
        print("usage: write_gate_orchestrator.py <file.vsm>", file=sys.stderr)
        return 2
    path = sys.argv[1]

    gates = load_gates()
    blocked: list[tuple[Gate, int, str]] = []
    advisories: list[str] = []

    for g in gates:
        if g.mode != "per-file":
            # write-time must be per-file (O(1), R18 latency). A corpus
            # gate at write time is a mis-registration — fail loud.
            print(f"write_gate_orchestrator: gate '{g.name}' has mode={g.mode} "
                  "— write-time gates MUST be per-file (O(1)). Fix "
                  "write_gates.vsm.", file=sys.stderr)
            return 1
        try:
            p = subprocess.run(g.cmd_with(path), capture_output=True,
                               text=True, timeout=180, cwd=ROOT)
        except (subprocess.TimeoutExpired, OSError) as e:
            blocked.append((g, 124, f"gate error: {e}"))
            continue
        out = (p.stdout or "") + (p.stderr or "")
        # ALWAYS report the gate's output — the agent must see what the
        # conformance daemon found, even when nothing blocks (mid-flight
        # grammar, advisory reports). Observation is the cycle.
        if out.strip():
            print(f"[{g.label}] {out.strip()}", file=sys.stderr)
        # block only when the gate's contract says so: advisory gates never
        # block; contains:<marker> gates block only on the marker;
        # nonzero gates block on any non-zero exit.
        if g.advisory:
            continue
        if g.blocks_on(p.returncode, out):
            blocked.append((g, p.returncode, out.strip()))

    if blocked:
        for g, rc, out in blocked:
            print(f"\n[DEMONIO {g.label}] gate '{g.name}' blocked "
                  f"(rc={rc}):", file=sys.stderr)
            if out:
                print(f"{out}", file=sys.stderr)
            if g.desc:
                print(f"  — {g.desc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())