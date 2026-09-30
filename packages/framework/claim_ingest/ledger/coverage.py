"""Coverage predicate (R10): every health claim shows its denominator.

Buckets (mutually exclusive, exhaustive over `total`):
  verified      — registry status CERTIFIED
  refuted       — registry status REFUTED
  untested      — DECLARED / OBSERVED / UNKNOWN (not yet settled)
  out_of_scope  — explicitly flagged `scope: "out_of_scope"` (never
                  silently folded into untested)

Route counts ride along as a distribution, not as coverage — routing is
the gate's opinion, not evidence.
"""
from __future__ import annotations


def coverage(claims: list[dict], routes: list[dict] | None = None) -> dict:
    buckets = {"verified": 0, "refuted": 0, "untested": 0,
               "out_of_scope": 0}
    for c in claims:
        if c.get("scope") == "out_of_scope":
            buckets["out_of_scope"] += 1
            continue
        st = c.get("status")
        if st == "CERTIFIED":
            buckets["verified"] += 1
        elif st == "REFUTED":
            buckets["refuted"] += 1
        else:
            buckets["untested"] += 1
    out: dict = dict(buckets)
    out["total"] = len(claims)
    if routes is not None:
        rc: dict = {}
        for r in routes:
            key = str(r.get("route", "?"))
            rc[key] = rc.get(key, 0) + 1
        out["routes"] = dict(sorted(rc.items()))
    return out
