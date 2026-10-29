# design: docs/design/sources/second-order-loop-v1/second_order_loop.vsm
"""instrument_manifest — F2 (second-order-loop): loader del manifest de instrumentos.

Interface modular de onboarding (design §6): un instrumento nuevo = 1 manifest
declarando (Sn, función-anidada) + driver B4 + canal + emits/consumes + consent
(rail R17) + on_ratified. El loader valida DETERMINÍSTICAMENTE (R10) y registra
por (Sn, nested_fn) — onboarding vivo sin tocar el orquestador.

B4 driver map (driver_topology.vsm §10 — no inventar; driver = B4[sn]):
  S1=phi_up_direct, S2=event_coordinator, S3=invariant_guard,
  S3*=audit_scanner, S4=projector_directive, S5=consent_gate.

Store: system/instruments/*.json (un instrumento = un manifest). El loader
también expone validate/index/query para que el harness (S5) consulte qué
instrumentos habitan cada asiento (Sn, nested_fn).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Schema enums (design §6) ────────────────────────────────────────────────
SN_ENUM = ("S1", "S2", "S3", "S3*", "S4", "S5")
CONSENT_ENUM = ("read-only", "advisory", "needs-nod")
EMITS_ENUM = ("insumo", "argumento", "predicado", "veredicto", "proposicion",
              "ratificacion")
CONSUMES_ENUM = ("canon", "alerts", "eventos", "contexto")
ON_RATIFIED_ENUM = ("pattern-runner", "socratic-predicate", "gate", "tasks",
                    "none")

# B4 (driver_topology.vsm §10): el driver del Sn NO se inventa.
B4_DRIVER = {
    "S1": "phi_up_direct",
    "S2": "event_coordinator",
    "S3": "invariant_guard",
    "S3*": "audit_scanner",
    "S4": "projector_directive",
    "S5": "consent_gate",
}

REQUIRED_FIELDS = ("id", "sn", "nested_fn", "driver", "canal", "emits",
                   "consumes", "consent", "on_ratified")


def _is_kebab(s: str) -> bool:
    if not s or s.startswith("-") or s.endswith("-") or "--" in s:
        return False
    return all(c.islower() or c.isdigit() or c == "-" for c in s)


def validate_manifest(m: dict) -> list[str]:
    """Deterministic schema + B4-driver validation (R10). Empty list = valid."""
    errs: list[str] = []
    if not isinstance(m, dict):
        return ["manifest must be a JSON object"]
    for f in REQUIRED_FIELDS:
        if f not in m:
            errs.append(f"missing field: {f}")
    if errs:
        return errs

    if not _is_kebab(str(m["id"])):
        errs.append(f"id not kebab-case: {m['id']!r}")
    if m["sn"] not in SN_ENUM:
        errs.append(f"sn not in {SN_ENUM}: {m['sn']!r}")
    if m["nested_fn"] not in SN_ENUM:
        errs.append(f"nested_fn not in {SN_ENUM}: {m['nested_fn']!r}")

    expected = B4_DRIVER.get(m["sn"])
    if m["driver"] != expected:
        errs.append(f"driver {m['driver']!r} != B4 driver {expected!r} "
                    f"for sn {m['sn']} (no inventar)")

    if m["consent"] not in CONSENT_ENUM:
        errs.append(f"consent not in {CONSENT_ENUM}: {m['consent']!r}")

    emits = m["emits"]
    if not (isinstance(emits, list) and emits):
        errs.append("emits must be a non-empty list")
    else:
        for e in emits:
            if e not in EMITS_ENUM:
                errs.append(f"emits value not in {EMITS_ENUM}: {e!r}")

    consumes = m["consumes"]
    if not (isinstance(consumes, list) and consumes):
        errs.append("consumes must be a non-empty list")
    else:
        for c in consumes:
            if c not in CONSUMES_ENUM:
                errs.append(f"consumes value not in {CONSUMES_ENUM}: {c!r}")

    if m["on_ratified"] not in ON_RATIFIED_ENUM:
        errs.append(f"on_ratified not in {ON_RATIFIED_ENUM}: {m['on_ratified']!r}")
    return errs


def load_manifests(store: Path) -> list[dict]:
    """Load all *.json manifests from the store dir (one instrument = one file).

    Invalid JSON is skipped (visible via load count); a manifest that fails
    validate_manifest is still returned (caller decides — R9: never silent).
    """
    out: list[dict] = []
    if not store.is_dir():
        return out
    for f in sorted(store.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def index_by_seat(manifests: list[dict]) -> dict[tuple, list[str]]:
    """Index valid manifests by (sn, nested_fn) → [instrument ids]."""
    idx: dict[tuple, list[str]] = {}
    for m in manifests:
        if validate_manifest(m):
            continue  # only valid manifests occupy a seat
        key = (m.get("sn"), m.get("nested_fn"))
        idx.setdefault(key, []).append(m.get("id"))
    return idx


def query(manifests: list[dict], sn: str | None = None,
          nested_fn: str | None = None, id: str | None = None) -> list[dict]:
    """Filter manifests by seat and/or id (all filters optional, AND-ed)."""
    out = []
    for m in manifests:
        if sn is not None and m.get("sn") != sn:
            continue
        if nested_fn is not None and m.get("nested_fn") != nested_fn:
            continue
        if id is not None and m.get("id") != id:
            continue
        out.append(m)
    return out


def onboard(store: Path, manifest_path: Path) -> list[str]:
    """Validate + install a manifest into the store (1 instrument = 1 file).

    Returns validation errors (empty = onboarded). Refuses to install an
    invalid manifest (deterministic gate, no silent patch).
    """
    try:
        m = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return [f"cannot read manifest: {e}"]
    errs = validate_manifest(m)
    if errs:
        return errs
    store.mkdir(parents=True, exist_ok=True)
    dest = store / f"{m['id']}.json"
    dest.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    return []


def _default_store() -> Path:
    # repo root = three levels up from packages/framework/vos_kernel/
    return Path(__file__).resolve().parents[3] / "system" / "instruments"


def main(argv: list[str]) -> int:
    store = _default_store()
    if len(argv) >= 1 and argv[0] == "validate":
        if len(argv) < 2:
            print("usage: instrument_manifest validate <file.json>", file=sys.stderr)
            return 2
        try:
            m = json.loads(Path(argv[1]).read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"FAIL cannot read: {e}", file=sys.stderr)
            return 1
        errs = validate_manifest(m)
        if errs:
            for e in errs:
                print(f"  ✗ {e}", file=sys.stderr)
            print("FAIL manifest invalid", file=sys.stderr)
            return 1
        print("PASS manifest valid")
        return 0
    if len(argv) >= 1 and argv[0] == "onboard":
        if len(argv) < 2:
            print("usage: instrument_manifest onboard <file.json>", file=sys.stderr)
            return 2
        errs = onboard(store, Path(argv[1]))
        if errs:
            for e in errs:
                print(f"  ✗ {e}", file=sys.stderr)
            print("FAIL not onboarded", file=sys.stderr)
            return 1
        print(f"PASS onboarded → {store}")
        return 0
    # default: list indexed by seat
    manifests = load_manifests(store)
    idx = index_by_seat(manifests)
    print(f"instruments: {len(manifests)} loaded, {sum(len(v) for v in idx.values())} seated")
    for (sn, nfn), ids in sorted(idx.items()):
        print(f"  {sn}.{nfn}: {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
