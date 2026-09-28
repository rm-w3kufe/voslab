"""EP-4 D3 tests — state-canon composite instance (claim_states domain).

Loads scripts/state/canon/voslab_instance.py by path (the exact way the
MCP server does) and exercises: domain registration, live reload, cert
resolution, filter semantics, base delegation, and a read-only smoke on
the REAL epistemic store.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from vos_kernel.epistemic import EpicStore, repo_root

INSTANCE_PATH = (repo_root() / "scripts" / "state" / "canon"
                 / "voslab_instance.py")


def _load_instance_module():
    name = "voslab_instance_under_test"
    spec = importlib.util.spec_from_file_location(name, INSTANCE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # before exec (dataclass-safe pattern)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def instance():
    return _load_instance_module()


@pytest.fixture()
def world(tmp_path: Path):
    """tmp project layout: current_focus.json + state/epistemic stores."""
    focus = tmp_path / "current_focus.json"
    focus.write_text(json.dumps([
        {"ref": "T-1", "status": "active", "updated_at": "2026-09-27T10:00:00Z"},
    ]))
    epi = tmp_path / "state" / "epistemic"
    epi.mkdir(parents=True)
    claims = [
        {"id": "C-obs", "type": "conformance", "subject": "a.vsm",
         "risk": "delivery", "status": "OBSERVED", "certs": ["CRT-1"],
         "provenance": "test", "value": "abc", "evidence": "m.json"},
        {"id": "C-ref", "type": "conformance", "subject": "b.vsm",
         "risk": "delivery", "status": "REFUTED", "certs": ["CRT-1", "CRT-2"],
         "provenance": "test", "value": "def", "evidence": "m.json"},
        {"id": "C-orphan", "type": "number", "subject": "c.vsm",
         "risk": "internal", "status": "OBSERVED", "certs": ["CRT-LOST"],
         "provenance": "test"},
    ]
    certs = [
        {"id": "CRT-1", "verdict": "pass", "class": "IDENTITY"},
        {"id": "CRT-2", "verdict": "fail", "class": "IDENTITY"},
    ]
    (epi / "claims.jsonl").write_text(
        "\n".join(json.dumps(c) for c in claims) + "\n")
    (epi / "certs.jsonl").write_text(
        "\n".join(json.dumps(c) for c in certs) + "\n")
    return tmp_path, focus, epi


def test_load_returns_provider_and_reconcilers(instance, world):
    _, focus, _ = world
    provider, reconcilers = instance.load(str(focus))
    assert hasattr(provider, "query") and hasattr(provider, "list_domains")
    assert isinstance(reconcilers, list) and len(reconcilers) >= 1


def test_domains_include_claim_states_and_base(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    domains = provider.list_domains()
    assert "claim_states" in domains
    assert "focus" in domains          # base keeps its domains
    assert "tasks" in domains          # base keeps its domains


def test_claim_states_records_and_resolution(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    records = provider.query("claim_states")
    assert [r["id"] for r in records] == ["C-obs", "C-ref", "C-orphan"]
    by_id = {r["id"]: r for r in records}
    assert by_id["C-obs"]["status"] == "OBSERVED"
    assert by_id["C-obs"]["cert_verdicts"] == ["pass"]
    assert by_id["C-obs"]["resolvable"] is True
    assert by_id["C-ref"]["cert_verdicts"] == ["pass", "fail"]
    assert by_id["C-orphan"]["resolvable"] is False  # CRT-LOST missing


def test_claim_states_live_reload(instance, world):
    import os
    _, focus, epi = world
    provider, _ = instance.load(str(focus))
    assert len(provider.query("claim_states")) == 3
    claims_file = epi / "claims.jsonl"
    with claims_file.open("a") as f:
        f.write(json.dumps({"id": "C-new", "type": "decision",
                            "subject": "d.vsm", "risk": "exploratory",
                            "status": "DECLARED", "certs": [],
                            "provenance": "test"}) + "\n")
    # force a distinct mtime: coarse-grained filesystems can tie the
    # fixture-write and append timestamps inside one tick (deterministic
    # instead of relying on wall-clock sleeps).
    st = claims_file.stat()
    os.utime(claims_file, ns=(st.st_atime_ns + 1_000_000,
                              st.st_mtime_ns + 1_000_000))
    records = provider.query("claim_states")
    assert len(records) == 4            # mtime reload, no restart needed
    assert records[-1]["id"] == "C-new"


def test_claim_states_filter_and_unknown_field(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    refuted = provider.query("claim_states", {"status": "REFUTED"})
    assert [r["id"] for r in refuted] == ["C-ref"]
    with pytest.raises(ValueError):
        provider.query("claim_states", {"no_such_field": 1})


def test_base_delegation_intact(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    # focus domain still served by the base provider (delegation)
    focus_records = provider.query("focus")
    assert focus_records and focus_records[0]["ref"] == "T-1"
    # unknown attribute forwards to base (schema comes from StateProvider)
    assert provider.schema("claim_states")["status"] == "str"


def test_missing_epistemic_store_is_fail_soft(instance, tmp_path: Path):
    focus = tmp_path / "current_focus.json"  # no state/epistemic at all
    focus.write_text("[]")
    provider, _ = instance.load(str(focus))
    assert provider.query("claim_states") == []   # empty domain, no crash
    assert "claim_states" in provider.list_domains()


def test_real_store_read_only_smoke(instance):
    """Declarative smoke against the real repo (no writes): counts match."""
    store = EpicStore()
    real_claims = len(store.load("claims"))
    focus = repo_root() / "current_focus.json"
    provider, _ = instance.load(str(focus))
    records = provider.query("claim_states")
    assert len(records) == real_claims
    statuses = {r["status"] for r in records}
    assert statuses <= {"UNKNOWN", "DECLARED", "OBSERVED", "CERTIFIED",
                        "INTERPRETIVE", "REFUTED"}
    assert all(isinstance(r["resolvable"], bool) for r in records)
