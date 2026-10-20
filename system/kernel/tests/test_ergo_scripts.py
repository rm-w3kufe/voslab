# design: docs/plans/ergo_batches_adopted.vsm
"""Gate tests for the DISTILL batch-1 adopted wrappers (verify.sh, sshq.sh).

design: docs/plans/ergo_batches_adopted.vsm
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = ["scripts/verify.sh", "scripts/sshq.sh"]


def test_r16_headers_present():
    for rel in SCRIPTS:
        head = (REPO / rel).read_text(encoding="utf-8").splitlines()[:10]
        text = "\n".join(head)
        assert "design:" in text, f"{rel} missing design: header"
        assert "route:" in text, f"{rel} missing route: header"


def test_verify_usage_rc2_on_bad_mode():
    r = subprocess.run(
        ["bash", str(REPO / "scripts/verify.sh"), "badmode"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 2
    assert "usage" in (r.stderr + r.stdout)


def test_verify_doc_mode_validates():
    r = subprocess.run(
        ["bash", str(REPO / "scripts/verify.sh"), "doc",
         "docs/plans/ergo_batches_adopted.vsm"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_sshq_syntax_and_defaults():
    p = REPO / "scripts/sshq.sh"
    r = subprocess.run(["bash", "-n", str(p)], capture_output=True, timeout=15)
    assert r.returncode == 0
    body = p.read_text(encoding="utf-8")
    assert "BatchMode=yes" in body
    assert "ConnectTimeout=" in body
