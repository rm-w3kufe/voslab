"""tests for D-06 FASE C3 — chained-hash verdict records.

Covers:
  - seal(): additive copy, deterministic hash, caller not mutated
  - verify_rounds(): intact chain is ok
  - tampered payload detected (hash mismatch)
  - broken linkage detected (prev_hash != predecessor record_hash)
  - first sealed record must chain to GENESIS
  - legacy unsealed records reported, never fail the chain
  - round_runner.emit(): writes sealed records linked round-to-round
"""
import json
from pathlib import Path

import pytest

from vos_kernel import hash_chain as hc
from vos_kernel import round_runner as rr


def _record(i: int, **over) -> dict:
    rec = {"round_id": f"ROUND-2026010{i}T000000000000Z",
           "verdict": "GREEN", "reasons": [],
           "metrics": {"M1": {"value": i, "target": ">0", "ok": True}},
           "closed_at": f"2026-01-0{i}T00:00:00Z"}
    rec.update(over)
    return rec


def _write(dirpath: Path, record: dict) -> Path:
    path = dirpath / record["round_id"]
    if not path.suffix:
        path = dirpath / (record["round_id"] + ".json")
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def _chain(dirpath: Path, n: int) -> list[dict]:
    """Write n correctly sealed records, return the sealed dicts."""
    sealed = []
    prev = hc.GENESIS
    for i in range(n):
        rec = hc.seal(_record(i), prev)
        _write(dirpath, rec)
        sealed.append(rec)
        prev = rec["record_hash"]
    return sealed


class TestSeal:
    def test_adds_chain_fields_deterministically(self):
        a = hc.seal(_record(0), hc.GENESIS)
        b = hc.seal(_record(0), hc.GENESIS)
        assert a == b
        assert a["prev_hash"] == hc.GENESIS
        assert len(a["record_hash"]) == 64

    def test_does_not_mutate_input_and_is_resealable(self):
        rec = _record(1)
        sealed = hc.seal(rec, hc.GENESIS)
        assert "record_hash" not in rec and "prev_hash" not in rec
        # stale chain fields on the input are stripped, not hashed twice
        stale = dict(rec, prev_hash="old", record_hash="old2")
        assert hc.seal(stale, hc.GENESIS) == sealed

    def test_prev_hash_changes_the_record_hash(self):
        a = hc.seal(_record(0), hc.GENESIS)
        b = hc.seal(_record(0), "x" * 64)
        assert a["record_hash"] != b["record_hash"]

    def test_is_sealed(self):
        assert not hc.is_sealed(_record(0))
        assert hc.is_sealed(hc.seal(_record(0), hc.GENESIS))


class TestVerify:
    def test_intact_chain_ok(self, tmp_path):
        _chain(tmp_path, 3)
        report = hc.verify_rounds(tmp_path)
        assert report["status"] == "ok"
        assert report["sealed"] == 3
        assert report["errors"] == []
        assert report["unsealed"] == []

    def test_empty_dir_ok(self, tmp_path):
        report = hc.verify_rounds(tmp_path)
        assert report == {"status": "ok", "sealed": 0,
                          "unsealed": [], "errors": []}

    def test_tampered_payload_detected(self, tmp_path):
        sealed = _chain(tmp_path, 3)
        # flip a payload value in record 2, keep its stored hash
        path = tmp_path / (sealed[1]["round_id"] + ".json")
        record = json.loads(path.read_text())
        record["verdict"] = "NOT_GREEN"
        path.write_text(json.dumps(record, indent=1) + "\n")
        report = hc.verify_rounds(tmp_path)
        assert report["status"] == "FAIL"
        assert any("hash mismatch" in e and sealed[1]["round_id"] in e
                   for e in report["errors"])

    def test_broken_link_detected(self, tmp_path):
        sealed = _chain(tmp_path, 3)
        path = tmp_path / (sealed[2]["round_id"] + ".json")
        record = json.loads(path.read_text())
        record["prev_hash"] = "0" * 64  # not record 2's hash
        record["record_hash"] = hc.payload_hash(
            {k: v for k, v in record.items() if k not in hc.CHAIN_FIELDS},
            record["prev_hash"])
        path.write_text(json.dumps(record, indent=1) + "\n")
        report = hc.verify_rounds(tmp_path)
        assert report["status"] == "FAIL"
        assert any("broken link" in e and sealed[2]["round_id"] in e
                   for e in report["errors"])

    def test_first_sealed_record_must_be_genesis(self, tmp_path):
        wrong = hc.seal(_record(0), "f" * 64)
        _write(tmp_path, wrong)
        report = hc.verify_rounds(tmp_path)
        assert report["status"] == "FAIL"
        assert any("broken link" in e for e in report["errors"])

    def test_legacy_unsealed_reported_but_chain_ok(self, tmp_path):
        # legacy pre-C3 record: no chain fields (older round id than the chain)
        _write(tmp_path, _record(0, round_id="ROUND-20251231T000000000000Z"))
        _chain(tmp_path, 2)
        report = hc.verify_rounds(tmp_path)
        assert report["status"] == "ok"
        assert report["sealed"] == 2
        assert report["unsealed"] == ["ROUND-20251231T000000000000Z.json"]

    def test_legacy_between_sealed_records_does_not_break_link(
            self, tmp_path):
        # chain linkage is computed over SEALED records only
        _write(tmp_path, _record(0))            # legacy, oldest
        s1 = hc.seal(_record(1), hc.GENESIS)
        _write(tmp_path, s1)
        _write(tmp_path, _record(2))            # legacy in the middle
        s3 = hc.seal(_record(3), s1["record_hash"])
        _write(tmp_path, s3)
        report = hc.verify_rounds(tmp_path)
        assert report["status"] == "ok"
        assert report["sealed"] == 2
        assert len(report["unsealed"]) == 2


class TestLastSealedHash:
    def test_empty_dir_is_genesis(self, tmp_path):
        assert hc.last_sealed_hash(tmp_path) == hc.GENESIS

    def test_only_legacy_is_genesis(self, tmp_path):
        _write(tmp_path, _record(0))
        assert hc.last_sealed_hash(tmp_path) == hc.GENESIS

    def test_returns_newest_sealed_hash(self, tmp_path):
        sealed = _chain(tmp_path, 3)
        # an unsealed NEWER record must not hide the sealed tip
        _write(tmp_path, _record(9))
        assert hc.last_sealed_hash(tmp_path) == sealed[2]["record_hash"]


class TestEmitIntegration:
    def _rec(self, i: int, **over) -> dict:
        return _record(i, **over)

    def test_emit_writes_sealed_record(self, tmp_path):
        rec = self._rec(0)
        rr.emit(rec, tmp_path)
        path = tmp_path / "state" / "epistemic" / "rounds" / (rec["round_id"] + ".json")
        written = json.loads(path.read_text())
        assert hc.is_sealed(written)
        assert written["prev_hash"] == hc.GENESIS
        assert written["verdict"] == "GREEN"
        # caller's record stays unmutated (event uses the raw record)
        assert "record_hash" not in rec
        assert hc.verify_rounds(path.parent)["status"] == "ok"

    def test_successive_emits_link_round_to_round(self, tmp_path):
        r1 = self._rec(1)
        r2 = self._rec(2)
        rr.emit(r1, tmp_path)
        rr.emit(r2, tmp_path)
        rounds = tmp_path / "state" / "epistemic" / "rounds"
        w1 = json.loads((rounds / (r1["round_id"] + ".json")).read_text())
        w2 = json.loads((rounds / (r2["round_id"] + ".json")).read_text())
        assert w2["prev_hash"] == w1["record_hash"]
        report = hc.verify_rounds(rounds)
        assert report["status"] == "ok" and report["sealed"] == 2

    def test_emit_links_across_legacy_rounds(self, tmp_path):
        rounds = tmp_path / "state" / "epistemic" / "rounds"
        rounds.mkdir(parents=True)
        # committed-style legacy record (unsealed, older name)
        (rounds / "ROUND-20261001T154628587240Z.json").write_text(
            json.dumps(_record(0)) + "\n")
        rec = self._rec(1, round_id="ROUND-20261002T000000000000Z")
        rr.emit(rec, tmp_path)
        report = hc.verify_rounds(rounds)
        assert report["status"] == "ok"
        assert report["sealed"] == 1
        assert len(report["unsealed"]) == 1
