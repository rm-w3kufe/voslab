"""router.py — epistemic router (EP-2 of EPISTEMIC-CERT-001).

Deterministic claim routing (plan S3): every proposition enters through
claim-gate.tree.vsm, which picks its certification route (R0-R5); the
evaluation is persisted as a tree_trace with tree_shape=claim_gate(...).
Session decisions (protocol H2) route through decide.tree, leave a
decide(...) trace and append a DEC record BEFORE execution.

Routes (tree homes, priority order = guard order in the tree):
  R0 RECYCLE       hash-matched CRT => link (no claim certified twice)
  R1 MACHINE       checkable=machine => CRT FORMAL|PREDICATE;
                   F16: type=conformance @ risk=delivery requires
                   independent_source=true — monocanal evidence lands on
                   home R1-FAIL => route R1, status FAIL, verdict FAIL,
                   exit 1 (one desensitized channel proves self-consistency,
                   not health)
  R2 OBSERVED      falsifier=true => CRT PREDICATE|IDENTITY, ceiling
                   OBSERVED (never CERTIFIED without FORMAL)
  R3 INTERPRETIVE  type=interpretation => ceiling INTERPRETIVE, CRT AUDIT
                   (checked BEFORE R1: the semantic never ascends via the
                   formal channel)
  R4 DECISION      type=decision => decide.tree; blocked => verdict FAIL
  R5 UNKNOWN       no route => declared UNKNOWN (never asserted, F10)

Output contract: {claim_id, route, status, verdict, required_certs[],
f16, trace_id, tree_shape}. verdict is the ROUTE verdict (PASS = a valid
certification path exists; FAIL = routing impossible: F16 violation or a
blocked decision). `status` is the lattice state (plan S2); FAIL is the
one non-lattice value, reserved for the blocked routes above.

CLI (the plan's `vsctl`, thin wrapper at scripts/vsl/vsctl):
  python3 -m vos_kernel.router route <claim.json|claim-id>
  python3 -m vos_kernel.router route --all
  python3 -m vos_kernel.router decide --question Q --alternatives a,b
      --impact I [--reversible true|false] [--approved]

Deterministic (R10): no randomness; same claim => same route/status.
Substrate-agnostic (plan S7): this module names tree files and the trace
store, never a runtime or a host.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from vos_kernel.epistemic import (
    CLAIM_TYPES,
    EpicStore,
    now_iso,
    repo_root,
    sha256_bytes,
    validate_claim,
)

# ------------------------------------------------------------------ policy

CLAIM_GATE_TREE = "claim-gate.tree.vsm"
DECIDE_TREE = "decide.tree.vsm"
CLAIM_GATE_NAME = "CLAIM-GATE"

# Route inputs derived from the claim when it carries no explicit
# checkable/falsifier field (documented derivation, deterministic).
DEFAULT_CHECKABLE = {
    "theorem": "machine",
    "number": "machine",
    "conformance": "machine",
    "empirical": "partial",
    "interpretation": "none",
    "decision": "none",
    "procedure": "partial",
}
DEFAULT_FALSIFIER = {
    "theorem": "false",
    "number": "true",
    "conformance": "false",
    "empirical": "true",
    "interpretation": "false",
    "decision": "false",
    "procedure": "false",
}

# required_certs per route (plan S3: which certificate classes the route
# demands before the claim may ascend the lattice).
REQUIRED_CERTS = {
    "R0": [],           # linked; demands nothing new unless status says so
    "R1": ["FORMAL", "PREDICATE"],
    "R2": ["PREDICATE", "IDENTITY"],
    "R3": ["AUDIT"],
    "R4": [],           # decide.tree is the gate, not a CRT class
    "R5": [],
}


def trees_dir() -> Path:
    return repo_root() / ".opencode" / "plugins" / "support" / "trees"


def _load_tree(name: str):
    from socratic_engine.tree import load_tree

    tree = load_tree(trees_dir() / name)
    if tree is None:
        raise FileNotFoundError(f"tree not loadable: {trees_dir() / name}")
    return tree


def _engine():
    # Bare engine: claim-gate and decide use only built-in ctx_* predicates
    # (verified: ctx_has/ctx_equals are engine builtins).
    from socratic_engine import SocraticEngine

    return SocraticEngine()


def _trace_logger():
    """TreeTraceLogger lives in system/kernel (not a package) — import by
    path. VOSLAB_PATH is re-read at runtime, so tests can redirect the
    trace store by setting the env before calling."""
    kernel_dir = repo_root() / "system" / "kernel"
    if str(kernel_dir) not in sys.path:
        sys.path.insert(0, str(kernel_dir))
    from tree_trace_logger import TreeTraceLogger

    return TreeTraceLogger()


# ------------------------------------------------------------------- input


def _cert_present(claim: dict, certs_by_id: dict[str, dict]) -> bool:
    """Hash-matched certificate for THIS claim in the CRT store.

    Two accepted linkages (both declared, deterministic):
      1. hash-match  — the CRT names this claim and its inputs_digest
         equals the claim text_hash (stale certs do not match);
      2. shared ref  — the CRT is claim-agnostic (claim_id "SHARED", the
         companion convention) and the claim references it by id.
    """
    th = str(claim.get("text_hash", "")).removeprefix("sha256:")
    for cid in claim.get("certs", []):
        c = certs_by_id.get(cid)
        if not c:
            continue
        if c.get("claim_id") == "SHARED":
            return True
        dig = str(c.get("inputs_digest", "")).removeprefix("sha256:")
        if c.get("claim_id") == claim.get("id") and th and dig == th:
            return True
    return False


def build_ctx(claim: dict, certs_by_id: dict[str, dict]) -> dict:
    """Route inputs (plan S3): claim_type, checkable, falsifier, risk,
    cert_present, independent_source — all strings for ctx_equals."""
    ctype = claim.get("type")
    checkable = claim.get("checkable") or DEFAULT_CHECKABLE.get(ctype, "none")
    if claim.get("falsifier") is None:
        falsifier = DEFAULT_FALSIFIER.get(ctype, "false")
    else:
        falsifier = "true" if claim["falsifier"] else "false"

    resolved = [certs_by_id[c] for c in claim.get("certs", [])
                if c in certs_by_id]
    if claim.get("independent_source") is None:
        independent = ("true" if any(c.get("independent") for c in resolved)
                       else "false")
    else:
        independent = "true" if claim["independent_source"] else "false"

    return {
        "claim_type": ctype,
        "checkable": checkable,
        "falsifier": falsifier,
        "risk": claim.get("risk", "exploratory"),
        "cert_present": "true" if _cert_present(claim, certs_by_id)
                        else "false",
        "independent_source": independent,
    }


def _f16(claim: dict, ctx: dict) -> str:
    """F16 applicability: satisfied | violated | not-subject."""
    if claim.get("type") != "conformance" or claim.get("risk") != "delivery":
        return "not-subject"
    return "satisfied" if ctx["independent_source"] == "true" else "violated"


# ------------------------------------------------------------------ decide


def decide_ctx(question: str, alternatives=None, impact: str = "",
               reversible: bool = True, approved: bool = False,
               skips: dict | None = None) -> dict:
    """Context for decide.tree (same shape scripts/vsl/classifier/decide.py
    feeds through SOCRATIC_CTX)."""
    ctx: dict = {"decision": question,
                 "reversible": "true" if reversible else "false"}
    if alternatives:
        ctx["alternatives"] = (list(alternatives) if isinstance(alternatives, (list, tuple))
                               else [alternatives])
    if impact:
        ctx["impact"] = impact
    if not reversible and approved:
        ctx["approved"] = "true"
    for k in ("alternatives", "impact", "approval"):
        if (skips or {}).get(k):
            ctx[f"skip_{k}"] = "true"
    return ctx


def evaluate_decide(ctx: dict, logger=None) -> dict:
    """Evaluate decide.tree (H2) and persist a decide(...) trace."""
    tree = _load_tree(DECIDE_TREE)
    engine = _engine()
    t0 = time.perf_counter()
    ev = engine.evaluate(tree, ctx)
    latency = (time.perf_counter() - t0) * 1000.0
    out = {
        "truth": bool(ev.is_true),
        "certified": bool(ev.certified),
        "outcome": "approved" if ev.is_true else "blocked",
    }
    if logger is not None:
        trace = logger.capture(ev, tree, dict(ctx), latency_ms=latency)
        trace.tree_shape = f"decide({trace.tree_shape})"
        logger.persist(trace)
        out["trace_id"] = trace.trace_id
        out["tree_shape"] = trace.tree_shape
    return out


def decide(question: str, alternatives=None, impact: str = "",
           reversible: bool = True, approved: bool = False,
           skips: dict | None = None, store: EpicStore | None = None,
           logger=None) -> dict:
    """H2 protocol: decide.tree FIRST, DEC record with the trace id, the
    decision outcome governs whether the session may execute it."""
    store = store or EpicStore()
    ctx = decide_ctx(question, alternatives, impact, reversible,
                     approved, skips)
    res = evaluate_decide(ctx, logger=logger)
    dec = {
        "id": f"DEC-{sha256_bytes((question + now_iso()).encode())[:10]}",
        "question": question,
        "alternatives": ctx.get("alternatives", ["(none declared)"]),
        "impact": impact or "(not declared)",
        "reversible": bool(reversible),
        "approved": bool(approved and not reversible),
        "tree_trace_id": res.get("trace_id", ""),
        "outcome": res["outcome"],
    }
    store.append("decisions", dec)
    res["decision_id"] = dec["id"]
    return res


def _decide_ctx_from_claim(claim: dict) -> dict:
    return decide_ctx(
        question=str(claim.get("text") or claim.get("id") or ""),
        alternatives=claim.get("alternatives"),
        impact=str(claim.get("impact") or ""),
        reversible=bool(claim.get("reversible", True)),
        approved=bool(claim.get("approved", False)),
    )


# ------------------------------------------------------------------- route


def _r0_status(claim: dict, ctx: dict,
               certs_by_id: dict[str, dict]) -> tuple[str, list[str]]:
    """Status of a recycled claim from its linked CRT class (plan R0:
    'link + status del CRT class')."""
    resolved = [certs_by_id[c] for c in claim.get("certs", [])
                if c in certs_by_id]
    passing = [c for c in resolved if c.get("verdict") == "pass"]
    failing = [c for c in resolved if c.get("verdict") == "fail"]
    f16 = _f16(claim, ctx)
    if passing:
        proper = [c for c in passing
                  if c.get("class") in ("FORMAL", "PREDICATE")]
        if proper and f16 in ("not-subject", "satisfied"):
            return "CERTIFIED", []
        return "OBSERVED", REQUIRED_CERTS["R1"]  # ceiling until proper cert
    if failing:
        return "REFUTED", []
    return "OBSERVED", REQUIRED_CERTS["R1"]


def route_claim(claim: dict, store: EpicStore | None = None,
                logger=None) -> dict:
    """Route one claim through claim-gate; persist the claim_gate trace."""
    from socratic_engine.tree import tree_home

    store = store or EpicStore()
    errs = validate_claim(claim)
    if errs:
        raise ValueError("invalid claim: " + "; ".join(errs))

    certs_by_id = {c["id"]: c for c in store.load("certs") if "id" in c}
    ctx = build_ctx(claim, certs_by_id)
    tree = _load_tree(CLAIM_GATE_TREE)
    engine = _engine()
    t0 = time.perf_counter()
    ev = engine.evaluate(tree, dict(ctx, type=CLAIM_GATE_NAME))
    home = tree_home(tree, CLAIM_GATE_NAME, engine, ctx)
    latency = (time.perf_counter() - t0) * 1000.0

    if logger is None:
        logger = _trace_logger()

    result: dict = {
        "claim_id": claim.get("id"),
        "route": "R1" if home == "R1-FAIL" else home,
        "status": "",
        "verdict": "PASS",
        "required_certs": list(REQUIRED_CERTS.get(home, [])),
        "f16": _f16(claim, ctx),
    }

    if home == "R0":
        status, req = _r0_status(claim, ctx, certs_by_id)
        result["status"], result["required_certs"] = status, req
    elif home == "R1":
        # current honest lattice state; required_certs drive the ascent
        result["status"] = str(claim.get("status", "DECLARED"))
    elif home == "R1-FAIL":
        result["status"] = "FAIL"
        result["verdict"] = "FAIL"
        result["required_certs"] = ["FORMAL", "PREDICATE", "INDEPENDENT"]
        result["reason"] = ("F16: conformance@delivery monocanal — "
                            "independent_source=false cannot certify")
    elif home == "R2":
        result["status"] = "OBSERVED"
        result["reason"] = "ceiling OBSERVED: never CERTIFIED without FORMAL"
    elif home == "R3":
        result["status"] = "INTERPRETIVE"
    elif home == "R4":
        dres = evaluate_decide(_decide_ctx_from_claim(claim),
                               logger=logger)
        result["decide"] = dres
        if dres["outcome"] == "blocked":
            result["status"] = "FAIL"
            result["verdict"] = "FAIL"
            result["reason"] = ("decision blocked by decide.tree "
                                "(alternatives/impact/approval)")
        else:
            result["status"] = str(claim.get("status", "DECLARED"))
    elif home == "R5":
        result["status"] = "UNKNOWN"
        result["reason"] = "declared UNKNOWN, never asserted (F10)"
    else:
        # tree_home returned None (unknown input) — R9: visible, not silent
        result["route"] = "?"
        result["status"] = "UNKNOWN"
        result["verdict"] = "FAIL"
        result["reason"] = f"unroutable home {home!r}"

    trace = logger.capture(ev, tree, dict(ctx), latency_ms=latency)
    trace.tree_shape = f"claim_gate({trace.tree_shape})"
    logger.persist(trace)
    result["trace_id"] = trace.trace_id
    result["tree_shape"] = trace.tree_shape
    return result


def route_all(store: EpicStore | None = None, logger=None) -> dict:
    """Round helper: route every claim in the store (plan round step R1)."""
    store = store or EpicStore()
    results = [route_claim(c, store=store, logger=logger)
               for c in store.load("claims")]
    routes: dict[str, int] = {}
    for r in results:
        routes[r["route"]] = routes.get(r["route"], 0) + 1
    failed = [r["claim_id"] for r in results if r["verdict"] != "PASS"]
    return {
        "routed": len(results),
        "routes": dict(sorted(routes.items())),
        "failed": failed,
        "trace_ids": [r["trace_id"] for r in results],
    }


# --------------------------------------------------------------------- CLI


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="vsctl",
        description="epistemic router (claim-gate + decide, EP-2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("route",
                       help="route a claim through claim-gate.tree.vsm")
    p.add_argument("claim", nargs="?",
                   help="claim JSON file or claim id in the store")
    p.add_argument("--all", action="store_true",
                   help="route every claim in the store")

    p = sub.add_parser("decide",
                       help="H2: decide.tree first, DEC record after")
    p.add_argument("--question", required=True)
    p.add_argument("--alternatives", help="comma-separated alternatives")
    p.add_argument("--impact", default="")
    p.add_argument("--reversible", choices=("true", "false"),
                   default="true")
    p.add_argument("--approved", action="store_true",
                   help="approval present (required if irreversible)")
    p.add_argument("--skip-alternatives", action="store_true")
    p.add_argument("--skip-impact", action="store_true")
    p.add_argument("--skip-approval", action="store_true")

    args = ap.parse_args(argv)
    logger = _trace_logger()

    if args.cmd == "route":
        if args.all:
            rep = route_all(logger=logger)
            _print(rep)
            return 1 if rep["failed"] else 0
        if not args.claim:
            ap.error("route needs <claim> or --all")
        src = Path(args.claim)
        if src.exists():
            claim = json.loads(src.read_text(encoding="utf-8"))
        else:
            claim = EpicStore().get("claims", args.claim)
            if claim is None:
                print(f"claim not found: {args.claim}", file=sys.stderr)
                return 2
        res = route_claim(claim, logger=logger)
        _print(res)
        return 0 if res["verdict"] == "PASS" else 1

    if args.cmd == "decide":
        alts = ([a for a in args.alternatives.split(",") if a]
                if args.alternatives else None)
        skips = {"alternatives": args.skip_alternatives,
                 "impact": args.skip_impact,
                 "approval": args.skip_approval}
        res = decide(
            args.question, alternatives=alts, impact=args.impact,
            reversible=(args.reversible == "true"),
            approved=args.approved, skips=skips, logger=logger,
        )
        _print(res)
        return 0 if res["outcome"] == "approved" else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
