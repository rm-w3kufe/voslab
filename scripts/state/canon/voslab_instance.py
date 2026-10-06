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

_STATE_CANON_FALLBACK = str(
    Path(__file__).resolve().parents[3]
    / "packages" / "public" / "state-canon-mcp")  # S5: vendored inside


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


def _filesig(*paths: Path) -> str:
    """F2 L1 content stamp: mtime_ns + size per file, `absent` if missing.

    Deliberately local (no state_canon import): this module must stay
    importable standalone. Only ever compared against ITSELF over time,
    so the format need not match any other provider's stamps.
    """
    parts: list[str] = []
    for p in paths:
        try:
            st = Path(p).stat()
        except OSError:
            parts.append(f"{Path(p).name}:absent")
        else:
            parts.append(f"{Path(p).name}:{st.st_mtime_ns}:{st.st_size}")
    return "|".join(parts)


def _version_of(provider: Any, domain: str) -> str | None:
    """Delegate version() down the view chain (absent → None = passthrough)."""
    fn = getattr(provider, "version", None)
    if not callable(fn):
        return None
    try:
        return fn(domain)
    except Exception:  # noqa: BLE001 — a broken version() must fail soft
        return None


# ── spec<->kernel domain (G-32: SPEC-KERNEL-DOMAIN-REGISTER paid) ──────────
# The six deviations hand-found during the 2026-08-07/09 certification and
# recorded in the compression ledger (the canonical store of those findings).
# Each record pins a ledger grep-token: evidence present right now ->
# status=known_deviation; gone (resolved upstream, ledger moved) ->
# evidence_missing, and the reconciler flags the registry as stale instead
# of silently claiming drift that no longer has a witness.
_SPEC_LEDGER = ("docs/spec_revision/ledger/compression-ledger-v1"
                "/compression_ledger.vsm")
SPEC_KERNEL_DEVIATIONS: tuple[dict, ...] = (
    {"id": "dev-a-breath", "subject": "A_breath",
     "kind": "terms_divergence",
     "token": "A_breath: kernel diverges in the THREE TERMS",
     "debt": "KERNEL-ABREATH-ALIGN"},
    {"id": "dev-cpu-pressure", "subject": "CPU_PRESSURE",
     "kind": "semantics_wrong",
     "token": "CPU_PRESSURE SEMANTICS WRONG", "debt": ""},
    {"id": "dev-sensor-priority", "subject": "sensor_priority",
     "kind": "inverted_order",
     "token": "SENSOR PRIORITY INVERTED", "debt": ""},
    {"id": "dev-eps-frontier", "subject": "eps_frontier",
     "kind": "derived_as_literal",
     "token": "\u03b5_frontier WRONG IN BOTH DOCUMENTS", "debt": ""},
    {"id": "dev-trust-update", "subject": "Def_TrustUpdate",
     "kind": "canon_defect",
     "token": "0.05 is UNREACHABLE", "debt": ""},
    {"id": "dev-ax-split-operator", "subject": "Ax_SplitOperator",
     "kind": "dangling_foundation",
     "token": "DANGLING FOUNDATION", "debt": ""},
)


def _spec_kernel_records(repo_dir: Path) -> list[dict]:
    """Live evidence check per deviation (fail-soft: no ledger -> all
    evidence_missing, never a crash — mirrors the sibling views)."""
    ledger = repo_dir / _SPEC_LEDGER
    try:
        lines = ledger.read_text(encoding="utf-8",
                                 errors="replace").splitlines()
    except OSError:
        lines = []
    records: list[dict] = []
    for d in SPEC_KERNEL_DEVIATIONS:
        line_no = next((i for i, raw in enumerate(lines, 1)
                        if d["token"] in raw), None)
        records.append({
            "id": d["id"],
            "subject": d["subject"],
            "kind": d["kind"],
            "status": ("known_deviation" if line_no is not None
                       else "evidence_missing"),
            "evidence_file": _SPEC_LEDGER,
            "evidence_line": line_no,
            "debt": d["debt"],
        })
    return records


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

    def version(self, domain: str) -> str | None:
        """F2 L1: claim_states backs on claims+certs; everything else
        delegates down the view chain."""
        if domain == "claim_states":
            return _filesig(self._dir / "claims.jsonl", self._dir / "certs.jsonl")
        return _version_of(self._base, domain)

    def __getattr__(self, name: str) -> Any:
        # Anything else the server might poke at forwards to the base
        # provider (deterministic delegation; raises the base's error).
        return getattr(self._base, name)


def _filter_records(records: list[dict], domain: str,
                    filter: dict[str, Any] | None) -> list[dict]:
    """Equality filter with unknown-field rejection (mirrors the base
    JsonStateProvider contract: silent typos must fail loudly)."""
    if not filter:
        return records
    known_fields = {k for r in records for k in r}
    unknown = set(filter) - known_fields
    if unknown and records:
        raise ValueError(
            f"unknown filter fields for {domain}: {sorted(unknown)}")
    return [r for r in records
            if all(r.get(k) == v for k, v in filter.items())]


class DeclaredWorkspacesView:
    """Duck-typed StateProvider view adding domain ``workspaces``.

    Serves state/workspaces.json (the D2 declared-workspace registry):
    id, root, kind, note, registered_at. Makes M7 ("writes observed
    outside the repo are declared") queryable from the canon instead of
    only from logs. Same freshness/fail-soft/filter contract as
    ClaimStatesProvider. Registry location: VOS_WORKSPACES_PATH env when
    set (tests/ops seam), else <repo>/state/workspaces.json anchored at
    the focus file's directory.
    """

    def __init__(self, base: Any, repo_dir: Path):
        self._base = base
        override = os.environ.get("VOS_WORKSPACES_PATH")
        self._file = (Path(override) if override
                      else repo_dir / "state" / "workspaces.json")
        self._records: list[dict] = []
        self._mtime: float | None = None

    def _reload_if_changed(self) -> None:
        try:
            mtime = self._file.stat().st_mtime
        except OSError:
            mtime = -1.0
        if mtime != self._mtime:
            self._records = self._build(mtime >= 0)
            self._mtime = mtime

    def _build(self, have_registry: bool) -> list[dict]:
        if not have_registry:
            return []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            entries = data.get("workspaces", [])
        except (OSError, ValueError, AttributeError):
            return []
        if not isinstance(entries, list):
            return []
        return [{
            "id": e.get("id"),
            "root": e.get("root"),
            "kind": e.get("kind"),
            "note": e.get("note", ""),
            "registered_at": e.get("registered_at", ""),
        } for e in entries if isinstance(e, dict)]

    def list_domains(self) -> list[str]:
        self._reload_if_changed()
        domains = list(self._base.list_domains())
        if "workspaces" not in domains:
            domains.append("workspaces")
        return domains

    def query(self, domain: str,
              filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain != "workspaces":
            return self._base.query(domain, filter)
        self._reload_if_changed()
        return _filter_records(self._records, domain, filter)

    def schema(self, domain: str) -> dict[str, str]:
        records = self.query(domain)
        return {k: type(v).__name__
                for r in records[:1] for k, v in r.items()}

    def version(self, domain: str) -> str | None:
        """F2 L1: workspaces backs on state/workspaces.json; else delegate."""
        if domain == "workspaces":
            return _filesig(self._file)
        return _version_of(self._base, domain)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


class EpistemicHealthView:
    """Duck-typed StateProvider view adding domain ``epistemic_health``.

    One record per guard in guards.jsonl, enriched with the findings it
    protects (F->G linkage made queryable: "which findings does this
    guard cover?"). Static definitions only — liveness comes from
    audit_guards runs, never from per-query execution (G-PANEL would take
    minutes). Same freshness/fail-soft/filter contract as siblings.
    """

    def __init__(self, base: Any, epistemic_dir: Path):
        self._base = base
        self._dir = epistemic_dir
        self._records: list[dict] = []
        self._mtimes: tuple[float, float] | None = None

    def _reload_if_changed(self) -> None:
        try:
            guards_m = (self._dir / "guards.jsonl").stat().st_mtime
            findings_m = (self._dir / "findings.jsonl").stat().st_mtime
        except OSError:
            guards_m = findings_m = -1.0
        if (guards_m, findings_m) != self._mtimes:
            self._records = self._build(guards_m >= 0)
            self._mtimes = (guards_m, findings_m)

    def _build(self, have_store: bool) -> list[dict]:
        if not have_store:
            return []
        guards = _read_jsonl(self._dir / "guards.jsonl")
        by_guard: dict[str, list[str]] = {}
        for f in _read_jsonl(self._dir / "findings.jsonl"):
            gid = f.get("guard")
            if isinstance(gid, str) and gid:
                by_guard.setdefault(gid, []).append(f.get("id"))
        return [{
            "id": g.get("id"),
            "artifact": g.get("artifact", ""),
            "covers": g.get("covers", ""),
            "findings": sorted(by_guard.get(g.get("id"), [])),
            "findings_count": len(by_guard.get(g.get("id"), [])),
            "updated_at": g.get("ts", ""),
        } for g in guards if g.get("id")]

    def list_domains(self) -> list[str]:
        self._reload_if_changed()
        domains = list(self._base.list_domains())
        if "epistemic_health" not in domains:
            domains.append("epistemic_health")
        return domains

    def query(self, domain: str,
              filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain != "epistemic_health":
            return self._base.query(domain, filter)
        self._reload_if_changed()
        return _filter_records(self._records, domain, filter)

    def schema(self, domain: str) -> dict[str, str]:
        records = self.query(domain)
        return {k: type(v).__name__
                for r in records[:1] for k, v in r.items()}

    def version(self, domain: str) -> str | None:
        """F2 L1: epistemic_health backs on guards+findings; else delegate."""
        if domain == "epistemic_health":
            return _filesig(self._dir / "guards.jsonl", self._dir / "findings.jsonl")
        return _version_of(self._base, domain)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


class SpecKernelView:
    """Duck-typed StateProvider view adding domain ``spec_kernel``.

    G-32 (SPEC-KERNEL-DOMAIN-REGISTER): the spec<->kernel deviations are
    queryable from the canon — ``state_query('spec_kernel')`` — instead of
    only from this tool's report. Records are the curated six (R10: the
    semantic form is not mechanically re-derivable — the ledger says so
    itself) with live evidence-line resolution. Freshness/fail-soft/filter
    contract identical to the sibling views.
    """

    def __init__(self, base: Any, repo_dir: Path):
        self._base = base
        self._repo = repo_dir
        self._records: list[dict] = []
        self._mtime: float | None = None

    def _reload_if_changed(self) -> None:
        try:
            mtime = (self._repo / _SPEC_LEDGER).stat().st_mtime
        except OSError:
            mtime = -1.0
        if mtime != self._mtime:
            self._records = _spec_kernel_records(self._repo)
            self._mtime = mtime

    def list_domains(self) -> list[str]:
        self._reload_if_changed()
        domains = list(self._base.list_domains())
        if "spec_kernel" not in domains:
            domains.append("spec_kernel")
        return domains

    def query(self, domain: str,
              filter: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if domain != "spec_kernel":
            return self._base.query(domain, filter)
        self._reload_if_changed()
        return _filter_records(self._records, domain, filter)

    def schema(self, domain: str) -> dict[str, str]:
        records = self.query(domain)
        return {k: type(v).__name__
                for r in records[:1] for k, v in r.items()}

    def version(self, domain: str) -> str | None:
        """F2 L1: spec_kernel backs on the compression ledger; else delegate."""
        if domain == "spec_kernel":
            return _filesig(self._repo / _SPEC_LEDGER)
        return _version_of(self._base, domain)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def load(path: str | Path):
    """Instance entrypoint: ``load(focus_json) -> (provider, reconcilers)``.

    The ARG is the same path the pre-EP-4 config already passed
    (current_focus.json); the epistemic store is derived as its
    sibling ``state/epistemic/`` (repo layout), the workspace registry
    as sibling ``state/workspaces.json`` (VOS_WORKSPACES_PATH wins when
    set). Views chain: base -> claim_states -> workspaces ->
    epistemic_health (each delegates unknown domains downward).
    """
    tasks_provider = _load_tasks_provider()
    focus_path = Path(path)
    base_provider, reconcilers = tasks_provider.load(focus_path)
    repo_dir = focus_path.parent
    epistemic_dir = repo_dir / "state" / "epistemic"
    provider = ClaimStatesProvider(base_provider, epistemic_dir)
    provider = DeclaredWorkspacesView(provider, repo_dir)
    provider = EpistemicHealthView(provider, epistemic_dir)
    provider = SpecKernelView(provider, repo_dir)

    # G-32: register the spec<->kernel Reconciler (state_verify/state_reconcile
    # cross-check). State-canon types imported HERE, not at module scope —
    # tasks_provider's bootstrap above has already put state_canon on the
    # path, preserving this module's import contract.
    from state_canon.reconcile import Drift, Reconciler

    def _spec_rule(declared: list[dict],
                   observed: list[dict]) -> list:
        """Each evidence-backed deviation IS drift: declared spec text vs
        observed kernel reality, witnessed at the ledger line."""
        obs = {o.get("id"): o for o in observed}
        out = []
        for d in declared:
            o = obs.get(d.get("id"), {})
            if o.get("status") == "known_deviation":
                debt = f", debt({d['debt']})" if d.get("debt") else ""
                out.append(Drift(
                    "rule_violation", str(d.get("subject")),
                    f"{d.get('subject')}: {d.get('kind')} — spec vs kernel "
                    f"divergence, evidence {d.get('evidence_file')}:"
                    f"{o.get('evidence_line')}{debt}",
                    {"record": o}))
        return out

    class SpecKernelReconciler(Reconciler):
        domain = "spec_kernel"
        key = "id"
        status_field = "status"
        active_values = frozenset({"known_deviation"})
        rules = [_spec_rule]

        def declared(self) -> list[dict]:
            # the registry's claim, independent of today's grep
            return [{**d, "status": "known_deviation",
                     "evidence_file": _SPEC_LEDGER, "evidence_line": None}
                    for d in SPEC_KERNEL_DEVIATIONS]

        def observe(self) -> list[dict]:
            # reality: does the witness still exist?
            return _spec_kernel_records(repo_dir)

    return provider, [*reconcilers, SpecKernelReconciler()]
