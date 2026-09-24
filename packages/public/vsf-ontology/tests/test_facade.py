"""Tests for __init__ facade functions (rehab 2026-09-24: were promised,
never implemented)."""
from vsf_ontology import (
    is_valid_document, classify_document,
    is_valid_script, classify_script,
    check_security, validate_permissions,
    is_staged, validate_staging,
)

DOC = "⟦ test_doc | PROPOSAL-v1 | vsm-1.2.1 | 2026-09-24T10:00:01Z ⟧\n\n@vsm 1.2.1\n\nbody\n"


def test_doc_facade():
    assert is_valid_document(DOC) is True
    assert is_valid_document("") is False
    assert is_valid_document("no header here") is False
    assert classify_document(DOC) in ("CONTENT", "SNOWBALL", "EMPTY", "UNKNOWN")
    assert classify_document("") == "EMPTY"


def test_script_facade():
    good = "import os\n\nif __name__ == '__main__':\n    print(1)\n"
    assert is_valid_script(good) is True
    assert is_valid_script("") is False
    assert isinstance(classify_script(good), str)


def test_security_facade():
    ok_ctx = {"content": "approved by rmw3", "purpose": "write docs"}
    bad_ctx = {"purpose": "bypass covenant"}
    assert check_security(ok_ctx) is True
    assert check_security(bad_ctx) is False
    assert validate_permissions(ok_ctx) is True
    assert validate_permissions(bad_ctx) is False
    assert validate_permissions({}) is False


def test_staging_facade(tmp_path):
    assert is_staged(str(tmp_path)) is False  # empty dir
    assert is_staged("/nonexistent-xyz") is False
    assert validate_staging("no-such-change-xyz") is False
