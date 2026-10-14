"""Tests for instrument_manifest (F2, second-order-loop). Deterministic (R10)."""
import json
from pathlib import Path

from vos_kernel import instrument_manifest as im


def _good(**over):
    m = {
        "id": "test-instrument",
        "sn": "S4",
        "nested_fn": "S1",
        "driver": "projector_directive",  # B4[S4]
        "canal": "modelo",
        "emits": ["veredicto"],
        "consumes": ["canon"],
        "consent": "advisory",
        "on_ratified": "none",
    }
    m.update(over)
    return m


def test_valid_manifest_passes():
    assert im.validate_manifest(_good()) == []


def test_missing_field_fails():
    m = _good()
    del m["consent"]
    errs = im.validate_manifest(m)
    assert any("missing field: consent" in e for e in errs)


def test_wrong_driver_fails_b4():
    # S4 driver must be projector_directive — inventing another fails (B4, R10).
    errs = im.validate_manifest(_good(driver="consent_gate"))
    assert any("B4" in e for e in errs)


def test_driver_matches_b4_per_sn():
    # each Sn validates against its own B4 driver
    assert im.validate_manifest(_good(sn="S5", driver="consent_gate",
                                      nested_fn="S3*")) == []
    assert im.validate_manifest(_good(sn="S5", driver="audit_scanner")) != []


def test_invalid_consent_fails():
    errs = im.validate_manifest(_good(consent="destructive"))
    assert any("consent" in e for e in errs)


def test_invalid_emits_fails():
    errs = im.validate_manifest(_good(emits=["hallucination"]))
    assert any("emits" in e for e in errs)


def test_non_kebab_id_fails():
    errs = im.validate_manifest(_good(id="Not_Kebab"))
    assert any("kebab" in e for e in errs)


def test_index_by_seat_only_seats_valid():
    good = _good()
    bad = _good(id="bad-driver", driver="wrong")
    idx = im.index_by_seat([good, bad])
    assert idx == {("S4", "S1"): ["test-instrument"]}


def test_query_filters():
    a = _good()
    b = _good(id="other", sn="S5", nested_fn="S3*", driver="consent_gate")
    ms = [a, b]
    assert [m["id"] for m in im.query(ms, sn="S5")] == ["other"]
    assert [m["id"] for m in im.query(ms, nested_fn="S1")] == ["test-instrument"]
    assert [m["id"] for m in im.query(ms, id="other")] == ["other"]
    assert len(im.query(ms)) == 2


def test_validate_deterministic():
    m = _good(driver="wrong")
    r1 = im.validate_manifest(m)
    for _ in range(20):
        assert im.validate_manifest(m) == r1


def test_onboard_refuses_invalid(tmp_path: Path):
    src = tmp_path / "bad.json"
    src.write_text(json.dumps(_good(driver="nope")))
    errs = im.onboard(tmp_path / "store", src)
    assert errs  # refused
    assert not (tmp_path / "store" / "test-instrument.json").exists()


def test_onboard_installs_valid(tmp_path: Path):
    src = tmp_path / "ok.json"
    src.write_text(json.dumps(_good()))
    store = tmp_path / "store"
    assert im.onboard(store, src) == []
    assert (store / "test-instrument.json").exists()
    loaded = im.load_manifests(store)
    assert [m["id"] for m in loaded] == ["test-instrument"]
