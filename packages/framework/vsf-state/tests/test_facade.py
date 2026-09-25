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


def test_validate_task_state_schema():
    from vsf_state import validate_task_state, VALID_TASK_STATUSES
    assert validate_task_state({"id": "A", "status": "open"}) == {
        "valid": True, "errors": []}
    assert validate_task_state(
        {"id": "A", "status": "done"})["valid"] is True
    bad = validate_task_state({"id": "", "status": "whatever"})
    assert bad["valid"] is False and len(bad["errors"]) == 2
    assert validate_task_state("nope") == {
        "valid": False, "errors": ["not-a-dict"]}
    assert "s3-star" not in VALID_TASK_STATUSES  # roles != statuses
    assert {"done", "open", "blocked"} <= set(VALID_TASK_STATUSES)


def test_restart_service_dry_run_default():
    from vsf_state import restart_service
    r = restart_service(101, "vsf-nucleus-operational.service")
    assert r["confirmed"] is False and r["ok"] is False
    assert r["would_run"] == ["systemctl", "restart",
                              "vsf-nucleus-operational.service"]
    assert r["target"] == "lxc101/vsf-nucleus-operational.service"


def test_filter_variety_pure():
    from vsf_state import filter_variety
    assert filter_variety({"a": 5, "b": 0, "c": 1}, min_count=2) == {
        "b": 0, "c": 1}
    assert filter_variety({}) == {}
    assert filter_variety(None) == {}


def test_compute_variety_metrics_graceful(monkeypatch):
    import vsf_state.cyberfilter_variety as cv
    from vsf_state import compute_variety_metrics
    monkeypatch.setattr(cv, "_count_events",
                        lambda date: {"x": 3})
    assert compute_variety_metrics("2026-01-01") == {"x": 3}

    def boom(date):
        raise RuntimeError("no infra")
    monkeypatch.setattr(cv, "_count_events", boom)
    assert compute_variety_metrics("2026-01-01") == {}


def test_get_certificate_info_empty_dir(tmp_path):
    from vsf_state import get_certificate_info
    r = get_certificate_info(str(tmp_path))
    assert r["trusted"] is False  # no CA root: honest negative


def test_restore_handoff_roundtrip(tmp_path):
    from vsf_state import archive_handoffs, restore_handoff
    live = tmp_path / "HANDOFF.vsm.md"
    live.write_text(
        "⟦ h | T-v1 | vsm-1.2.1 | 2026-01-01T00:00:01Z ⟧\n\n"
        'session("2026-01-a")\n\nold stuff\n\n'
        'session("2026-08-b")\n\nnew stuff\n\n'
        "⟦ /h ⟧\n")
    arch = tmp_path / "arch"
    archive_handoffs(live, arch, keep=1, apply=True)
    r = restore_handoff(arch, "2026-01")
    assert r["restored"] is True and r["blocks"] >= 1
    assert any("old stuff" in b for b in [open(
        arch / f, encoding="utf-8").read() for f in r["files"]])
    out = tmp_path / "restored.md"
    r2 = restore_handoff(arch, "2026-01", target_path=out)
    assert r2["wrote"] == str(out) and "old stuff" in out.read_text()
    assert restore_handoff(arch, "1999-99")["restored"] is False


def test_subscribe_beacon_no_broker_fast(monkeypatch):
    import vsf_state as V
    import asyncio as _aio

    async def boom(*a, **k):
        raise ConnectionError("no broker")

    monkeypatch.setattr(V, "_subscribe_collect", boom)
    r = V.subscribe_beacon("vsf.test", timeout=1.0)
    assert r == {"reached": False, "messages": [],
                 "error": "ConnectionError: no broker"}


def test_monitor_reconcile_graceful_without_infra(monkeypatch):
    import sys
    from vsf_state import monitor_services, reconcile_state
    monkeypatch.setitem(sys.modules, "vsf_state.monitor_reconcile", None)
    assert monitor_services()["status"] == "unavailable"
    assert reconcile_state()["status"] == "unavailable"
