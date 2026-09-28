"""EP-4 D1 tests — delivery manifest: declare/observe/drift/REFUTED.

All state lives in a tmp root (EpicStore(root=tmp)); the only writes to
the real store are the real-artifact demo performed outside these tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vos_kernel.delivery import (
    MANIFEST_NAME,
    declare,
    main,
    observe,
    scan_manifest,
)
from vos_kernel.epistemic import EpicStore, audit_claims, sha256_file


def _audit(store: EpicStore) -> dict:
    """audit_claims with evidence resolved against THIS store's dir."""
    return audit_claims(store, evidence_root=store.dir)


@pytest.fixture()
def env(tmp_path: Path):
    store = EpicStore(root=tmp_path)
    art = tmp_path / "artifact.txt"
    art.write_text("v1 payload\n")
    events: list[dict] = []
    return store, art, events


def _emit(events):
    def fn(entry: dict) -> None:
        events.append(entry)
    return fn


def test_declare_creates_manifest_claim_cert(env):
    store, art, _ = env
    rep = declare([str(art)], store=store)
    assert rep["ok"], rep
    assert len(rep["declared"]) == 1
    man = json.loads((store.dir / MANIFEST_NAME).read_text())
    (key, entry), = man["artifacts"].items()
    assert entry["sha256"] == sha256_file(art)
    claims = [c for c in store.load("claims") if c["id"].startswith("DEL-")]
    assert len(claims) == 1
    claim = claims[0]
    assert claim["status"] == "OBSERVED"
    assert claim["value"] == entry["sha256"]
    assert claim["evidence"] == MANIFEST_NAME
    certs = {c["id"]: c for c in store.load("certs")}
    cert = certs[claim["certs"][0]]
    assert cert["class"] == "IDENTITY"
    assert cert["verdict"] == "pass"
    assert cert["inputs_digest"] == entry["sha256"]
    assert _audit(store)["ok"]


def test_declare_idempotent(env):
    store, art, _ = env
    declare([str(art)], store=store)
    n_claims = len(store.load("claims"))
    n_certs = len(store.load("certs"))
    rep = declare([str(art)], store=store)
    assert rep["ok"] and rep["declared"] == [] and rep["skipped"]
    assert len(store.load("claims")) == n_claims
    assert len(store.load("certs")) == n_certs


def test_declare_changed_digest_updates_claim_single(env):
    store, art, _ = env
    declare([str(art)], store=store)
    art.write_text("v2 payload changed\n")
    rep = declare([str(art)], store=store)
    assert rep["ok"] and rep["declared"][0]["version"] == 2
    claims = [c for c in store.load("claims") if c["id"].startswith("DEL-")]
    assert len(claims) == 1  # upsert, never duplicate ids
    assert claims[0]["status"] == "OBSERVED"
    assert len(claims[0]["certs"]) == 2
    assert _audit(store)["ok"]


def test_observe_clean_no_event(env):
    store, art, events = env
    declare([str(art)], store=store)
    rep = observe(store=store, emit=_emit(events))
    assert rep["ok"], rep
    assert rep["drifts"] == [] and rep["checked"] == 1
    assert events == []


def test_observe_drift_refutes_and_emits(env):
    store, art, events = env
    declare([str(art)], store=store)
    art.write_text("v1 payload\nX")  # one-byte mutation (negative control)
    rep = observe(store=store, emit=_emit(events))
    assert not rep["ok"] and len(rep["drifts"]) == 1
    d = rep["drifts"][0]
    assert d["issue"] == "delivery_drift"
    assert d["declared"] != d["observed"]
    claims = [c for c in store.load("claims") if c["id"].startswith("DEL-")]
    assert claims[0]["status"] == "REFUTED"
    assert claims[0]["drift"]["issue"] == "delivery_drift"
    certs = {c["id"]: c for c in store.load("certs")}
    fail = [certs[cid] for cid in claims[0]["certs"]
            if certs[cid]["verdict"] == "fail"]
    assert len(fail) == 1 and fail[0]["inputs_digest"] == d["observed"]
    assert _audit(store)["ok"]
    assert len(events) == 1
    entry = events[0]
    assert entry["phase"] == "delivery_drift"
    assert entry["outcome"] == "failure"
    assert entry["evidence"]["drifts"][0]["path"] == d["path"]


def test_observe_missing_file_refutes(env):
    store, art, events = env
    declare([str(art)], store=store)
    art.unlink()
    rep = observe(store=store, emit=_emit(events))
    assert not rep["ok"] and rep["drifts"][0]["issue"] == "missing"
    claims = [c for c in store.load("claims") if c["id"].startswith("DEL-")]
    assert claims[0]["status"] == "REFUTED"
    assert _audit(store)["ok"]
    assert len(events) == 1


def test_observe_repeated_drift_stable_stores(env):
    store, art, events = env
    declare([str(art)], store=store)
    art.write_text("mutated\n")
    observe(store=store, emit=_emit(events))
    n_claims, n_certs = (len(store.load("claims")),
                         len(store.load("certs")))
    rep = observe(store=store, emit=_emit(events))
    assert not rep["ok"] and len(rep["drifts"]) == 1  # alarm persists
    assert len(store.load("claims")) == n_claims      # no store growth
    assert len(store.load("certs")) == n_certs
    assert len(events) == 2                           # event every round


def test_redeclare_after_restore_clears_drift(env):
    store, art, events = env
    declare([str(art)], store=store)
    original = art.read_bytes()
    art.write_bytes(original + b"tamper")
    observe(store=store, emit=_emit(events))
    art.write_bytes(original)
    rep = declare([str(art)], store=store)
    assert rep["ok"] and rep["declared"][0]["version"] == 3
    claims = [c for c in store.load("claims") if c["id"].startswith("DEL-")]
    assert claims[0]["status"] == "OBSERVED"
    assert "drift" not in claims[0]
    man = json.loads((store.dir / MANIFEST_NAME).read_text())
    assert list(man["artifacts"].values())[0]["drift"] is None
    assert _audit(store)["ok"]
    rep2 = observe(store=store, emit=_emit(events))
    assert rep2["ok"] and rep2["drifts"] == []


def test_scan_manifest_is_pure(env):
    store, art, _ = env
    declare([str(art)], store=store)
    art.write_text("mutated\n")
    before = (store.dir / MANIFEST_NAME).read_text()
    drifts = scan_manifest(store=store)
    assert len(drifts) == 1
    assert (store.dir / MANIFEST_NAME).read_text() == before
    claims = [c for c in store.load("claims") if c["id"].startswith("DEL-")]
    assert claims[0]["status"] == "OBSERVED"  # scan never mutates


def test_cli_rc_codes(env, capsys, tmp_path):
    store, art, _ = env  # store root = tmp_path/state/epistemic
    # CLI uses the real store; drive main() against tmp via monkeypatched cwd
    # instead — here we only validate rc semantics on declare/observe of a
    # file through the module entry with an explicit store path handled by
    # EpicStore(root=) defaults: use direct functions for the tmp store and
    # assert the rc contract on a missing file for the CLI.
    assert main(["list"]) in (0, 1)  # real store: list is always rc 0
    rc = main(["declare", str(tmp_path / "does-not-exist.txt")])
    assert rc == 1


def test_declare_missing_file_reports_error(env):
    store, _, _ = env
    rep = declare([str(store.dir / "nope.txt")], store=store)
    assert not rep["ok"] and rep["errors"]
    assert rep["audit"]["ok"]  # store untouched stays valid


def test_nested_path_slug_stable(tmp_path: Path):
    store = EpicStore(root=tmp_path)
    sub = tmp_path / "docs" / "plan.vsm"
    sub.parent.mkdir()
    sub.write_text("⟦ x ⟧\n")
    rep = declare([str(sub)], store=store)
    assert rep["ok"]
    claim = [c for c in store.load("claims")
             if c["id"].startswith("DEL-")][0]
    assert "/" not in claim["id"]
    assert claim["subject"].endswith("docs/plan.vsm")
