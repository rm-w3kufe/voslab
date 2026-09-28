"""EP-4 D1 — delivery manifest: declared digests + drift detection.

Replaces the manual md5 rituals (plan §E3/E4): delivery artifacts are
declared once with sha256, every round observes them, and any byte change
surfaces as a `delivery_drift` event plus an honest REFUTED claim.

Epistemic discipline (F16): the declare/observe chain never reaches
CERTIFIED — the best state is OBSERVED (evidence = this manifest), the
drifted state is REFUTED with a failing IDENTITY cert. Same-system declare
and observe means `independent=False` by construction.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from vos_kernel.epistemic import (
    EpicStore,
    audit_claims,
    now_iso,
    repo_root,
    sha256_bytes,
    sha256_file,
    validate_cert,
    validate_claim,
)

MANIFEST_NAME = "delivery.manifest.json"


# ------------------------------------------------------------------ helpers


def _key(path: Path) -> str:
    """Stable manifest key: repo-relative posix path, else absolute."""
    p = path.resolve()
    try:
        return p.relative_to(repo_root()).as_posix()
    except ValueError:
        return str(p)


def _slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", key).strip("-")


def _load_manifest(store: EpicStore) -> dict:
    p = store.dir / MANIFEST_NAME
    if not p.exists():
        return {"version": 1, "updated_at": None, "artifacts": {}}
    return json.loads(p.read_text())


def _write_manifest(store: EpicStore, man: dict) -> None:
    man["updated_at"] = now_iso()
    p = store.dir / MANIFEST_NAME
    p.write_text(json.dumps(man, indent=1, sort_keys=True,
                             ensure_ascii=False) + "\n")


def _claim_for(key: str, digest: str, ts: str,
               existing: dict | None) -> dict:
    slug = _slug(key)
    text = f"artifact {key} sha256 {digest}"
    claim = dict(existing) if existing else {
        "id": f"DEL-{slug}",
        "type": "conformance",
        "subject": key,
        "risk": "delivery",
        "provenance": "vos_kernel.delivery declare",
        "certs": [],
    }
    claim.update({
        "status": "OBSERVED",
        "text": text,
        "text_hash": sha256_bytes(text.encode()),
        "value": digest,
        "evidence": MANIFEST_NAME,
        "declared_at": ts,
    })
    claim.pop("drift", None)
    claim["certs"] = list(claim.get("certs", []))
    return claim


def _cert(claim_id: str, slug: str, version: int, digest: str,
          ts: str, *, verdict: str, executor: str) -> dict:
    return {
        "id": f"CRT-DEL-{slug}-v{version}",
        "claim_id": claim_id,
        "class": "IDENTITY",
        "executor_ref": executor,
        "inputs_digest": digest,
        "verdict": verdict,
        "observed_at": ts,
        "independent": False,
    }


def _bridge_log(entry: dict) -> None:
    """Emit one event to logs/agent_plugin.jsonl via the bridge (EP-3 path)."""
    p = (repo_root() / ".opencode" / "plugins" / "operational"
         / "tool_integration_bridge.py")
    spec = importlib.util.spec_from_file_location(
        "tool_integration_bridge_delivery", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load bridge: {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.log_integration(entry)


# ------------------------------------------------------------------- declare


def declare(paths: list[str], store: EpicStore | None = None) -> dict:
    """Declare artifacts: sha256 -> manifest + OBSERVED claim + IDENTITY cert."""
    store = store or EpicStore()
    man = _load_manifest(store)
    claims_by_id = {c.get("id"): c for c in store.load("claims")}
    cert_ids = {c.get("id") for c in store.load("certs")}
    rep: dict = {"declared": [], "skipped": [], "errors": [], "audit": {}}

    pending_claims: list[dict] = []
    pending_certs: list[dict] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            rep["errors"].append(f"not a file: {raw}")
            continue
        digest = sha256_file(p)
        key = _key(p)
        slug = _slug(key)
        prev = man["artifacts"].get(key)
        if (prev and prev.get("sha256") == digest
                and not prev.get("drift")):
            rep["skipped"].append(key)
            continue

        ts = now_iso()
        version = (int(prev.get("version", 0)) + 1) if prev else 1
        claim_id = f"DEL-{slug}"
        claim = _claim_for(key, digest, ts, claims_by_id.get(claim_id))
        cert = _cert(claim_id, slug, version, digest, ts,
                     verdict="pass", executor="vos_kernel.delivery.declare")
        if cert["id"] not in claim["certs"]:
            claim["certs"].append(cert["id"])

        errs = validate_claim(claim) + validate_cert(cert)
        if errs:
            rep["errors"] += errs
            continue

        man["artifacts"][key] = {
            "sha256": digest,
            "declared_at": ts,
            "version": version,
            "claim_id": claim_id,
            "cert_ids": [cert["id"]],
            "drift": None,
        }
        pending_claims.append(claim)
        if cert["id"] not in cert_ids:
            pending_certs.append(cert)
            cert_ids.add(cert["id"])
        claims_by_id[claim_id] = claim
        rep["declared"].append({"key": key, "sha256": digest,
                                "version": version, "claim_id": claim_id,
                                "cert_id": cert["id"]})

    if rep["declared"]:
        _write_manifest(store, man)
        for claim in pending_claims:
            store.upsert("claims", claim)
        for cert in pending_certs:
            store.append("certs", cert)

    rep["audit"] = audit_claims(store, evidence_root=store.dir)
    rep["ok"] = not rep["errors"] and bool(rep["audit"].get("ok"))
    return rep


# -------------------------------------------------------------------- scan


def scan_manifest(paths: list[str] | None = None,
                  store: EpicStore | None = None) -> list[dict]:
    """Pure read: compare manifest digests against the files on disk.

    No writes, no events — detect_drift uses this; observe() persists.
    """
    store = store or EpicStore()
    man = _load_manifest(store)
    out: list[dict] = []
    keys = None
    if paths is not None:
        keys = {_key(Path(p)) for p in paths}
    for key, entry in man.get("artifacts", {}).items():
        if keys is not None and key not in keys:
            continue
        p = Path(key)
        if not p.is_absolute():
            p = repo_root() / key
        if not p.is_file():
            out.append({"path": key, "issue": "missing",
                        "declared": entry.get("sha256"),
                        "observed": None})
            continue
        digest = sha256_file(p)
        if digest != entry.get("sha256"):
            out.append({"path": key, "issue": "delivery_drift",
                        "declared": entry.get("sha256"),
                        "observed": digest})
    return out


# ------------------------------------------------------------------ observe


def observe(paths: list[str] | None = None, store: EpicStore | None = None,
            emit=None) -> dict:
    """Observe declared artifacts; on drift: REFUTED claim + failing cert +
    one delivery_drift event. Repeated observation of an unchanged drift
    keeps reporting (and emits) but does not grow the stores."""
    store = store or EpicStore()
    man = _load_manifest(store)
    if not man.get("artifacts"):
        return {"ok": False, "checked": 0, "clean": [], "drifts": [],
                "errors": ["nothing declared in delivery manifest"],
                "audit": {}}

    drifts = scan_manifest(paths, store=store)
    checked_keys = set(man["artifacts"])
    if paths is not None:
        checked_keys = {_key(Path(p)) for p in paths}
    drifted_keys = {d["path"] for d in drifts}
    clean = sorted(checked_keys - drifted_keys)

    rep: dict = {"checked": len(checked_keys), "clean": clean,
                 "drifts": drifts, "errors": [], "audit": {}}

    if drifts:
        claims_by_id = {c.get("id"): c for c in store.load("claims")}
        cert_ids = {c.get("id") for c in store.load("certs")}
        pending_claims: list[dict] = []
        pending_certs: list[dict] = []
        changed_manifest = False
        for d in drifts:
            key = d["path"]
            entry = man["artifacts"][key]
            slug = _slug(key)
            claim_id = entry.get("claim_id") or f"DEL-{slug}"
            prev_drift = entry.get("drift") or {}
            already = (prev_drift.get("issue") == d["issue"]
                       and prev_drift.get("observed_sha256")
                       == d["observed"]
                       and claims_by_id.get(claim_id, {}).get("status")
                       == "REFUTED")
            if already:
                continue  # alarm persists; stores stay stable

            ts = now_iso()
            version = int(entry.get("version", 0)) + 1
            observed = d.get("observed") or sha256_bytes(
                f"{key}:missing".encode())
            claim = claims_by_id.get(claim_id)
            if claim is None:
                claim = _claim_for(key, entry["sha256"], ts, None)
            cert = _cert(claim_id, slug, version, observed, ts,
                         verdict="fail",
                         executor="vos_kernel.delivery.observe")
            claim["status"] = "REFUTED"
            if cert["id"] not in claim["certs"]:
                claim["certs"].append(cert["id"])
            claim["drift"] = {"issue": d["issue"],
                              "observed_sha256": d.get("observed"),
                              "observed_at": ts}
            errs = validate_claim(claim) + validate_cert(cert)
            if errs:
                rep["errors"] += errs
                continue
            entry["version"] = version
            entry.setdefault("cert_ids", []).append(cert["id"])
            entry["drift"] = {"issue": d["issue"],
                              "observed_sha256": d.get("observed"),
                              "observed_at": ts}
            changed_manifest = True
            pending_claims.append(claim)
            if cert["id"] not in cert_ids:
                pending_certs.append(cert)
                cert_ids.add(cert["id"])
            claims_by_id[claim_id] = claim

        if changed_manifest:
            _write_manifest(store, man)
            for claim in pending_claims:
                store.upsert("claims", claim)
            for cert in pending_certs:
                store.append("certs", cert)

        entry_log = {
            "ts": now_iso(),
            "phase": "delivery_drift",
            "tool": "manifest-observe",
            "file": ";".join(d["path"] for d in drifts)[:120],
            "outcome": "failure",
            "level": "error",
            "evidence": {"drifts": drifts, "checked": rep["checked"]},
        }
        if emit is None:
            emit = _bridge_log
        try:
            emit(entry_log)
        except Exception as e:  # noqa: BLE001 — event loss must be visible
            rep["log_error"] = f"{type(e).__name__}: {e}"

    rep["audit"] = audit_claims(store, evidence_root=store.dir)
    rep["ok"] = (not rep["drifts"] and not rep["errors"]
                 and bool(rep["audit"].get("ok"))
                 and "log_error" not in rep)
    return rep


# --------------------------------------------------------------------- CLI


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="vos_kernel.delivery",
        description="EP-4 D1: delivery manifest declare/observe")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("declare", help="declare artifact digests (sha256)")
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("observe", help="verify declared digests (rc1=drift)")
    p.add_argument("paths", nargs="*")

    sub.add_parser("list", help="print the manifest")

    args = ap.parse_args(argv)
    store = EpicStore()

    if args.cmd == "declare":
        rep = declare(args.paths, store=store)
        _print(rep)
        return 0 if rep["ok"] else 1
    if args.cmd == "observe":
        rep = observe(args.paths or None, store=store)
        _print(rep)
        return 0 if rep["ok"] else 1
    _print(_load_manifest(store))
    return 0


if __name__ == "__main__":
    sys.exit(main())
