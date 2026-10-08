#!/usr/bin/env python3
"""telemetry_ports_verify.py — executable verifier for state/telemetry_ports.json.

TELEMETRY-01 P2. Validates the declared contracts against the committed
evidence fixtures (state/fixtures/telemetry/):

  events.kernel_tick   -> kernel_tick_sample.jsonl   (5 live lines, envelope
                          + metrics + state, KernelMode enum, ranges)
  abreath.queue_up     -> port_manifest_sample.jsonl (feeders manifest:
  abreath.absorption                   value/provenance/source + exact
  abreath.cpu                          canon pressure 0.4q+0.3cpu+0.3(1-abs))

CWD-independent (ROOT derived from script location). Stdlib only.
Exit 0 iff every checked port's contract holds on every fixture line; exit 1
with a per-violation report otherwise. Used by checks/port-verified (pass
mode = real fixtures; fail mode = corrupted temp fixture must be rejected).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # .../vOSlab
REGISTRY = ROOT / "state" / "telemetry_ports.json"
FIX_DIR = ROOT / "state" / "fixtures" / "telemetry"
KERNEL_FIX = FIX_DIR / "kernel_tick_sample.jsonl"
MANIFEST_FIX = FIX_DIR / "port_manifest_sample.jsonl"

PROVENANCE = {"measured", "param", "synthetic", "scaffold"}
MODES = {"GOVERNED", "COMPLETE", "HALTED", "SURVIVAL"}
FEEDER_PORTS = ("abreath.queue_up", "abreath.absorption", "abreath.cpu")

viol: list[str] = []


def _is_num(x) -> bool:
    """number but NOT bool (bool subclasses int in Python)."""
    return type(x) is float or type(x) is int


def _need(d: dict, key: str, where: str):
    if key not in d:
        viol.append(f"{where}: missing key {key!r}")
        return None
    return d[key]


def _check_str(v, where: str, const=None, enum=None, non_empty=True):
    if not isinstance(v, str):
        viol.append(f"{where}: expected string, got {type(v).__name__}")
        return
    if const is not None and v != const:
        viol.append(f"{where}: expected const {const!r}, got {v!r}")
    if enum is not None and v not in enum:
        viol.append(f"{where}: {v!r} not in enum {sorted(enum)}")
    if non_empty and not v:
        viol.append(f"{where}: empty string")


def _check_num(v, where: str, lo=None, hi=None):
    if not _is_num(v):
        viol.append(f"{where}: expected number, got {type(v).__name__}")
        return
    if lo is not None and v < lo:
        viol.append(f"{where}: {v} < min {lo}")
    if hi is not None and v > hi:
        viol.append(f"{where}: {v} > max {hi}")


def _check_int(v, where: str, lo=None):
    if type(v) is not int:
        viol.append(f"{where}: expected integer, got {type(v).__name__}")
        return
    if lo is not None and v < lo:
        viol.append(f"{where}: {v} < min {lo}")


def _check_bool(v, where: str):
    if not isinstance(v, bool):
        viol.append(f"{where}: expected boolean, got {type(v).__name__}")


def check_kernel_tick_line(obj: dict, where: str) -> None:
    """Envelope + metrics + state per contract kernel_tick-1."""
    ts = _need(obj, "ts", where)
    if ts is not None:
        _check_str(ts, f"{where}.ts")
        # rfc3339 micros UTC: YYYY-MM-DDTHH:MM:SS.ffffffZ
        if not (len(ts) > 19 and ts.endswith("Z") and "T" in ts):
            viol.append(f"{where}.ts: not rfc3339-utc: {ts!r}")
    sid = _need(obj, "system_id", where)
    if sid is not None:
        _check_str(sid, f"{where}.system_id", const="vsf-nucleus")
    et = _need(obj, "event_type", where)
    if et is not None:
        _check_str(et, f"{where}.event_type", const="kernel_tick")
    st = _need(obj, "status", where)
    if st is not None:
        _check_str(st, f"{where}.status")
    ss = _need(obj, "signal_status", where)
    if ss is not None:
        _check_str(ss, f"{where}.signal_status")
    du = _need(obj, "duration_s", where)
    if du is not None:
        _check_num(du, f"{where}.duration_s", lo=0.0)

    m = _need(obj, "metrics", where)
    if not isinstance(m, dict):
        viol.append(f"{where}.metrics: expected object")
        return
    k = _need(m, "kernel", f"{where}.metrics")
    if k is not None:
        _check_str(k, f"{where}.metrics.kernel")
    for key in ("level", "tick"):
        v = _need(m, key, f"{where}.metrics")
        if v is not None:
            _check_int(v, f"{where}.metrics.{key}", lo=0)
    for key in ("spawned", "metamorphosed"):
        v = _need(m, key, f"{where}.metrics")
        if v is not None:
            _check_bool(v, f"{where}.metrics.{key}")

    s = _need(m, "state", f"{where}.metrics")
    if not isinstance(s, dict):
        viol.append(f"{where}.metrics.state: expected object")
        return
    for key in ("active", "policy_locked"):
        v = _need(s, key, f"{where}.state")
        if v is not None:
            _check_bool(v, f"{where}.state.{key}")
    for key, lo, hi in (("autonomy", 0.0, 1.0), ("integrity", 0.0, 1.0),
                        ("trust", 0.0, 1.0), ("entropy", 0.0, None),
                        ("complexity", None, None)):
        v = _need(s, key, f"{where}.state")
        if v is not None:
            _check_num(v, f"{where}.state.{key}", lo=lo, hi=hi)
    mode = _need(s, "mode", f"{where}.state")
    if mode is not None:
        _check_str(mode, f"{where}.state.mode", enum=MODES)
    tick = _need(s, "tick", f"{where}.state")
    if tick is not None:
        _check_int(tick, f"{where}.state.tick", lo=0)
    if "result" not in s:
        viol.append(f"{where}.state: missing key 'result'")


def _load_manifest(path: Path) -> dict:
    """Return feeders dict of the LAST line carrying one (init_step complete)."""
    feeders = None
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            viol.append(f"{path.name}:{i}: invalid json: {e}")
            continue
        m = obj.get("metrics")
        # init_step wraps: metrics = {step, metrics: <payload>}  (telemetry.rs:143)
        payload = m.get("metrics") if isinstance(m, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("feeders"), dict):
            feeders = payload["feeders"]
    return feeders or {}


def check_feeder(port: str, feeders: dict, where: str) -> None:
    """Shared manifest envelope + the per-port feeder entry."""
    if not feeders:
        viol.append(f"{where}: no feeders manifest found in {MANIFEST_FIX.name}")
        return
    # shared
    en = _need(feeders, "enabled", where)
    if en is not None:
        _check_bool(en, f"{where}.enabled")
    fd = _need(feeders, "feeds", where)
    if fd is not None:
        _check_int(fd, f"{where}.feeds", lo=0)
    weak = _need(feeders, "weakest", where)
    if weak is not None:
        _check_str(weak, f"{where}.weakest", enum=PROVENANCE)
    src = _need(feeders, "source", where)
    if src is not None:
        _check_str(src, f"{where}.source")

    key = port.split(".", 1)[1]           # queue_up | absorption | cpu
    entry = _need(feeders, key, where)
    if not isinstance(entry, dict):
        if entry is not None:
            viol.append(f"{where}.{key}: expected object, got {type(entry).__name__}")
        return
    val = _need(entry, "value", f"{where}.{key}")
    if val is not None:
        _check_num(val, f"{where}.{key}.value", lo=0.0, hi=1.0)
    prov = _need(entry, "provenance", f"{where}.{key}")
    if prov is not None:
        _check_str(prov, f"{where}.{key}.provenance", enum=PROVENANCE)
    esrc = _need(entry, "source", f"{where}.{key}")
    if esrc is not None:
        _check_str(esrc, f"{where}.{key}.source")

    # canon pressure — exact, applies to every feeder-port verdict
    press = _need(feeders, "pressure", where)
    if press is not None and all(
        isinstance(feeders.get(k), dict) and _is_num(feeders[k].get("value"))
        for k in ("queue_up", "absorption", "cpu")
    ):
        _check_num(press, f"{where}.pressure", lo=0.0, hi=1.0)
        if _is_num(press):
            q = feeders["queue_up"]["value"]
            c = feeders["cpu"]["value"]
            a = feeders["absorption"]["value"]
            expect = 0.4 * q + 0.3 * c + 0.3 * (1.0 - a)
            if abs(press - expect) > 1e-9:
                viol.append(
                    f"{where}.pressure: {press} != canon 0.4q+0.3cpu+0.3(1-abs) "
                    f"= {expect} (exact required)"
                )


def verify(port: str) -> int:
    if port == "events.kernel_tick":
        if not KERNEL_FIX.is_file():
            viol.append(f"missing fixture: {KERNEL_FIX}")
            return 1
        n = 0
        for i, line in enumerate(KERNEL_FIX.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                viol.append(f"{KERNEL_FIX.name}:{i}: invalid json: {e}")
                continue
            check_kernel_tick_line(obj, f"{KERNEL_FIX.name}:{i}")
            n += 1
        if n == 0:
            viol.append(f"{KERNEL_FIX.name}: no lines")
        print(f"  kernel_tick: {n} fixture lines checked")
    elif port in FEEDER_PORTS:
        if not MANIFEST_FIX.is_file():
            viol.append(f"missing fixture: {MANIFEST_FIX}")
            return 1
        feeders = _load_manifest(MANIFEST_FIX)
        check_feeder(port, feeders, port)
        print(f"  {port}: manifest entry checked")
    else:
        viol.append(f"unknown port: {port!r}")
        return 1
    return 0


def main() -> int:
    global KERNEL_FIX, MANIFEST_FIX
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="single port (default: all 4)")
    ap.add_argument("--fixtures", metavar="DIR",
                    help="override fixtures dir (fail-mode/NC: corrupted copy "
                         "must be REJECTED)")
    args = ap.parse_args()
    if args.fixtures:
        d = Path(args.fixtures)
        KERNEL_FIX = d / "kernel_tick_sample.jsonl"
        MANIFEST_FIX = d / "port_manifest_sample.jsonl"

    if not REGISTRY.is_file():
        print(f"FAIL: registry missing: {REGISTRY}", file=sys.stderr)
        return 1
    reg = json.loads(REGISTRY.read_text())
    known = {p["port"] for p in reg.get("ports", [])}
    ports = [args.port] if args.port else [
        "events.kernel_tick", "abreath.queue_up",
        "abreath.absorption", "abreath.cpu",
    ]
    for p in ports:
        if p not in known:
            print(f"FAIL: port {p!r} not in registry (known: {sorted(known)})",
                  file=sys.stderr)
            return 1

    for p in ports:
        verify(p)

    if viol:
        print(f"FAIL: telemetry_ports_verify — {len(viol)} violation(s):",
              file=sys.stderr)
        for v in viol:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print(f"PASS: telemetry_ports_verify — {len(ports)} port(s) match contract "
          f"on {KERNEL_FIX.name} + {MANIFEST_FIX.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
