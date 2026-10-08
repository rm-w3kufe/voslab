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
    (tmp_path / "state" / "workspaces.json").write_text(json.dumps({
        "version": 1,
        "workspaces": [
            {"id": "ws-tmp", "root": "/tmp/opencode", "kind": "sandbox",
             "note": "scratch", "registered_at": "2026-09-29T00:00:00Z"},
            {"id": "ws-shared", "root": "/data/shared", "kind": "shared",
             "note": "", "registered_at": "2026-09-29T00:00:00Z"},
        ]}))
    (epi / "guards.jsonl").write_text("\n".join(json.dumps(g) for g in [
        {"id": "G-1", "artifact": "art-a", "covers": "cov-a",
         "cmd": ["true"], "expect": [], "ts": "2026-09-29T00:00:00Z"},
        {"id": "G-2", "artifact": "art-b", "covers": "cov-b",
         "cmd": ["true"], "expect": [], "ts": "2026-09-29T00:00:00Z"},
    ]) + "\n")
    (epi / "findings.jsonl").write_text("\n".join(json.dumps(f) for f in [
        {"id": "F-1", "symptom": "s", "root_cause": "r", "fix": "x",
         "guard": "G-1", "guard_status": "live"},
        {"id": "F-2", "symptom": "s", "root_cause": "r", "fix": "x",
         "guard": "G-1", "guard_status": "live"},
        {"id": "F-3", "symptom": "s", "root_cause": "r", "fix": "",
         "guard": "", "guard_status": "none"},
    ]) + "\n")
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


# ─── Phase 1 domains: workspaces + epistemic_health ──────────────────────────

def test_domains_include_phase1(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    domains = provider.list_domains()
    assert "workspaces" in domains
    assert "epistemic_health" in domains
    assert "claim_states" in domains     # D3 intact through the chain
    assert "focus" in domains            # base intact through the chain


def test_workspaces_records_and_filter(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    records = provider.query("workspaces")
    assert [r["id"] for r in records] == ["ws-tmp", "ws-shared"]
    assert records[0]["root"] == "/tmp/opencode"
    assert records[0]["kind"] == "sandbox"
    sandbox = provider.query("workspaces", {"kind": "sandbox"})
    assert [r["id"] for r in sandbox] == ["ws-tmp"]
    with pytest.raises(ValueError):
        provider.query("workspaces", {"no_such_field": 1})


def test_workspaces_live_reload(instance, world):
    import os
    root, focus, _ = world
    provider, _ = instance.load(str(focus))
    assert len(provider.query("workspaces")) == 2
    reg_file = root / "state" / "workspaces.json"
    reg = json.loads(reg_file.read_text())
    reg["workspaces"].append({"id": "ws-new", "root": "/srv/new",
                              "kind": "reference", "note": "",
                              "registered_at": "2026-09-29T00:00:00Z"})
    reg_file.write_text(json.dumps(reg))
    st = reg_file.stat()  # distinct mtime (same coarse-tick rationale
    os.utime(reg_file, ns=(st.st_atime_ns + 1_000_000,      # as claims)
                              st.st_mtime_ns + 1_000_000))
    records = provider.query("workspaces")
    assert len(records) == 3
    assert records[-1]["id"] == "ws-new"


def test_epistemic_health_linkage(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    records = provider.query("epistemic_health")
    by_id = {r["id"]: r for r in records}
    assert set(by_id) == {"G-1", "G-2"}
    assert by_id["G-1"]["findings"] == ["F-1", "F-2"]  # F->G linkage
    assert by_id["G-1"]["findings_count"] == 2
    assert by_id["G-2"]["findings"] == []              # unreferenced guard
    assert by_id["G-2"]["findings_count"] == 0
    # F-3 (empty guard) linked nowhere
    assert all("F-3" not in r["findings"] for r in records)


def test_phase1_fail_soft_without_stores(instance, tmp_path: Path,
                                         monkeypatch):
    """Empty layout: all three composite domains degrade to []."""
    monkeypatch.setenv("VOS_WORKSPACES_PATH",
                       str(tmp_path / "nowhere.json"))
    focus = tmp_path / "current_focus.json"  # no state/ at all
    focus.write_text("[]")
    provider, _ = instance.load(str(focus))
    assert provider.query("claim_states") == []
    assert provider.query("workspaces") == []
    assert provider.query("epistemic_health") == []
    for d in ("claim_states", "workspaces", "epistemic_health"):
        assert d in provider.list_domains()


def test_full_chain_delegation(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    # base domains survive three chained views
    assert provider.query("focus")[0]["ref"] == "T-1"
    assert len(provider.query("claim_states")) == 3
    assert provider.schema("epistemic_health")["findings"] == "list"
    assert provider.schema("workspaces")["kind"] == "str"


# ─── G-32: spec_kernel domain (SPEC-KERNEL-DOMAIN-REGISTER) ─────────────────

def test_spec_kernel_domain_registered_tmp(instance, world):
    """Domain answers in a world WITHOUT the ledger: six records, all
    evidence_missing — fail-soft, never a crash."""
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    assert "spec_kernel" in provider.list_domains()
    records = provider.query("spec_kernel")
    assert [r["id"] for r in records] == [
        "dev-a-breath", "dev-cpu-pressure", "dev-sensor-priority",
        "dev-eps-frontier", "dev-trust-update", "dev-ax-split-operator"]
    assert all(r["status"] == "evidence_missing" for r in records)
    assert all(r["evidence_file"].endswith("compression_ledger.vsm")
               for r in records)


def test_spec_kernel_filter_contract(instance, world):
    _, focus, _ = world
    provider, _ = instance.load(str(focus))
    only = provider.query("spec_kernel", {"subject": "A_breath"})
    assert [r["id"] for r in only] == ["dev-a-breath"]
    with pytest.raises(ValueError):
        provider.query("spec_kernel", {"no_such_field": 1})


def test_spec_kernel_reconciler_registered(instance, world):
    _, focus, _ = world
    _, reconcilers = instance.load(str(focus))
    matches = [r for r in reconcilers
               if getattr(r, "domain", None) == "spec_kernel"]
    assert len(matches) == 1


def test_spec_kernel_real_evidence_and_diff(instance):
    """THE G-32 auto_verify, as a test: the domain responds against the
    real repo, all six carry live ledger evidence lines, and the
    reconciler's diff reports exactly the OPEN deviations (A_breath —
    KERNEL-ABREATH-ALIGN still open) as rule_violation; the five resolved
    at certification 2026-08-08 stay recorded but drift nothing
    (lifecycle retired 2026-10-08, sesión algedónica)."""
    focus = repo_root() / "current_focus.json"
    provider, reconcilers = instance.load(str(focus))
    records = provider.query("spec_kernel")
    assert len(records) == 6
    by_id = {r["id"]: r for r in records}
    assert by_id["dev-a-breath"]["status"] == "known_deviation"
    assert all(by_id[i]["status"] == "resolved" for i in (
        "dev-cpu-pressure", "dev-sensor-priority", "dev-eps-frontier",
        "dev-trust-update", "dev-ax-split-operator"))
    assert all(isinstance(r["evidence_line"], int) for r in records)
    subjects = {r["subject"] for r in records}
    assert subjects == {"A_breath", "CPU_PRESSURE", "sensor_priority",
                        "eps_frontier", "Def_TrustUpdate",
                        "Ax_SplitOperator"}
    rec = next(r for r in reconcilers
               if getattr(r, "domain", None) == "spec_kernel")
    diffs = rec.diff()
    assert len(diffs) == 1
    assert all(d.kind == "rule_violation" for d in diffs)
    assert {d.subject for d in diffs} == {"A_breath"}
    # provider and observe() must agree (server warning contract)
    obs = {o["id"]: o for o in rec.observe()}
    prov = {r["id"]: r for r in records}
    assert all(obs[k]["status"] == prov[k]["status"] for k in obs)


def test_spec_kernel_evidence_missing_becomes_drift(instance, world,
                                                    monkeypatch):
    """Evidence token vanishes -> observe flips to evidence_missing and the
    OPEN registry claim itself is flagged (declared_but_missing), not
    silently kept. Retired (resolved) claims stay silent even WITH a live
    witness — they claim nothing (lifecycle 2026-10-08)."""
    root, focus, _ = world
    ledger = (root / "docs/spec_revision/ledger/compression-ledger-v1"
              / "compression_ledger.vsm")
    ledger.parent.mkdir(parents=True)
    # witness for a RETIRED claim only; A_breath's token is absent
    ledger.write_text("CPU_PRESSURE SEMANTICS WRONG was fixed 2026-08-08\n")
    provider, reconcilers = instance.load(str(focus))
    by_id = {r["id"]: r for r in provider.query("spec_kernel")}
    assert by_id["dev-a-breath"]["status"] == "evidence_missing"
    assert by_id["dev-cpu-pressure"]["status"] == "resolved"
    rec = next(r for r in reconcilers
               if getattr(r, "domain", None) == "spec_kernel")
    diffs = rec.diff()
    missing = [d for d in diffs if d.kind == "declared_but_missing"]
    # declared_but_missing indexes by key (id), per the Reconciler contract;
    # only the still-open claim goes stale — the five retired entries are
    # not declared active, so a missing token drifts nothing for them
    assert {d.subject for d in missing} == {"dev-a-breath"}
    rule = [d for d in diffs if d.kind == "rule_violation"]
    assert rule == []


def test_real_registry_and_health_read_only(instance):
    """Declarative smoke against the real repo (no writes)."""
    focus = repo_root() / "current_focus.json"
    provider, _ = instance.load(str(focus))
    ws_ids = [r["id"] for r in provider.query("workspaces")]
    # S5 external-path directive 2026-10-06: the 4 vsf-topology entries
    # (shared-docs, shared-scripts, vsf, vsf-nucleus) were retired — their
    # content lives in-repo now; only genuine externals remain declared.
    assert len(ws_ids) == 4 and "tmp-opencode" in ws_ids
    health = {r["id"]: r for r in provider.query("epistemic_health")}
    assert "G-MCP-ENV" in health
    assert {"FND-MCP-ENV-01", "FND-MCP-ENV-02",
            "FND-MCP-SIGTTIN-01"} <= set(health["G-MCP-ENV"]["findings"])
    assert health["G-MCP-ENV"]["findings_count"] >= 3



# ─── G-34 P4: pleasure domain (PLEASURE-CHANNEL-001) ────────────────────────

def _pleasure_rows() -> list[dict]:
    return [
        {"ts": "2026-10-05T10:00:00Z", "unit": "gate_run", "success": True,
         "streak": 3, "detail": "80/80",
         "emissions": [{"kind": "milestone", "magnitude": 4.2,
                        "magnitude_unit": "bits", "streak": 3}]},
        {"ts": "2026-10-06T10:00:00Z", "unit": "session_close", "success": False,
         "streak": 0, "detail": "dirty", "emissions": []},
    ]


def test_pleasure_domain_registered(instance, world):
    tmp, _, _ = world
    rsi = tmp / "state" / "rsi"
    rsi.mkdir(parents=True, exist_ok=True)
    (rsi / "pleasure.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _pleasure_rows()) + "\n",
        encoding="utf-8")
    provider, _ = instance.load(str(tmp / "current_focus.json"))
    assert "pleasure" in provider.list_domains()
    records = provider.query("pleasure")
    assert [r["unit"] for r in records] == ["gate_run", "session_close"]
    assert records[0]["pleasure"] == "milestone:4.2"
    assert records[1]["pleasure"] == "-"          # fallo sin emisiones
    assert records[0]["streak"] == 3 and records[0]["success"] is True
    assert provider.version("pleasure") and "absent" not in provider.version("pleasure")
    # delegacion intacta a traves de la cadena (base domains survive)
    assert provider.query("focus")[0]["ref"] == "T-1"
    # schema del dominio propio
    assert provider.schema("pleasure")["unit"] == "str"


def test_pleasure_live_reload(instance, world):
    tmp, _, _ = world
    rsi = tmp / "state" / "rsi"
    rsi.mkdir(parents=True, exist_ok=True)
    f = rsi / "pleasure.jsonl"
    f.write_text(json.dumps(_pleasure_rows()[0]) + "\n", encoding="utf-8")
    provider, _ = instance.load(str(tmp / "current_focus.json"))
    assert len(provider.query("pleasure")) == 1
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_pleasure_rows()[1]) + "\n")
    assert len(provider.query("pleasure")) == 2


def test_pleasure_filter_and_fail_soft(instance, world):
    tmp, _, _ = world
    rsi = tmp / "state" / "rsi"
    rsi.mkdir(parents=True, exist_ok=True)
    (rsi / "pleasure.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _pleasure_rows()) + "\n",
        encoding="utf-8")
    provider, _ = instance.load(str(tmp / "current_focus.json"))
    only = provider.query("pleasure", {"unit": "gate_run"})
    assert [r["unit"] for r in only] == ["gate_run"]
    assert provider.query("pleasure", {"unit": "nope"}) == []
    # fail-soft: dominio presente, datos corruptos -> []
    (rsi / "pleasure.jsonl").write_text("{broken\n", encoding="utf-8")
    assert provider.query("pleasure") == []
    assert "pleasure" in provider.list_domains()


def test_pleasure_missing_canal_is_empty_domain(instance, tmp_path: Path):
    """Canal aun no existe: dominio registrado y vacio (fail-soft F2)."""
    focus = tmp_path / "current_focus.json"
    focus.write_text("[]")
    provider, _ = instance.load(str(focus))
    assert provider.query("pleasure") == []
    assert "pleasure" in provider.list_domains()
    assert "absent" in (provider.version("pleasure") or "")
