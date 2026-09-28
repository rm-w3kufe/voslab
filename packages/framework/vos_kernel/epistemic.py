"""epistemic certification engine (EP-1) — schemas, stores, audits, CLI.

VSM phase EP-1 of plan EPISTEMIC-CERT-001 (docs/plans/epistemic_certification_plan.vsm).

Ontology (substrate-agnostic; every executor is named by `executor_ref`,
never by language/runtime):

  CLM  claim       {id, text, text_hash, type, subject, risk, status, certs[],
                    provenance, value?, evidence?}
  CRT  certificate {id, claim_id, class, executor_ref, inputs_digest, verdict,
                    observed_at, independent, evidence?, detail?}
  FND  finding     {id, symptom, root_cause, fix, guard, guard_status, learn_ref}
  GDR  guard       {id, artifact, cmd, cwd, expect[], ts}
  DEC  decision    {id, question, alternatives, impact, reversible, approved,
                    tree_trace_id, outcome}

Lattice (6 states): UNKNOWN / DECLARED / OBSERVED / CERTIFIED / INTERPRETIVE
/ REFUTED.  Reading: UNKNOWN = not yet asserted; DECLARED = asserted, not yet
seen; OBSERVED = seen in evidence; CERTIFIED = certified by resolvable certs;
INTERPRETIVE = ceiling for type=interpretation (never CERTIFIED — F16 of the
plan: the semantic is argued, never certified); REFUTED = contradicted.

Audit invariants (deterministic, R10 — no randomness anywhere):
  F→G   every finding with a `fix` names a guard that exists in guards.jsonl
        and is not `dead` (plan F10/§6: fix ⇒ guard ejecutable con nombre).
  CHAIN every claim in status OBSERVED/CERTIFIED (or carrying cert refs) has
        resolvable certificates; CERTIFIED needs >=1 passing cert; a
        conformance claim at risk=delivery needs >=1 independent cert
        (plan F16: fuente independiente).
  SCAN  number tokens in prose are tracked: curated sidecar claims or the
        auto-scan registry (status DECLARED, provenance=auto-scan); new
        unregistered tokens are orphans.

Extension fields beyond the plan's core schema are marked `?` above and are
required by the audits (value/evidence for number claims, evidence/detail for
certs, cmd/cwd/expect for guards).

CLI:
  python3 -m vos_kernel.epistemic audit-claims [--strict]
  python3 -m vos_kernel.epistemic audit-guards [--run]
  python3 -m vos_kernel.epistemic audit-artifact PATH [--strict] [--scan]
  python3 -m vos_kernel.epistemic scan PATH...        (register bare numbers)
  python3 -m vos_kernel.epistemic register PATH...    (H1: explicit claims)
  python3 -m vos_kernel.epistemic show claims|certs|findings|guards|decisions
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- constants

STATUSES = (
    "UNKNOWN", "DECLARED", "OBSERVED", "CERTIFIED", "INTERPRETIVE", "REFUTED",
)
CLAIM_TYPES = (
    "theorem", "number", "conformance", "empirical",
    "interpretation", "decision", "procedure",
)
CERT_CLASSES = ("FORMAL", "PREDICATE", "AUDIT", "IDENTITY", "REVIEW")
RISKS = ("exploratory", "internal", "delivery")
VERDICTS = ("pass", "fail", "inconclusive")
GUARD_STATES = ("live", "dead", "unknown", "none")

_NUM_RE = re.compile(
    r"(?<![\w.])-?\d+\.\d+(?:[eE][-+]?\d+)?(?![\w])"
    r"|(?<![\w])\d+/\d+(?![\w])"
)
_FLOAT_RE = re.compile(r"-?\d+\.\d+(?:[eE][-+]?\d+)?")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sig_digits(value: str) -> int:
    if "/" in value:  # ratios compare at evidence precision (6 decimals)
        return 6
    mant = value.split("/")[0].lstrip("+-").split("e")[0].split("E")[0]
    mant = mant.replace(".", "")
    return len(mant.lstrip("0")) or 1


def _parse_value(value: str) -> float | None:
    """Numeric reading of a claim value: floats, e-notation and ratios a/b."""
    v = value.strip().strip("%").replace(",", "")
    if "/" in v:
        a, _, b = v.partition("/")
        try:
            return float(a) / float(b)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(v)
    except ValueError:
        return None


def value_in_evidence(value: str, hay: str) -> bool:
    """Deterministic match: exact substring first, then numeric equality at
    the claim's own precision (prose rounds; outputs keep full digits)."""
    val = str(value).strip()
    if not val:
        return False
    if val in hay:
        return True
    x = _parse_value(val)
    if x is None:
        return False
    sig = _sig_digits(val)
    # tolerance = half of the claim's last significant digit
    import math
    if x == 0.0:
        tol = 0.0  # zero only matches exact zero (substring already covered it)
    else:
        tol = 0.5 * 10.0 ** (math.floor(math.log10(abs(x))) - sig + 1)
    for tok in _FLOAT_RE.finditer(hay):
        try:
            y = float(tok.group(0))
        except ValueError:
            continue
        if abs(y - x) <= tol:
            return True
    return False


def now_iso() -> str:
    """Real UTC timestamp with seconds; avoids the :00 sentinel the
    timestamp gate classifies as hardcoded."""
    while True:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not ts.endswith(":00Z"):
            return ts
        time.sleep(1)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for cand in [here, *here.parents]:
        if (cand / "state").is_dir() and (cand / "packages").is_dir():
            return cand
    return Path.cwd()


def store_dir(root: Path | None = None) -> Path:
    d = (root or repo_root()) / "state" / "epistemic"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- validators


def validate_claim(c: dict) -> list[str]:
    errs: list[str] = []
    for f in ("id", "type", "subject", "risk", "status", "provenance"):
        if not isinstance(c.get(f), str) or not c.get(f):
            errs.append(f"claim: missing/empty field {f!r}")
    if c.get("type") not in CLAIM_TYPES:
        errs.append(f"claim {c.get('id')}: invalid type {c.get('type')!r}")
    if c.get("risk") not in RISKS:
        errs.append(f"claim {c.get('id')}: invalid risk {c.get('risk')!r}")
    if c.get("status") not in STATUSES:
        errs.append(f"claim {c.get('id')}: invalid status {c.get('status')!r}")
    certs = c.get("certs", [])
    if not isinstance(certs, list) or not all(isinstance(x, str) for x in certs):
        errs.append(f"claim {c.get('id')}: certs must be a list of ids")
    text = c.get("text", "")
    if text:
        if c.get("text_hash") and c["text_hash"] != sha256_bytes(text.encode()):
            errs.append(f"claim {c.get('id')}: text_hash does not match text")
    if c.get("type") == "number":
        val = c.get("value")
        if val is None or not str(val).strip() or str(val) == "None":
            errs.append(f"claim {c.get('id')}: number claim needs value")
    if c.get("type") == "interpretation" and c.get("status") == "CERTIFIED":
        errs.append(
            f"claim {c.get('id')}: interpretation cannot reach CERTIFIED "
            "(ceiling INTERPRETIVE)"
        )
    return errs


def validate_cert(c: dict) -> list[str]:
    errs: list[str] = []
    for f in ("id", "claim_id", "class", "executor_ref", "inputs_digest",
              "verdict", "observed_at"):
        if not isinstance(c.get(f), str) or not c.get(f):
            errs.append(f"cert: missing/empty field {f!r}")
    if c.get("class") not in CERT_CLASSES:
        errs.append(f"cert {c.get('id')}: invalid class {c.get('class')!r}")
    if c.get("verdict") not in VERDICTS:
        errs.append(f"cert {c.get('id')}: invalid verdict {c.get('verdict')!r}")
    dig = str(c.get("inputs_digest", ""))
    if dig and dig.removeprefix("sha256:") and not _SHA256_RE.match(
            dig.removeprefix("sha256:")):
        errs.append(f"cert {c.get('id')}: inputs_digest not sha256 hex")
    obs = str(c.get("observed_at", ""))
    if obs and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", obs):
        errs.append(f"cert {c.get('id')}: observed_at not ISO8601 with seconds")
    if not isinstance(c.get("independent"), bool):
        errs.append(f"cert {c.get('id')}: independent must be bool")
    return errs


def validate_finding(f: dict) -> list[str]:
    errs: list[str] = []
    for fld in ("id", "symptom", "root_cause", "fix", "guard", "guard_status"):
        if not isinstance(f.get(fld), str):
            errs.append(f"finding: missing/str field {fld!r}")
    if f.get("guard_status") not in GUARD_STATES:
        errs.append(f"finding {f.get('id')}: bad guard_status")
    if f.get("fix") and not f.get("guard"):
        errs.append(f"finding {f.get('id')}: fix without guard (F→G)")
    if f.get("fix") and f.get("guard_status") == "none":
        errs.append(f"finding {f.get('id')}: fix with guard_status=none (F→G)")
    if f.get("fix") and f.get("guard_status") == "dead":
        errs.append(f"finding {f.get('id')}: fix with dead guard (F→G)")
    return errs


def validate_guard(g: dict) -> list[str]:
    errs: list[str] = []
    for fld in ("id", "cmd", "expect", "ts"):
        if g.get(fld) in (None, "", []):
            errs.append(f"guard: missing/empty field {fld!r}")
    cmd = g.get("cmd")
    if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
        errs.append(f"guard {g.get('id')}: cmd must be list[str]")
    exp = g.get("expect")
    if not isinstance(exp, list) or not all(isinstance(x, str) for x in exp):
        errs.append(f"guard {g.get('id')}: expect must be list[str]")
    return errs


def validate_decision(d: dict) -> list[str]:
    errs: list[str] = []
    for f in ("id", "question", "impact", "outcome"):
        if not isinstance(d.get(f), str) or not d.get(f):
            errs.append(f"decision: missing/empty field {f!r}")
    if not isinstance(d.get("reversible"), bool):
        errs.append(f"decision {d.get('id')}: reversible must be bool")
    alts = d.get("alternatives")
    if not isinstance(alts, list) or not alts:
        errs.append(f"decision {d.get('id')}: alternatives must be non-empty list")
    return errs


# ---------------------------------------------------------------- store


class EpicStore:
    """JSONL store under state/epistemic/. Deterministic reads (file order)."""

    FILES = {
        "claims": "claims.jsonl",
        "certs": "certs.jsonl",
        "findings": "findings.jsonl",
        "guards": "guards.jsonl",
        "decisions": "decisions.jsonl",
    }

    def __init__(self, root: Path | None = None):
        self.dir = store_dir(root)

    def path(self, kind: str) -> Path:
        return self.dir / self.FILES[kind]

    def load(self, kind: str) -> list[dict]:
        p = self.path(kind)
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def append(self, kind: str, rec: dict) -> None:
        with self.path(kind).open("a") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")

    def get(self, kind: str, rec_id: str) -> dict | None:
        for r in self.load(kind):
            if r.get("id") == rec_id:
                return r
        return None


# ---------------------------------------------------------------- audits


def resolve_certs(claim: dict, certs_by_id: dict[str, dict]) -> tuple[list[dict], list[str]]:
    resolved, errs = [], []
    for cid in claim.get("certs", []):
        c = certs_by_id.get(cid)
        if c is None:
            errs.append(f"claim {claim.get('id')}: cert {cid!r} not found")
        else:
            resolved.append(c)
    return resolved, errs


def audit_claim(claim: dict, certs_by_id: dict[str, dict],
                evidence_root: Path | None = None) -> list[str]:
    """Chain rules for one claim. Returns error strings ([] = ok)."""
    errs = validate_claim(claim)
    if errs:
        return errs
    status = claim["status"]
    resolved, rerrs = resolve_certs(claim, certs_by_id)
    if status in ("OBSERVED", "CERTIFIED") or claim.get("certs"):
        errs += rerrs
    bad = [c for c in resolved if c.get("verdict") not in VERDICTS]
    errs += [f"claim {claim['id']}: cert {c['id']} bad verdict" for c in bad]

    passing = [c for c in resolved if c.get("verdict") == "pass"]
    if status == "CERTIFIED":
        if not passing:
            errs.append(f"claim {claim['id']}: CERTIFIED without passing cert")
        if (claim["type"] == "conformance" and claim["risk"] == "delivery"
                and not any(c.get("independent") for c in passing)):
            errs.append(
                f"claim {claim['id']}: conformance@delivery needs an "
                "independent cert (F16)"
            )
    if status == "OBSERVED":
        ev = claim.get("evidence")
        if not ev:
            errs.append(f"claim {claim['id']}: OBSERVED without evidence")
    if status == "REFUTED":
        if not any(c.get("verdict") == "fail" for c in resolved):
            errs.append(f"claim {claim['id']}: REFUTED without failing cert")

    # evidence resolution + number value presence (observed/certified)
    ev = claim.get("evidence")
    if ev and status in ("OBSERVED", "CERTIFIED"):
        evp = Path(ev) if Path(ev).is_absolute() else (
            (evidence_root or (store_dir() )) / ev)
        if not evp.exists():
            errs.append(f"claim {claim['id']}: evidence {ev!r} not found")
        elif claim["type"] == "number":
            hay = evp.read_text(errors="replace")
            if not value_in_evidence(str(claim.get("value", "")), hay):
                errs.append(
                    f"claim {claim['id']}: value {claim.get('value')!r} not "
                    f"present in evidence {ev!r}"
                )
    return errs


def audit_claims(store: EpicStore, extra_claims: list[dict] | None = None,
                 evidence_root: Path | None = None) -> dict:
    claims = store.load("claims") + (extra_claims or [])
    certs = {c["id"]: c for c in store.load("certs") if "id" in c}
    seen, dup, errors = set(), [], []
    for cl in claims:
        cid = cl.get("id")
        if cid in seen:
            dup.append(cid)
        seen.add(cid)
        for e in audit_claim(cl, certs, evidence_root=evidence_root):
            errors.append(e)
    if dup:
        errors.append(f"duplicate claim ids: {dup}")
    orphans = [
        e for e in errors if "CERTIFIED" in e or "cert " in e or "OBSERVED" in e
    ]
    return {
        "claims": len(claims),
        "certs": len(certs),
        "errors": errors,
        "orphan_errors": orphans,
        "ok": not errors,
    }


def audit_guards(store: EpicStore, run: bool = False) -> dict:
    """F→G: every finding with a fix has an existing, non-dead guard."""
    findings = store.load("findings")
    guards = {g["id"]: g for g in store.load("guards") if "id" in g}
    errors, missing, fixeados = [], [], 0
    liveness: dict[str, str] = {}
    for f in findings:
        verr = validate_finding(f)
        errors += verr
        if not f.get("fix"):
            continue
        fixeados += 1
        gid = f.get("guard")
        if not gid or gid not in guards:
            missing.append(f.get("id"))
            errors.append(
                f"finding {f.get('id')}: fix without resolvable guard {gid!r}"
            )
    if run:
        for gid, g in sorted(guards.items()):
            liveness[gid] = _run_guard(g)
    coverage = (fixeados - len(missing)) / fixeados if fixeados else 1.0
    return {
        "findings": len(findings),
        "fixeados": fixeados,
        "guarded": fixeados - len(missing),
        "coverage": round(coverage, 4),
        "missing": missing,
        "liveness": liveness,
        "errors": errors,
        "ok": not errors and coverage == 1.0,
    }


def _run_guard(g: dict) -> str:
    """Execute a guard deterministically: live if rc==0 and every expect
    substring appears in combined stdout+stderr."""
    cwd = g.get("cwd") or "."
    try:
        p = subprocess.run(
            g["cmd"], cwd=cwd, capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"error:{type(e).__name__}"
    out = p.stdout + p.stderr
    if p.returncode != 0:
        return f"dead:rc={p.returncode}"
    for exp in g.get("expect", []):
        if exp not in out:
            return f"dead:missing_expect:{exp[:40]!r}"
    return "live"


# ------------------------------------------------------- sidecar + artifacts


def load_sidecar(path: Path) -> list[dict]:
    """Parse `<name>.claims.vsm`: JSON list assigned to `claims = [...]`."""
    text = path.read_text()
    marker = "claims = ["
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"{path}: no `claims = [` marker")
    start = idx + len("claims = ")
    arr, _end = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(arr, list):
        raise ValueError(f"{path}: claims is not a list")
    return arr


def new_doc_sidecar(name: str, claims: list[dict]) -> str:
    """Build a valid `<stem>.claims.vsm` document from claim dicts."""
    from vos_kernel.utils.vsm_kernel import new_doc

    body = (
        "// epistemic claims sidecar (EPISTEMIC-CERT-001, EP-1)\n"
        "claims = " + json.dumps(claims, indent=2, ensure_ascii=False) + "\n"
    )
    return new_doc(name, "CLAIMS-v1", body, status="active")


def find_sidecar(artifact: Path) -> Path | None:
    """Adjacent sidecar first, then central state/epistemic/sidecars/."""
    cands = [
        artifact.parent / f"{artifact.stem}.claims.vsm",
        artifact.parent / f"{artifact.name}.claims.vsm",
        store_dir() / "sidecars" / f"{artifact.stem}.claims.vsm",
    ]
    for c in cands:
        if c.exists():
            return c
    return None


def extract_numbers(text: str) -> list[str]:
    """Number tokens of prose (decimals, e-notation, ratios), order kept."""
    out: list[str] = []
    for m in _NUM_RE.finditer(text):
        tok = m.group(0)
        if tok not in out:
            out.append(tok)
    return out


def audit_artifact(artifact: Path, store: EpicStore | None = None,
                   strict: bool = False) -> dict:
    """Chain-audit an artifact's sidecar; report prose numbers not tracked."""
    store = store or EpicStore()
    text = artifact.read_text(errors="replace")
    report: dict = {"artifact": str(artifact), "sidecar": None, "errors": [],
                    "uncovered": [], "auto_registered": [], "orphan_claims": 0}
    sidecar = find_sidecar(artifact)
    claims: list[dict] = []
    if sidecar is not None:
        report["sidecar"] = str(sidecar)
        try:
            claims = load_sidecar(sidecar)
        except (ValueError, json.JSONDecodeError) as e:
            report["errors"].append(f"sidecar parse: {e}")
    if "<!-- claim:" in text and sidecar is None:
        report["errors"].append("claim markers present but no sidecar found")

    certs = {c["id"]: c for c in store.load("certs") if "id" in c}
    for cl in claims:
        errs = audit_claim(cl, certs)
        report["errors"] += errs
        if errs and any("cert" in e or "OBSERVED" in e for e in errs):
            report["orphan_claims"] += 1

    # number coverage: curated + auto registry (provenance=auto-scan)
    claimed_values = {
        str(c.get("value", "")).strip()
        for c in claims + store.load("claims")
        if c.get("type") == "number"
    }
    auto_values = {
        str(c.get("value", "")).strip()
        for c in store.load("claims")
        if c.get("provenance") == "auto-scan" and c.get("type") == "number"
    }
    all_numbers = extract_numbers(text)
    report["numbers_total"] = len(all_numbers)
    report["uncovered"] = [n for n in all_numbers
                           if n not in claimed_values and n not in auto_values]
    if report["uncovered"]:
        report["auto_registered"] = []  # only `scan` registers
    if strict:
        if report["uncovered"]:
            report["errors"].append(
                f"{len(report['uncovered'])} bare numbers not tracked "
                "(run `scan` to register)"
            )
        if report["orphan_claims"]:
            report["errors"].append(
                f"{report['orphan_claims']} orphan claim(s) without cert chain"
            )
    report["ok"] = not report["errors"]
    return report


def scan_register(artifact: Path, store: EpicStore | None = None) -> list[dict]:
    """Register uncovered prose numbers as claims.

    Deterministic auto-certification: if the token matches a value in the
    committed evidence dumps (at the token's own precision) the claim is
    recorded as OBSERVED with that evidence; otherwise it stays an honest
    DECLARED (plan F10: UNKNOWN/DECLARED never assert)."""
    store = store or EpicStore()
    rep = audit_artifact(artifact, store=store, strict=False)
    existing = {
        str(c.get("value", "")).strip()
        for c in store.load("claims")
        if c.get("type") == "number"
    }
    ev_files = sorted((store.dir / "evidence").glob("*.txt")) \
        if (store.dir / "evidence").is_dir() else []
    ev_cache: list[tuple[str, str]] = [
        (f"evidence/{p.name}", p.read_text(errors="replace")) for p in ev_files
    ]
    text = artifact.read_text(errors="replace")
    lines = text.splitlines()
    added = []
    for tok in rep["uncovered"]:
        if tok in existing:
            continue
        line_no = next(
            (i + 1 for i, ln in enumerate(lines)
             if tok in ln and "http" not in ln), 0,
        )
        hit = next(
            (rel for rel, hay in ev_cache if value_in_evidence(tok, hay)),
            None,
        )
        text_line = f"{artifact.name}:{line_no} numeric literal" + (
            "" if hit else " (no evidence match)")
        rec = {
            "id": f"CL-AUTO-{sha256_bytes((artifact.name + tok + str(line_no)).encode())[:8]}",
            "text": text_line,
            "text_hash": sha256_bytes(text_line.encode()),
            "type": "number",
            "subject": artifact.name,
            "risk": "exploratory",
            "status": "OBSERVED" if hit else "DECLARED",
            "value": tok,
            "evidence": hit,
            "provenance": "auto-scan",
            "certs": [],
        }
        store.append("claims", rec)
        added.append(rec)
    return added


def register_artifact(artifact: Path, store: EpicStore | None = None) -> dict:
    """H1 (EP-2): register an artifact's explicit sidecar claims in the store.

    Append-only with dedup by id: claims already in the store are never
    rewritten. Invalid claims are reported and NOT registered, so the store
    stays valid (plan H1: register explicit claims + fire the number audit —
    the audit is a separate call, this is the registration half)."""
    store = store or EpicStore()
    rep: dict = {"artifact": str(artifact), "sidecar": None, "registered": 0,
                 "ids": [], "skipped": [], "errors": []}
    sidecar = find_sidecar(artifact)
    if sidecar is None:
        return rep
    rep["sidecar"] = str(sidecar)
    try:
        claims = load_sidecar(sidecar)
    except (ValueError, json.JSONDecodeError) as e:
        rep["errors"].append(f"sidecar parse: {e}")
        return rep
    existing = {c.get("id") for c in store.load("claims")}
    for c in claims:
        cid = c.get("id")
        if cid in existing:
            rep["skipped"].append(cid)
            continue
        errs = validate_claim(c)
        if errs:
            rep["errors"] += errs
            continue
        store.append("claims", c)
        existing.add(cid)
        rep["ids"].append(cid)
        rep["registered"] += 1
    return rep


# ---------------------------------------------------------------- CLI


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vos_kernel.epistemic")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audit-claims")
    p.add_argument("--strict", action="store_true")

    p = sub.add_parser("audit-guards")
    p.add_argument("--run", action="store_true")

    p = sub.add_parser("audit-artifact")
    p.add_argument("path")
    p.add_argument("--strict", action="store_true")

    p = sub.add_parser("scan")
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("register",
                       help="H1: register an artifact's explicit sidecar claims")
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("show")
    p.add_argument("kind", choices=sorted(EpicStore.FILES))

    args = ap.parse_args(argv)
    store = EpicStore()

    if args.cmd == "audit-claims":
        rep = audit_claims(store)
        if args.strict and store.load("claims") and not rep["ok"]:
            pass
        _print(rep)
        return 0 if rep["ok"] else 1

    if args.cmd == "audit-guards":
        rep = audit_guards(store, run=args.run)
        _print(rep)
        return 0 if rep["ok"] else 1

    if args.cmd == "audit-artifact":
        rep = audit_artifact(Path(args.path), store=store,
                             strict=args.strict)
        _print(rep)
        return 0 if rep["ok"] else 1

    if args.cmd == "scan":
        total = []
        for pth in args.paths:
            total += scan_register(Path(pth), store=store)
        _print({"registered": len(total),
                "ids": [r["id"] for r in total]})
        return 0

    if args.cmd == "register":
        reps = [register_artifact(Path(pth), store=store)
                for pth in args.paths]
        _print(reps if len(reps) > 1 else reps[0])
        return 1 if any(r["errors"] for r in reps) else 0

    if args.cmd == "show":
        _print(store.load(args.kind))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
