"""topology.py — LXC topology range/anchors from the single source of truth (D-05).

Reads ``system/instance/lxc_topology.json`` — the declared LXC container ID
range (101-117) and role anchors for the n02 Proxmox host. Nothing in the
codebase may hardcode the range; consumers call these accessors instead
(debt D-05 / D16, docs/plans/instance_isolation_debt_register.vsm).

Usage:
    from vos_kernel.utils.topology import get_lxc_id_range, get_lxc_ids

    lo, hi = get_lxc_id_range()      # (101, 117)
    ids = get_lxc_ids()              # [101, 104, ..., 117]

All accessors fail loud (FileNotFoundError / ValueError / KeyError) if the
config is missing or malformed — a silent default would re-create the debt.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from vos_kernel.epistemic import repo_root

CONFIG_RELPATH = Path("system") / "instance" / "lxc_topology.json"


def _candidate_paths() -> list[Path]:
    """Config locations, in precedence order: env override, VOSLAB_PATH, repo root."""
    paths: list[Path] = []
    env_file = os.environ.get("VOSLAB_LXC_TOPOLOGY")
    if env_file:
        paths.append(Path(env_file))
    voslab = os.environ.get("VOSLAB_PATH")
    if voslab:
        paths.append(Path(voslab) / CONFIG_RELPATH)
    paths.append(repo_root() / CONFIG_RELPATH)
    paths.append(Path(__file__).resolve().parents[4] / CONFIG_RELPATH)
    # de-duplicate, keep order
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in paths:
        rp = p.absolute()
        if rp not in seen:
            seen.add(rp)
            uniq.append(rp)
    return uniq


def config_path() -> Path:
    """Return the resolved path of lxc_topology.json (fail loud if absent)."""
    env_file = os.environ.get("VOSLAB_LXC_TOPOLOGY")
    if env_file and not Path(env_file).is_file():
        raise FileNotFoundError(
            f"VOSLAB_LXC_TOPOLOGY points to missing file: {env_file}"
        )
    tried = _candidate_paths()
    for p in tried:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "lxc_topology.json not found (D-05 single source of truth). "
        f"Tried: {', '.join(str(p) for p in tried)}. "
        "Set VOSLAB_PATH or VOSLAB_LXC_TOPOLOGY to locate it."
    )


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(config_path(), encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"lxc_topology.json is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("lxc_topology.json: top level must be a JSON object")
    return data


def get_lxc_id_range() -> tuple[int, int]:
    """Declared (min, max) LXC container ID range as ints. Fail loud on bad data."""
    try:
        rng = _load()["lxc_ids"]
        lo, hi = rng["min"], rng["max"]
    except KeyError as e:
        raise ValueError(f"lxc_topology.json: missing lxc_ids.{e.args[0]}") from e
    if not (isinstance(lo, int) and isinstance(hi, int)):
        raise ValueError(f"lxc_topology.json: lxc_ids min/max must be ints, got {lo!r}/{hi!r}")
    if lo > hi:
        raise ValueError(f"lxc_topology.json: invalid range {lo}..{hi} (min > max)")
    return (lo, hi)


def get_lxc_ids() -> list[int]:
    """Explicit set of declared container IDs (sorted ints)."""
    raw = _load().get("lxc_ids", {}).get("ids")
    if not isinstance(raw, list) or not raw:
        raise ValueError("lxc_topology.json: lxc_ids.ids must be a non-empty list")
    ids: list[int] = []
    for v in raw:
        if not isinstance(v, int):
            raise ValueError(f"lxc_topology.json: container id must be int, got {v!r}")
        ids.append(v)
    lo, hi = get_lxc_id_range()
    out_of_range = [i for i in ids if not lo <= i <= hi]
    if out_of_range:
        raise ValueError(f"lxc_topology.json: ids {out_of_range} outside declared range {lo}..{hi}")
    return sorted(ids)


def is_valid_lxc_id(cid) -> bool:
    """True if cid (int or str) is a declared container ID of the topology."""
    try:
        v = int(cid)
    except (TypeError, ValueError):
        return False
    return v in get_lxc_ids()


def get_lxc_anchor(name: str) -> int:
    """Resolve a role/service anchor (e.g. 'nucleus', 'nats') to its container ID."""
    anchors = _load().get("anchors")
    if not isinstance(anchors, dict):
        raise ValueError("lxc_topology.json: missing 'anchors' object")
    try:
        value = anchors[name]
    except KeyError:
        raise KeyError(
            f"lxc_topology.json: unknown anchor {name!r} "
            f"(known: {', '.join(sorted(anchors))})"
        ) from None
    if not isinstance(value, int):
        raise ValueError(f"lxc_topology.json: anchor {name!r} must be an int id, got {value!r}")
    if not is_valid_lxc_id(value):
        raise ValueError(f"lxc_topology.json: anchor {name!r}={value} not in declared ids")
    return value


def reload() -> None:
    """Drop the cached config (for tests / after config edits)."""
    _load.cache_clear()
