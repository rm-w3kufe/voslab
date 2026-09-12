"""test_handler_states.py — PLC-001 thin slice: sidecar schema + dep graph.

Pure file reads (no imports, no spawns): every router handler id has a
declared state (enabled/version/depends_on), no orphans, deps resolve,
graph acyclic. Hermetic.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OP = ROOT / ".opencode" / "plugins" / "operational"
SIDECAR = OP / "handler_states.json"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
ID_RX = re.compile(r'id:\s*"([^"]+)"')


def _code_ids():
    ids = set()
    for p in list((OP / "handlers").glob("*.ts")) + [
            OP / "scenario-memory.ts", OP / "socratic-hook-engine.ts"]:
        if p.is_file():
            ids.update(ID_RX.findall(p.read_text(encoding="utf-8",
                                                 errors="replace")))
    return ids


def _sidecar():
    return json.loads(SIDECAR.read_text(encoding="utf-8"))


def test_sidecar_valid():
    sc = _sidecar()
    assert isinstance(sc.get("version"), int)
    assert isinstance(sc.get("handlers"), dict)


def test_every_handler_pinned():
    sc = _sidecar()["handlers"]
    missing = _code_ids() - set(sc)
    assert missing == set(), f"handlers without declared state: {missing}"


def test_no_orphan_entries():
    sc = _sidecar()["handlers"]
    orphans = set(sc) - _code_ids()
    assert orphans == set(), f"sidecar entries without code: {orphans}"


def test_entry_shapes():
    for hid, e in _sidecar()["handlers"].items():
        assert isinstance(e.get("enabled"), bool), hid
        assert SEMVER.match(e.get("version", "")), hid
        assert isinstance(e.get("depends_on"), list), hid


def test_deps_resolve_and_acyclic():
    handlers = _sidecar()["handlers"]
    for hid, e in handlers.items():
        for dep in e["depends_on"]:
            assert dep in handlers, f"{hid} -> unknown {dep}"
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}

    def visit(n, stack):
        color[n] = GRAY
        for dep in handlers[n]["depends_on"]:
            if color.get(dep, WHITE) == GRAY:
                raise AssertionError(
                    f"cycle: {' -> '.join([*stack, n, dep])}")
            if color.get(dep, WHITE) == WHITE:
                visit(dep, [*stack, n])
        color[n] = BLACK

    for hid in handlers:
        if color.get(hid, WHITE) == WHITE:
            visit(hid, [])
