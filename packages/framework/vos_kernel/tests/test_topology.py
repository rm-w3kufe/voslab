"""tests/test_topology.py — D-05: LXC topology single source of truth loader.

Covers: config file exists and parses, get_lxc_id_range matches the declared
range from the debt register (101-117), explicit id set is ints within the
range and consistent with root topology.json, anchors resolve to declared ids
and match topology.json roles/services, and missing config fails loud.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vos_kernel.epistemic import repo_root
from vos_kernel.utils import topology as topo_mod
from vos_kernel.utils.topology import (
    config_path,
    get_lxc_anchor,
    get_lxc_id_range,
    get_lxc_ids,
    is_valid_lxc_id,
)

DECLARED_RANGE = (101, 117)  # instance_isolation_debt_register.vsm: D16 (101-117)


@pytest.fixture(autouse=True)
def _reload_after_test():
    topo_mod.reload()
    yield
    topo_mod.reload()


def test_config_file_exists():
    """system/instance/lxc_topology.json exists at the declared location."""
    p = repo_root() / "system" / "instance" / "lxc_topology.json"
    assert p.is_file(), f"missing D-05 config: {p}"
    assert Path(config_path()).resolve() == p.resolve()


def test_range_matches_declared():
    """get_lxc_id_range() == declared range (101, 117) with int bounds."""
    lo, hi = get_lxc_id_range()
    assert (lo, hi) == DECLARED_RANGE
    assert isinstance(lo, int) and isinstance(hi, int)


def test_ids_are_ints_within_range():
    """Explicit id set: non-empty list of ints, all inside the declared range."""
    ids = get_lxc_ids()
    assert ids, "lxc_ids.ids must not be empty"
    assert all(isinstance(i, int) for i in ids)
    lo, hi = get_lxc_id_range()
    assert all(lo <= i <= hi for i in ids)
    assert ids == sorted(ids)


def test_ids_consistent_with_detailed_topology():
    """The declared set mirrors the containers in root topology.json (no drift)."""
    with open(repo_root() / "topology.json", encoding="utf-8") as f:
        detailed = json.load(f)
    detailed_ids = sorted(int(cid) for cid in detailed["containers"])
    assert get_lxc_ids() == detailed_ids


def _anchor_valid_in_detailed(anchor: str, cid: int, detailed: dict) -> bool:
    c = detailed["containers"][str(cid)]
    key = anchor.lower().replace("_", "-")
    name = c.get("name", "").lower()
    roles = [r.lower() for r in c.get("roles", [])]
    services = detailed.get("services", {})
    if key in services and int(services[key]["container"]) == cid:
        return True
    if key == name or key in roles:
        return True
    return any(r.replace("-", "") == key.replace("-", "") for r in roles)


def test_anchors_resolve_to_declared_ids():
    """Every anchor resolves to an int id inside the declared id set."""
    ids = set(get_lxc_ids())
    anchors = json.loads(config_path().read_text(encoding="utf-8"))["anchors"]
    assert anchors, "anchors must not be empty"
    for name in anchors:
        value = get_lxc_anchor(name)
        assert isinstance(value, int)
        assert value in ids, f"anchor {name}={value} not in declared ids"


def test_anchors_consistent_with_detailed_topology():
    """Each anchor maps to the same container as root topology.json (no drift)."""
    detailed = json.loads((repo_root() / "topology.json").read_text(encoding="utf-8"))
    anchors = json.loads(config_path().read_text(encoding="utf-8"))["anchors"]
    for name, cid in anchors.items():
        assert _anchor_valid_in_detailed(name, cid, detailed), (
            f"anchor {name}={cid} disagrees with topology.json "
            f"(container {detailed['containers'].get(str(cid), {}).get('name')})"
        )


def test_is_valid_lxc_id():
    """Valid accepts declared ids as int/str; rejects gaps and junk."""
    assert is_valid_lxc_id(101) is True
    assert is_valid_lxc_id("117") is True
    assert is_valid_lxc_id(102) is False  # unallocated gap
    assert is_valid_lxc_id(999) is False
    assert is_valid_lxc_id("not-a-number") is False


def test_unknown_anchor_fails_loud():
    """Unknown anchor raises KeyError listing the known ones."""
    with pytest.raises(KeyError, match="unknown anchor"):
        get_lxc_anchor("does-not-exist")


def test_missing_config_fails_loud(monkeypatch, tmp_path):
    """Missing config file raises FileNotFoundError, never a silent default."""
    topo_mod.reload()
    monkeypatch.setenv("VOSLAB_LXC_TOPOLOGY", str(tmp_path / "nope.json"))
    with pytest.raises(FileNotFoundError, match="VOSLAB_LXC_TOPOLOGY"):
        topo_mod.config_path()
    monkeypatch.delenv("VOSLAB_LXC_TOPOLOGY")
    # hide the real config from every candidate location
    monkeypatch.setattr(topo_mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(topo_mod, "CONFIG_RELPATH", Path("no") / "lxc_topology.json")
    topo_mod.reload()
    with pytest.raises(FileNotFoundError, match="lxc_topology.json not found"):
        topo_mod.config_path()


def test_malformed_config_fails_loud(monkeypatch, tmp_path):
    """A range whose min/max are not ints raises ValueError, not a fallback."""
    bad = tmp_path / "lxc_topology.json"
    bad.write_text(json.dumps({"lxc_ids": {"min": "101", "max": 117}}), encoding="utf-8")
    topo_mod.reload()
    monkeypatch.setenv("VOSLAB_LXC_TOPOLOGY", str(bad))
    topo_mod.reload()
    with pytest.raises(ValueError, match="must be ints"):
        get_lxc_id_range()
