"""voslab_instance — state-canon instance for vOSlab (EP-4 D3).

Delegates tasks/sessions/meta/focus to the stock ``tasks_provider.py``
(same ARG contract as before: the path to ``current_focus.json``, which
also anchors the co-located focus domain) and adds the ``claim_states``
domain: a LIVE view of ``state/epistemic/claims.jsonl`` + cert resolution,
so the epistemic lattice (UNKNOWN/DECLARED/OBSERVED/CERTIFIED/REFUTED) is
queryable from the canon via ``state_query('claim_states')`` instead of
only from local Python.

Design notes:
- Duck-typed provider (list_domains/query/schema) — the server never
  isinstance-checks, so this module needs NO import of state_canon at
  module scope; the only sys.path bootstrap happens inside ``load()``
  via the stock tasks_provider (read-only against ~/state-canon-mcp).
- claim_states reloads on mtime change of claims.jsonl OR certs.jsonl
  (cheap stat per query), mirroring JsonStateProvider freshness.
- Fail-soft on a missing store: an empty claim_states domain, never a
  crashed server (the canon must stay up when epistemic state is absent,
  e.g. in a fresh clone).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

_STATE_CANON_FALLBACK = "/home/rmw3/state-canon-mcp"


def _state_canon_path() -> Path:
    return Path(os.environ.get("STATE_CANON_PATH", _STATE_CANON_FALLBACK))


def _load_tasks_provider():
    """Import the stock tasks_provider.py by file path (read-only).

    Its own top-level sys.path bootstrap brings state_canon + vendored
    vslline into reach; we only register it under a private module name
    so the server's own module namespace stays clean.
    """
    path = _state_canon_path() / "instances" / "tasks_provider.py"
    if not path.is_file():
        raise FileNotFoundError(
            f"tasks_provider not found: {path} (set STATE_CANON_PATH?)")
    name = "voslab_tasks_provider"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load instance module: {path}")
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: tasks_provider defines @dataclass classes,
    # which look up cls.__module__ in sys.modules.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


class ClaimStatesProvider:
    """Duck-typed StateProvider view adding domain ``claim_states``.

    Delegates every other domain (and unknown attributes) to the base
    provider from tasks_provider.load().
    """

    def __init__(self, base: Any, epistemic_dir: Path):
        self._base = base
        self._dir = epistemic_dir
        self._records: list[dict] = []
        self._mtimes: tuple[float, float] | None = None

    # -- freshness -----------------------------------------------------------

    def _reload_if_changed(self) -> None:
        try:
            claims_m = (self._dir / "claims.jsonl").stat().st_mtime
            certs_m = (self._dir / "certs.jsonl").stat().st_mtime
        except OSError:
            claims_m = certs_m = -1.0
        if (claims_m, certs_m) != self._mtimes:
            self._records = self._build(claims_m >= 0)
            self._mtimes = (claims_m, certs_m)

    def _build(self, have_store: bool) -> list[dict]:
        if not have_store:
            return []
        claims = _read_jsonl(self._dir / "claims.jsonl")
        certs_by_id = {c.get("id"): c for c in _read_jsonl(self._dir
                                                            / "certs.jsonl")
                       if c.get("id")}
        records: list[dict] = []
        for c in claims:
            cert_ids = c.get("certs", []) or []
            verdicts = [certs_by_id[cid].get("verdict")
                        for cid in cert_ids if cid in certs_by_id]
            records.append({
                "id": c.get("id"),
                "type": c.get("type"),
                "subject": c.get("subject"),
                "risk": c.get("risk"),
                "status": c.get("status"),
                "certs": cert_ids,
                "cert_verdicts": verdicts,
                "resolvable": all(cid in certs_by_id for cid in cert_ids),
                "value": c.get("value"),
                "evidence": c.get("evidence"),
                "provenance": c.get("provenance"),
            })
        return records

    # -- StateProvider protocol ---------------------------------------------

    def list_domains(self) -> list[str]:
        self._reload_if_changed()
        domains = list(self._base.list_domains())
        if "claim_states" not in domains:
            domains.append("claim_states")
        return domains

    def query(self, domain: str,
              filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain != "claim_states":
            return self._base.query(domain, filter)
        self._reload_if_changed()
        records = self._records
        if filter:
            known_fields = {k for r in records for k in r}
            unknown = set(filter) - known_fields
            if unknown and records:
                raise ValueError(
                    f"unknown filter fields for {domain}: {sorted(unknown)}")
            records = [r for r in records
                       if all(r.get(k) == v for k, v in filter.items())]
        return records

    def schema(self, domain: str) -> dict[str, str]:
        records = self.query(domain)
        return {k: type(v).__name__
                for r in records[:1] for k, v in r.items()}

    def __getattr__(self, name: str) -> Any:
        # Anything else the server might poke at forwards to the base
        # provider (deterministic delegation; raises the base's error).
        return getattr(self._base, name)


def load(path: str | Path):
    """Instance entrypoint: ``load(focus_json) -> (provider, reconcilers)``.

    The ARG is the same path the pre-EP-4 config already passed
    (current_focus.json); the epistemic store is derived as its
    sibling ``state/epistemic/`` (repo layout).
    """
    tasks_provider = _load_tasks_provider()
    focus_path = Path(path)
    base_provider, reconcilers = tasks_provider.load(focus_path)
    epistemic_dir = focus_path.parent / "state" / "epistemic"
    provider = ClaimStatesProvider(base_provider, epistemic_dir)
    return provider, reconcilers
