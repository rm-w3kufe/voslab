"""Tests for vos_kernel.epistemic — EP-1 of EPISTEMIC-CERT-001.

Deterministic only (R10): fixed inputs, fixed expectations, temp stores.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vos_kernel.epistemic import (
    EpicStore,
    audit_artifact,
    audit_claim,
    audit_claims,
    audit_guards,
    extract_numbers,
    load_sidecar,
    new_doc_sidecar,
    scan_register,
    validate_claim,
    validate_finding,
    value_in_evidence,
)


def _claim(**over):
    base = {
        "id": "CL-T1", "text": "t", "text_hash": "", "type": "number",
        "subject": "s.md", "risk": "delivery", "status": "DECLARED",
        "provenance": "test", "certs": [], "value": "1.0",
    }
    base.update(over)
    if base.get("text"):
        import hashlib
        base["text_hash"] = hashlib.sha256(base["text"].encode()).hexdigest()
    return base


def _cert(cid="CRT-T1", verdict="pass", independent=False, claim_id="SHARED"):
    return {
        "id": cid, "claim_id": claim_id, "class": "PREDICATE",
        "executor_ref": "tester@sha256:" + "0" * 64,
        "inputs_digest": "sha256:" + "0" * 64, "verdict": verdict,
        "observed_at": "2026-09-27T21:00:00Z", "independent": independent,
    }


class TestValidators(unittest.TestCase):
    def test_interpretation_ceiling(self):
        errs = validate_claim(_claim(type="interpretation", status="CERTIFIED",
                                     value=None))
        self.assertTrue(any("INTERPRETIVE" in e for e in errs))

    def test_number_needs_value(self):
        errs = validate_claim(_claim(type="number", value=None))
        self.assertTrue(any("value" in e for e in errs))

    def test_fix_without_guard_rejected(self):
        errs = validate_finding({
            "id": "F1", "symptom": "s", "root_cause": "r", "fix": "patch",
            "guard": "", "guard_status": "none",
        })
        self.assertTrue(any("F→G" in e for e in errs))

    def test_finding_without_fix_ok(self):
        errs = validate_finding({
            "id": "F1", "symptom": "s", "root_cause": "r", "fix": "",
            "guard": "", "guard_status": "none",
        })
        self.assertEqual(errs, [])


class TestValueMatch(unittest.TestCase):
    def test_exact_substring(self):
        self.assertTrue(value_in_evidence("24/24", "panel 24/24 done"))

    def test_tolerant_rounding(self):
        # prose rounds to 5 digits, output keeps full precision
        self.assertTrue(value_in_evidence("0.91492", "lambda1 = 0.91491853"))

    def test_tolerant_scientific(self):
        self.assertTrue(value_in_evidence("8.9e-16", "residual 8.882e-16"))

    def test_mismatch_rejected(self):
        self.assertFalse(value_in_evidence("0.91493", "lambda1 = 0.91491853"))

    def test_zero_needs_exact_zero(self):
        self.assertTrue(value_in_evidence("0.0", "nu = 0.0 floor"))
        self.assertFalse(value_in_evidence("0.0", "residual 3.1e-5"))

    def test_ratio_precision(self):
        # 9/11 must not match a stray 1.0
        self.assertTrue(value_in_evidence("9/11", "ratio = 0.818182"))
        self.assertFalse(value_in_evidence("9/11", "ratio = 1.000000"))


class TestChainAudit(unittest.TestCase):
    def test_certified_without_cert_fails(self):
        errs = audit_claim(_claim(status="CERTIFIED"), {})
        self.assertTrue(any("CERTIFIED without passing cert" in e for e in errs))

    def test_certified_with_pass_cert_ok(self):
        c = _claim(status="CERTIFIED", certs=["CRT-T1"])
        self.assertEqual(audit_claim(c, {"CRT-T1": _cert()}), [])

    def test_delivery_conformance_needs_independent(self):
        c = _claim(type="conformance", status="CERTIFIED", certs=["CRT-T1"],
                   value="24/24")
        errs = audit_claim(c, {"CRT-T1": _cert(independent=False)})
        self.assertTrue(any("independent" in e for e in errs))
        errs = audit_claim(c, {"CRT-T1": _cert(independent=True)})
        self.assertEqual(errs, [])

    def test_unresolvable_cert_ref(self):
        c = _claim(status="CERTIFIED", certs=["CRT-NOPE"])
        errs = audit_claim(c, {"CRT-T1": _cert()})
        self.assertTrue(any("not found" in e for e in errs))

    def test_observed_needs_evidence(self):
        errs = audit_claim(_claim(status="OBSERVED"), {})
        self.assertTrue(any("evidence" in e for e in errs))


class TestStoreAudits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ep1_test_")
        self.store = EpicStore(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_coverage_100_with_guard(self):
        self.store.append("guards", {"id": "G1", "cmd": ["true"],
                                     "expect": ["x"], "ts": "2026-09-27T21:00:00Z"})
        self.store.append("findings", {
            "id": "F1", "symptom": "s", "root_cause": "r", "fix": "f",
            "guard": "G1", "guard_status": "live", "learn_ref": "t",
        })
        rep = audit_guards(self.store)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["coverage"], 1.0)

    def test_coverage_fails_on_orphan_fix(self):
        self.store.append("findings", {
            "id": "F1", "symptom": "s", "root_cause": "r", "fix": "f",
            "guard": "G-MISSING", "guard_status": "live", "learn_ref": "t",
        })
        rep = audit_guards(self.store)
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["missing"], ["F1"])

    def test_claims_audit_counts(self):
        self.store.append("certs", _cert())
        self.store.append("claims", _claim(status="CERTIFIED",
                                           certs=["CRT-T1"]))
        rep = audit_claims(self.store)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["claims"], 1)


class TestSidecar(unittest.TestCase):
    def test_roundtrip(self):
        claims = [_claim(status="DECLARED")]
        content = new_doc_sidecar("t_claims", claims)
        with tempfile.NamedTemporaryFile(
                "w", suffix=".claims.vsm", delete=False) as f:
            f.write(content)
            p = Path(f.name)
        try:
            loaded = load_sidecar(p)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["id"], "CL-T1")
        finally:
            p.unlink()


class TestScan(unittest.TestCase):
    def test_scan_registers_and_matches(self):
        with tempfile.TemporaryDirectory(prefix="ep1_scan_") as tmp:
            root = Path(tmp)
            store = EpicStore(root)
            ev = store.dir / "evidence"
            ev.mkdir(parents=True, exist_ok=True)
            (ev / "dump.txt").write_text("panel 24/24, lambda 0.91491853\n")
            art = root / "NOTE.md"
            art.write_text(
                "# t\n\npanel 24/24 confirmed; stray 0.91492 present; "
                "and 123.456 with no evidence.\n"
            )
            added = scan_register(art, store=store)
            self.assertEqual(len(added), 3)
            by_val = {a["value"]: a for a in added}
            self.assertEqual(by_val["24/24"]["status"], "OBSERVED")
            self.assertEqual(by_val["0.91492"]["status"], "OBSERVED")
            self.assertEqual(by_val["123.456"]["status"], "DECLARED")
            rep = audit_artifact(art, store=store, strict=True)
            self.assertTrue(rep["ok"], rep["errors"])
            self.assertEqual(rep["uncovered"], [])

    def test_extract_numbers_unique_order(self):
        nums = extract_numbers("a 1.5 b 2/3 c 1.5 d 4.0")
        self.assertEqual(nums, ["1.5", "2/3", "4.0"])


if __name__ == "__main__":
    unittest.main()
