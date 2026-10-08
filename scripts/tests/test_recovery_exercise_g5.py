#!/usr/bin/env python3
"""test_recovery_exercise_g5.py — unit tests for the G5 observe loop.

Covers the 2026-10-08 g5-IO debt fix: PSI-aware deterministic backoff
replacing the fixed sleep(3) (FAIL 12:44Z under PSI full avg10=69 vs
PASS 13:0x with healthy chain). No network, no LXC: pct_exec and time
are faked at module level.

Standalone: python3 scripts/tests/test_recovery_exercise_g5.py → exit 0/1.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "scripts" / "s1-kernel" / "tools" / "recovery_exercise.py"

_failures = 0


def _check(cond: bool, label: str) -> None:
    global _failures
    if cond:
        print(f"  ok    {label}")
    else:
        _failures += 1
        print(f"  FAIL  {label}")


def _load_module():
    spec = importlib.util.spec_from_file_location("recovery_exercise", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeTime:
    """Deterministic clock: sleep advances time instantly (R10)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeExec:
    """Routes pct_exec(ct, cmd) calls by content; returns scripted results."""

    def __init__(self, grep_templates: list[str] | None = None,
                 psi_out: str = "some avg10=5.00 avg60=1.00 avg300=0.10\n",
                 inject_rc: int = 0) -> None:
        self.grep_templates = grep_templates or []
        self.psi_out = psi_out
        self.inject_rc = inject_rc
        self.tag: str | None = None
        self.n_grep = 0
        self.n_psi = 0
        self.n_restore = 0

    def __call__(self, ct: int, cmd: str, timeout: int = 60) -> SimpleNamespace:
        if "phi_down.params" in cmd and "g5-roundtrip" in cmd:
            m = re.search(r"g5-roundtrip-[0-9a-f]+", cmd)
            self.tag = m.group(0) if m else None
            return SimpleNamespace(returncode=self.inject_rc, stdout="", stderr="")
        if "phi_down.params" in cmd:
            self.n_restore += 1
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "/proc/pressure" in cmd:
            self.n_psi += 1
            return SimpleNamespace(returncode=0, stdout=self.psi_out, stderr="")
        if "grep -h" in cmd:
            i = min(self.n_grep, len(self.grep_templates) - 1)
            tpl = self.grep_templates[i] if self.grep_templates else ""
            self.n_grep += 1
            out = tpl.replace("{tag}", self.tag) if (tpl and self.tag) else tpl
            return SimpleNamespace(returncode=0, stdout=out, stderr="")
        raise AssertionError(f"unexpected pct_exec cmd: {cmd[:120]}")


def _event(tag_placeholder: str = "{tag}", status: str = "ok",
           changed: list[str] | None = None, etype: str = "param_change",
           origin: str = "{tag}") -> str:
    return json.dumps({
        "event_type": etype,
        "origin": origin,
        "status": status,
        "metrics": {"changed_keys": changed or []},
    })


def test_mutate_restores_on_third_poll() -> None:
    print("[test] mutate path: event lands on 3rd poll → PASS + restore")
    mod = _load_module()
    ft = FakeTime()
    fx = FakeExec(grep_templates=["", "", _event(changed=["log_level"])])
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: 5.0
    r = mod.gate_g5_hot_reload(verbose=True, dry_run=False)
    _check(r.passed, "passed")
    _check("verbosity restored to info" in r.evidence, "evidence mentions restore")
    _check(fx.n_restore == 1, "restore PUB issued once")
    _check(any("psi_some_avg10=5.0" in n for n in r.notes), "psi in notes")
    _check(ft.sleeps and all(s in (2.0, 4.0) for s in ft.sleeps),
           f"deterministic schedule {ft.sleeps}")


def test_noop_passes() -> None:
    print("[test] noop path: emission proves loop → PASS")
    mod = _load_module()
    ft, fx = FakeTime(), FakeExec(grep_templates=[_event(status="noop")])
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: 1.0
    r = mod.gate_g5_hot_reload(verbose=False, dry_run=False)
    _check(r.passed, "passed")
    _check("noop" in r.evidence, "noop evidence")
    _check(fx.n_restore == 0, "no restore for noop")


def test_timeout_normal_deadline_15s() -> None:
    print("[test] timeout: psi=5 → deadline 15s, backoff engages")
    mod = _load_module()
    ft, fx = FakeTime(), FakeExec(grep_templates=[""])  # never lands
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: 5.0
    r = mod.gate_g5_hot_reload(verbose=False, dry_run=False)
    _check(not r.passed, "failed")
    _check("after 15s" in r.evidence, f"deadline in evidence: {r.evidence[:90]}")
    _check("psi_some_avg10=5.0" in r.evidence, "psi in failure evidence")
    _check(any(s == 4.0 for s in ft.sleeps), f"backoff sleep4 used {ft.sleeps}")
    _check(sum(ft.sleeps) >= 15.0, f"window respected: {sum(ft.sleeps)}s")


def test_storm_deadline_45s() -> None:
    print("[test] storm: psi=69 → deadline 45s")
    mod = _load_module()
    ft, fx = FakeTime(), FakeExec(grep_templates=[""])
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: 69.23
    r = mod.gate_g5_hot_reload(verbose=False, dry_run=False)
    _check(not r.passed, "failed")
    _check("after 45s" in r.evidence, f"storm deadline: {r.evidence[:90]}")
    _check("psi_some_avg10=69.23" in r.evidence, "psi in evidence")
    _check(sum(ft.sleeps) >= 45.0, f"storm window respected: {sum(ft.sleeps)}s")


def test_psi_unavailable_degrades_to_15s() -> None:
    print("[test] psi unavailable → None → deadline 15s (nunca crashea)")
    mod = _load_module()
    ft, fx = FakeTime(), FakeExec(grep_templates=[""])
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: None
    r = mod.gate_g5_hot_reload(verbose=False, dry_run=False)
    _check(not r.passed, "failed (no event)")
    _check("after 15s" in r.evidence and "psi_some_avg10=None" in r.evidence,
           f"degraded deadline: {r.evidence[:90]}")


def test_inject_failure_early() -> None:
    print("[test] inject rc≠0 → early FAIL, no observe loop")
    mod = _load_module()
    ft, fx = FakeTime(), FakeExec(inject_rc=255)
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: 5.0
    r = mod.gate_g5_hot_reload(verbose=False, dry_run=False)
    _check(not r.passed, "failed")
    _check("NATS publish failed" in r.evidence, "inject failure evidence")
    _check(fx.n_grep == 0 and fx.n_psi == 0, "no observe calls made")


def test_shape_mismatch_fails() -> None:
    print("[test] wrong event shape → FAIL (regresión parse)")
    mod = _load_module()
    ft, fx = FakeTime(), FakeExec(grep_templates=[_event(etype="heartbeat")])
    mod.time, mod.pct_exec = ft, fx
    mod._psi_some_avg10 = lambda: 5.0
    r = mod.gate_g5_hot_reload(verbose=False, dry_run=False)
    _check(not r.passed, "failed")
    _check("shape unexpected" in r.evidence, "shape evidence")


def main() -> int:
    tests = [
        test_mutate_restores_on_third_poll,
        test_noop_passes,
        test_timeout_normal_deadline_15s,
        test_storm_deadline_45s,
        test_psi_unavailable_degrades_to_15s,
        test_inject_failure_early,
        test_shape_mismatch_fails,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001 — harness: any error = failure
            global _failures
            _failures += 1
            print(f"  FAIL  harness error in {t.__name__}: {e!r}")
    print(f"\n{_failures} failure(s) across {len(tests)} tests")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
