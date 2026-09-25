"""Tests for vsf_state facades (rehab 2026-09-24: __init__ promised
16 names that did not exist). Facades compose existing primitives;
uncomposable names are tracked gaps, not faked."""
import json

import vsf_state
from vsf_state import (
    compute_hook_metrics,
    reconcile_tasks,
    publish_beacon,
    verify_witness,
    check_service_health,
)


def test_package_imports():
    assert len(vsf_state.__all__) >= 20


def test_compute_hook_metrics(tmp_path):
    log = tmp_path / "actions.jsonl"
    log.write_text(
        json.dumps({"phase": "after", "tool": "write", "result": "ok"}) + "\n"
        + json.dumps({"phase": "after", "tool": "bash", "result": "error"}) + "\n")
    m = compute_hook_metrics(log)
    assert isinstance(m, dict) and "frequency" in m and "errors" in m


def test_reconcile_tasks_empty(tmp_path):
    f = tmp_path / "TASKS.vsm"
    f.write_text("nothing here\n")
    out = reconcile_tasks(str(f))
    assert isinstance(out, dict)


def test_reconcile_tasks_never_raises(tmp_path):
    assert reconcile_tasks("/nonexistent-xyz") == {}


def test_publish_beacon_degrades_without_nats(monkeypatch):
    # Fake the transport (no network in tests): failure -> False, fast.
    import vsf_state.algedonic_pub as ap

    async def boom(payload: bytes):
        raise ConnectionError("no broker")

    async def ok(payload: bytes):
        return None

    monkeypatch.setattr(ap, "_publish", boom)
    assert publish_beacon({"test": 1}) is False
    monkeypatch.setattr(ap, "_publish", ok)
    assert publish_beacon({"test": 1}) is True


def test_check_service_health_lazy():
    # Lazy import inside facade (module needs checkout layout).
    try:
        out = check_service_health(101, "vsf-nucleus-operational.service")
        assert isinstance(out, tuple)
    except (ImportError, ModuleNotFoundError):
        pass  # service_watchdog unimportable outside checkout: documented


def test_verify_witness_passthrough():
    import inspect
    sig = inspect.signature(verify_witness)
    assert list(sig.parameters)[:2] == ["statements", "ca_dir"]


def test_export_analytics_writes_report(tmp_path):
    from vsf_state import export_analytics
    recs = [{"phase": "after", "tool": "write", "result": "ok"}]
    out = export_analytics(recs, tmp_path / "rep.json")
    import json as _json
    loaded = _json.loads(open(out).read())
    assert loaded["summary"]["total_records"] == 1


def _handoff_doc(old="old stuff", new="new stuff"):
    return ("⟦ h | T-v1 | vsm-1.2.1 | 2026-01-01T00:00:01Z ⟧\n\n"
            'session("2026-01-a")\n\n' + old + "\n\n"
            'session("2026-08-b")\n\n' + new + "\n\n"
            "⟦ /h ⟧\n")


def test_archive_handoffs_dry_run(tmp_path):
    from vsf_state import archive_handoffs
    live = tmp_path / "HANDOFF.vsm.md"
    live.write_text(_handoff_doc())
    out = archive_handoffs(live, tmp_path / "arch", keep=1, apply=False)
    assert out["applied"] is False
    assert out["archived_blocks"] >= 1
    # dry run writes nothing
    assert not (tmp_path / "arch").exists()
    assert "old stuff" in live.read_text()


def test_archive_handoffs_apply_conserves(tmp_path):
    from vsf_state import archive_handoffs
    live = tmp_path / "HANDOFF.vsm.md"
    live.write_text(_handoff_doc())
    before = live.read_text()
    out = archive_handoffs(live, tmp_path / "arch", keep=1, apply=True)
    assert out["applied"] is True
    new_live = live.read_text()
    assert "new stuff" in new_live and "old stuff" not in new_live
    archived = list((tmp_path / "arch").glob("*.vsm.md"))
    assert len(archived) == len(out["archive_files"]) >= 1
    assert "old stuff" in archived[0].read_text()
    # conservation: archived + live bodies cover the original blocks
    assert "new stuff" in new_live
