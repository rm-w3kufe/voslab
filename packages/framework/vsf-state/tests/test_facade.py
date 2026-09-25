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
