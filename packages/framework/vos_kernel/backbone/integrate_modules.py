"""integrate_modules.py — A-8: push framework modules through the backbone.

Runs the full lifecycle (route → register → verify → load → evaluate →
activate → monitor) on the canonical entry module of each integrated
package, producing registration records (component_registry.json) and
BackboneEvent evidence (backbone_events.jsonl + backbone_status.json).

A-8 (backlog system_backlog.vsm, pedido S5 2026-09-30): register
trace_graph and claim_ingest in the execution channel so the system
invokes them through the canal — WITHOUT rewriting the modules (they
already work and carry their own tests).

Usage (from the workspace root):
    python3 -m vos_kernel.backbone.integrate_modules [--state-dir state]
                                                     [--module NAME]

Exit codes: 0 all modules integrated, 1 any lifecycle failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vos_kernel.backbone.backbone import Backbone
from vos_kernel.backbone.backbone_event import ComponentType

#: workspace root — parents[4] of .../packages/framework/vos_kernel/backbone/
WORKSPACE = Path(__file__).resolve().parents[4]

#: Canonical entry module per package (unique stems -> unique registry keys).
MODULES: dict[str, str] = {
    "trace_graph": "packages/framework/trace_graph/graph.py",
    "claim_ingest": "packages/framework/claim_ingest/pipeline.py",
    "round_runner": "packages/framework/vos_kernel/round_runner.py",  # EP-5 PRC
}


def integrate(
    state_dir: str | Path,
    only: str | None = None,
) -> dict[str, bool]:
    """Ingest each module through the full lifecycle. Returns per-module ok."""
    backbone = Backbone(state_dir=state_dir)
    selected = {only: MODULES[only]} if only else MODULES
    outcomes: dict[str, bool] = {}
    for name, rel in selected.items():
        path = WORKSPACE / rel
        result = backbone.ingest(
            path,
            ComponentType.SCRIPT,
            context={"module": name, "source": "A-8-integrate_modules"},
        )
        outcomes[name] = bool(result.success)
        if not result.success:
            print(
                f"FAIL {name}: {result.error} evidence={result.evidence}",
                file=sys.stderr,
            )
        else:
            print(f"OK   {name}: {rel} ({result.evidence.get('total_ms')}ms)")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", default=str(WORKSPACE / "state"))
    parser.add_argument("--module", choices=sorted(MODULES), default=None)
    args = parser.parse_args(argv)
    outcomes = integrate(args.state_dir, args.module)
    return 0 if all(outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
