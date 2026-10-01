"""covenant_hash.py — covenant hash registry verification (kernel operation).

Procedure imported from vsf under the covenant-ceremony observation
(S5 rmw3, 2026-10-01): "incorporar el procedimiento en el runtime/kernel".

Design follows docs/specs/covenant_hash_registry.vsm: the hash is an
INTEGRITY ANCHOR derived independently at several points that must then
AGREE — never a secret to distribute from one config file. This module
is the read-only INDEPENDENT verifier; it never writes. Mutation of the
mutable class belongs to vsf's sync_covenant_hash.sh (apply-gated, R17),
and remote publication checks belong to verify_covenant_hash.py --remote.

Offline scope (deterministic, R10 — same inputs, same report):
    anchor      = sha256(vsf/docs/governance/covenant.vsm)
    mutable     = core/s5_policy.default.json _meta.covenant_hash
                  LICENSE line "Covenant SHA-256:" (beacon canonical;
                  UNREGISTERED gap — task LICENSE-COVENANT-DRIFT-FOUND)
    registry    = docs/spec/covenant_hash_registry.vsm current.hash
    mirror      = vOSlab docs/canon_mirror/covenant.vsm (fidelity; the
                  mirror stays frozen by policy at promotion — plan gap g4)
    derived     = build.rs / env!(COVENANT_SHA256) self-check at build+runtime
                  (out of scope offline — noted, not re-implemented)
    published   = https://vsf.u2738.org/covenant.hash (delegated to
                  verify_covenant_hash.py --remote — never fetched here)

Usage:
    from vos_kernel.covenant_hash import verify_registry, promotion_plan
    report = verify_registry()
    assert report.consistent

CLI:
    python3 -m vos_kernel.covenant_hash [--json]
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HASH_RE = re.compile(r"([0-9a-f]{64})")
_REGISTRY_HASH_RE = re.compile(r'hash:\s*"([0-9a-f]{64})"')
_LICENSE_RE = re.compile(r"^Covenant SHA-256:\s*([0-9a-f]{64})\s*$")
_PLAN_ID_RE = re.compile(r'\{id:\s*"(P[0-9]+)",\s*name:\s*"([A-Z0-9-]+)"')


def voslab_root() -> Path:
    # .../vOSlab/packages/framework/vos_kernel/covenant_hash.py -> parents[3]
    return Path(__file__).resolve().parents[3]


def default_vsf_root() -> Path:
    return Path(os.environ.get("VSF_ROOT", str(Path.home() / "vsf")))


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Check:
    name: str
    cls: str  # mutable | unregistered | registry | mirror | derived | published
    expected: str | None  # anchor
    observed: str | None  # None = missing/unreadable
    ok: bool
    note: str = ""


@dataclass
class HashReport:
    anchor: str | None
    anchor_source: str
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return (
            self.anchor is not None
            and bool(self.checks)
            and all(c.ok for c in self.checks)
        )

    def to_dict(self) -> dict:
        return {
            "anchor": self.anchor,
            "anchor_source": self.anchor_source,
            "consistent": self.consistent,
            "checks": [
                {
                    "name": c.name,
                    "class": c.cls,
                    "expected": c.expected,
                    "observed": c.observed,
                    "ok": c.ok,
                    "note": c.note,
                }
                for c in self.checks
            ],
            "notes": self.notes,
        }


def _check(name: str, cls: str, anchor: str | None, observed: str | None,
           note: str = "") -> Check:
    if observed is None:
        return Check(name, cls, anchor, None, False,
                     note or "location missing or unreadable")
    ok = anchor is not None and observed == anchor
    return Check(name, cls, anchor, observed, ok, note)


def verify_registry(vsf_root: Path | None = None,
                    voslab: Path | None = None) -> HashReport:
    """Compare every offline-checkable covenant hash location against the
    anchor (the governance covenant on disk). Deterministic, read-only."""
    vsf = Path(vsf_root) if vsf_root else default_vsf_root()
    vlab = Path(voslab) if voslab else voslab_root()

    gov = vsf / "docs" / "governance" / "covenant.vsm"
    anchor = file_sha256(gov)
    report = HashReport(anchor=anchor, anchor_source=str(gov))

    if anchor is None:
        report.notes.append("anchor missing: governance covenant not found")
        return report

    # mutable: operational expectation S5 boots against
    policy = vsf / "core" / "s5_policy.default.json"
    observed = None
    if policy.is_file():
        try:
            data = json.loads(policy.read_text(encoding="utf-8"))
            observed = data.get("_meta", {}).get("covenant_hash")
        except (json.JSONDecodeError, OSError) as exc:
            report.notes.append(f"{policy.name}: unreadable ({exc})")
    report.checks.append(
        _check("s5_policy._meta.covenant_hash", "mutable", anchor, observed))

    # unregistered-but-live: LICENSE line (beacon canonical source)
    lic = vsf / "LICENSE"
    observed = None
    if lic.is_file():
        for line in lic.read_text(encoding="utf-8").splitlines():
            m = _LICENSE_RE.match(line)
            if m:
                observed = m.group(1)
                break
    report.checks.append(
        _check("LICENSE:Covenant SHA-256", "unregistered", anchor, observed,
               "beacon _canonical_hash() source; not in registry "
               "(LICENSE-COVENANT-DRIFT-FOUND)"))

    # registry document's own recorded current hash
    reg = vsf / "docs" / "spec" / "covenant_hash_registry.vsm"
    observed = None
    if reg.is_file():
        m = _REGISTRY_HASH_RE.search(reg.read_text(encoding="utf-8"))
        if m:
            observed = m.group(1)
    report.checks.append(
        _check("registry.current.hash", "registry", anchor, observed))

    # vOSlab canon_mirror fidelity (policy note: frozen drift expected
    # after promotion — S5 re-baselines then, plan gap g4)
    mirror = vlab / "docs" / "canon_mirror" / "covenant.vsm"
    report.checks.append(
        _check("canon_mirror.covenant", "mirror", anchor,
               file_sha256(mirror)))

    report.notes.append(
        "derived (build.rs/env!) self-checks at build+runtime — out of "
        "scope offline; published canonical via verify_covenant_hash.py "
        "--remote — never fetched here")
    return report


def promotion_plan(plan_path: Path | None = None) -> list[dict]:
    """Extract the ratified ceremony phases (id + name) from
    docs/plans/covenant_promotion_ceremony.vsm. Deterministic parse."""
    path = (plan_path if plan_path
            else voslab_root() / "docs" / "plans"
            / "covenant_promotion_ceremony.vsm")
    if not path.is_file():
        raise FileNotFoundError(f"ceremony plan not found: {path}")
    text = path.read_text(encoding="utf-8")
    return [{"id": m.group(1), "name": m.group(2)}
            for m in _PLAN_ID_RE.finditer(text)]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    report = verify_registry()
    if "--json" in argv:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        flag = "CONSISTENT" if report.consistent else "INCONSISTENT"
        print(f"{flag}  anchor={report.anchor}  ({report.anchor_source})")
        for c in report.checks:
            mark = "ok " if c.ok else "FAIL"
            print(f"  [{mark}] {c.cls:13s} {c.name}  observed={c.observed}")
        for n in report.notes:
            print(f"  note: {n}")
    return 0 if report.consistent else 1


if __name__ == "__main__":
    sys.exit(main())
