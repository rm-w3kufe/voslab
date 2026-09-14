#!/usr/bin/env python3
"""vosi — Audit trail CLI for vOSlab.

Provides visibility into the 4-layer audit trail:
  vosi traces   — recent decision traces
  vosi alerts   — recent alerts
  vosi health   — health history summary
  vosi status   — pipeline status (metrics + thresholds)
  vosi measure  — run latency benchmark
  vosi topology — infrastructure topology management

Usage:
    python3 system/kernel/vosi.py traces [--last N]
    python3 system/kernel/vosi.py alerts [--last N]
    python3 system/kernel/vosi.py health [--last N]
    python3 system/kernel/vosi.py status
    python3 system/kernel/vosi.py measure [--iterations N]
    python3 system/kernel/vosi.py topology status|validate|reconcile|lookup|nats-rules|events
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone

# Ensure kernel is importable
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("VOSLAB_PATH", str(ROOT))

STATE_DIR = ROOT / "state" / "rsi"


def cmd_traces(args):
    """Show recent decision traces."""
    n = args.get("last", 10)
    trace_file = STATE_DIR / "tree_traces.jsonl"
    if not trace_file.exists():
        print("No traces found. Run some evaluations first.")
        return

    lines = trace_file.read_text().strip().split("\n")
    lines = [l for l in lines if l]
    recent = lines[-n:]

    print(f"=== Last {len(recent)} traces (of {len(lines)} total) ===\n")
    for line in recent:
        try:
            t = json.loads(line)
            ts = t.get("ts", "?")[:19]
            truth = t.get("final_truth", "?")
            source = t.get("final_source", "?")
            nodes = t.get("total_nodes", 0)
            latency = t.get("total_latency_ms", 0)
            shape = t.get("tree_shape", "?")[:50]
            print(f"  {ts} | {truth:>8} | {source:>20} | nodes={nodes} | {latency:.1f}ms | {shape}")
        except (json.JSONDecodeError, KeyError):
            continue


def cmd_alerts(args):
    """Show recent alerts."""
    n = args.get("last", 10)
    alert_file = STATE_DIR / "alerts.jsonl"
    if not alert_file.exists():
        print("No alerts found.")
        return

    lines = alert_file.read_text().strip().split("\n")
    lines = [l for l in lines if l]
    recent = lines[-n:]

    print(f"=== Last {len(recent)} alerts (of {len(lines)} total) ===\n")
    for line in recent:
        try:
            a = json.loads(line)
            ts = a.get("ts", "?")[:19]
            level = a.get("level", "?")
            atype = a.get("alert_type", "?")
            source = a.get("source", "?")
            detail = a.get("detail", "?")[:50]
            trace_id = a.get("trace_id", "")
            marker = {"info": "ℹ", "warning": "⚠", "critical": "🔴"}.get(level, "?")
            tid = f" trace={trace_id[:12]}" if trace_id else ""
            print(f"  {ts} | {marker} {level:>8} | {atype:>20} | {detail}{tid}")
        except (json.JSONDecodeError, KeyError):
            continue


def cmd_health(args):
    """Show health history summary."""
    n = args.get("last", 10)
    health_file = ROOT / "state" / "health_history.jsonl"
    if not health_file.exists():
        print("No health history found.")
        return

    lines = health_file.read_text().strip().split("\n")
    lines = [l for l in lines if l]
    recent = lines[-n:]

    print(f"=== Last {len(recent)} health entries (of {len(lines)} total) ===\n")
    for line in recent:
        try:
            h = json.loads(line)
            ts = h.get("ts", "?")[:19]
            traces = h.get("traces", {})
            total = traces.get("total", 0)
            pass_rate = traces.get("pass_rate", 0)
            atts = h.get("attestations", {})
            att_rate = atts.get("verification_rate", 0)
            patterns = h.get("patterns", [])
            print(f"  {ts} | traces={total} pass={pass_rate:.0%} attest={att_rate:.0%} patterns={len(patterns)}")
        except (json.JSONDecodeError, KeyError):
            continue


def cmd_status(args):
    """Show pipeline status: metrics + thresholds."""
    from rsi_cycle import RSICycle
    cycle = RSICycle()
    stats = cycle.get_stats()

    print("=== Audit Pipeline Status ===\n")

    # Metrics
    m = stats.get("audit_metrics", {})
    print("Metrics:")
    print(f"  evals_total:       {m.get('evals_total', 0)}")
    print(f"  traces_captured:   {m.get('traces_captured', 0)}")
    print(f"  traces_lost:       {m.get('traces_lost', 0)}")
    print(f"  attestations_signed: {m.get('attestations_signed', 0)}")
    print(f"  attestations_lost: {m.get('attestations_lost', 0)}")

    loss_rate = 0
    if m.get('evals_total', 0) > 0:
        loss_rate = m.get('traces_lost', 0) / m.get('evals_total', 0)
    print(f"  loss_rate:         {loss_rate:.1%}")

    # Thresholds
    from alerting import DEFAULT_THRESHOLDS
    print("\nAlerting Thresholds:")
    for k, v in DEFAULT_THRESHOLDS.items():
        print(f"  {k}: {v}")

    # Faults (with auto-expiry: entries older than 7 days are pruned)
    fault_file = ROOT / "state" / "faults" / "detected_faults.json"
    if fault_file.exists():
        try:
            faults = json.loads(fault_file.read_text())
            if isinstance(faults, dict):
                faults = list(faults.values())
            now = datetime.now(timezone.utc)
            fresh = []
            stale = 0
            for f in faults:
                last = f.get("last_seen") or f.get("detected_at") or ""
                if last:
                    try:
                        age = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
                        if age > 7:
                            stale += 1
                            continue
                    except Exception:
                        pass
                fresh.append(f)
            if stale:
                fault_file.write_text(json.dumps({f["fault_id"]: f for f in fresh}, indent=2, default=str))
                print(f"\nFaults pruned: {stale} stale entries removed (>7d)")
            active = [f for f in fresh if f.get("status") == "active"]
            print(f"\nActive Faults: {len(active)}")
            for f in active[:5]:
                print(f"  {f.get('fault_id', '?')} — {f.get('status', '?')} (count={f.get('count', 0)})")
        except Exception:
            print("\nActive Faults: (unreadable)")
    else:
        print("\nActive Faults: 0")


def cmd_measure(args):
    """Run latency benchmark."""
    from measure_latency import measure
    result = measure(args.get("iterations", 100))

    print(f"=== Latency Benchmark ===")
    print(f"N={result['n']}")
    print(f"min={result['min_ms']}ms  max={result['max_ms']}ms  avg={result['avg_ms']}ms  stdev={result['stdev_ms']}ms")
    print(f"p50={result['p50_ms']}ms  p95={result['p95_ms']}ms  p99={result['p99_ms']}ms")
    print()
    for bucket, count in result["distribution"].items():
        bar = "#" * count
        print(f"  {bucket:>8}: {count:3d} {bar}")


def cmd_topology(args):
    """Topology management — delegates to topology_cli."""
    sys.path.insert(0, str(ROOT))
    from topology_cli import cmd_status, cmd_validate, cmd_reconcile, cmd_lookup, cmd_nats_rules, cmd_events

    sub = args.get("sub", "status")
    sub_cmds = {
        "status": cmd_status,
        "validate": cmd_validate,
        "reconcile": cmd_reconcile,
        "lookup": cmd_lookup,
        "nats-rules": cmd_nats_rules,
        "events": cmd_events,
    }
    if sub in sub_cmds:
        sub_cmds[sub](args)
    else:
        print("Usage: vosi topology <subcommand>")
        print()
        print("Subcommands:")
        print("  status              Show topology status")
        print("  validate            Validate topology.json")
        print("  reconcile [--dry-run]  Reconcile desired vs actual")
        print("  lookup <name|id>    Look up service or container")
        print("  nats-rules          Show NATS whitelist")
        print("  events [--tail N]   Show recent events")


COMMANDS = {
    "traces": cmd_traces,
    "alerts": cmd_alerts,
    "health": cmd_health,
    "status": cmd_status,
    "measure": cmd_measure,
    "topology": cmd_topology,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: vosi <command> [options]")
        print()
        print("Commands:")
        print("  traces [--last N]   Show recent decision traces")
        print("  alerts [--last N]   Show recent alerts")
        print("  health [--last N]   Show health history")
        print("  status              Pipeline status + metrics")
        print("  measure [--iterations N]  Run latency benchmark")
        print("  topology [sub]      Topology management")
        sys.exit(1)

    cmd = sys.argv[1]
    args = {}
    i = 2

    # Topology subcommand: vosi topology status|validate|reconcile|...
    if cmd == "topology" and i < len(sys.argv):
        args["sub"] = sys.argv[i]
        i += 1

    while i < len(sys.argv):
        if sys.argv[i] == "--last" and i + 1 < len(sys.argv):
            args["last"] = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--iterations" and i + 1 < len(sys.argv):
            args["iterations"] = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--dry-run":
            args["dry_run"] = True
            i += 1
        elif sys.argv[i] == "--json":
            args["json"] = True
            i += 1
        elif sys.argv[i] == "--tail" and i + 1 < len(sys.argv):
            args["tail"] = int(sys.argv[i + 1])
            i += 2
        elif cmd == "topology" and args.get("sub") == "lookup" and "query" not in args:
            args["query"] = sys.argv[i]
            i += 1
        else:
            i += 1

    COMMANDS[cmd](args)


if __name__ == "__main__":
    main()
