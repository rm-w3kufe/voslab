"""tests/test_regulation.py — Tests for regulation layer."""

import pytest
from vos_kernel.regulation import RegulationLayer, Invariant, InvariantStatus


def test_regulation_init_defaults():
    """G-31: RegulationLayer() registers the boot-doc default invariant."""
    layer = RegulationLayer()
    names = [i.name for i in layer._invariants]
    assert names == ["caution_mode_expiry"]
    assert layer._invariants[0].auto_halt is False


def test_regulation_init_no_defaults():
    """register_defaults=False gives the bare framework (tests)."""
    layer = RegulationLayer(register_defaults=False)
    assert len(layer._invariants) == 0


def test_caution_expiry_holds(tmp_path):
    """check_caution_expiry: inactive or absent state holds (no phantom)."""
    from vos_kernel.regulation import check_caution_expiry
    assert check_caution_expiry(str(tmp_path / "missing.db")) is True
    import sqlite3
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE s5_policy(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO s5_policy VALUES('s5.caution_mode', 'false')")
    conn.commit(); conn.close()
    assert check_caution_expiry(str(db)) is True


def test_caution_expiry_phantom_violated(tmp_path):
    """check_caution_expiry: active past expiry (or no expiry) -> False."""
    from vos_kernel.regulation import check_caution_expiry
    import sqlite3
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE s5_policy(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO s5_policy VALUES('s5.caution_mode', 'true')")
    conn.execute("INSERT INTO s5_policy VALUES('s5.caution_expires', '2026-01-01T00:00:00Z')")
    conn.commit(); conn.close()
    assert check_caution_expiry(str(db)) is False
    # active with no expiry -> cannot auto-clear -> False
    db2 = tmp_path / "state2.db"
    conn = sqlite3.connect(db2)
    conn.execute("CREATE TABLE s5_policy(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO s5_policy VALUES('s5.caution_mode', 'true')")
    conn.commit(); conn.close()
    assert check_caution_expiry(str(db2)) is False


def test_regulation_register():
    """Can register invariants."""
def test_regulation_register():
    """Can register invariants."""
    layer = RegulationLayer(register_defaults=False)
    layer.register(Invariant(
        name="test",
        description="test invariant",
        check=lambda: True,
    ))
    assert len(layer._invariants) == 1


def test_regulation_monitor_healthy():
    """Monitor returns HEALTHY for passing invariant."""
def test_regulation_monitor_healthy():
    """Monitor returns HEALTHY for passing invariant."""
    layer = RegulationLayer(register_defaults=False)
    layer.register(Invariant(
        name="healthy",
        description="always healthy",
        check=lambda: True,
    ))
    results = layer.monitor()
    assert len(results) == 1
    assert results[0].status == InvariantStatus.HEALTHY


def test_regulation_monitor_violated():
    """Monitor returns VIOLATED for failing invariant."""
def test_regulation_monitor_violated():
    """Monitor returns VIOLATED for failing invariant."""
    layer = RegulationLayer(register_defaults=False)
    layer.register(Invariant(
        name="violated",
        description="always violated",
        check=lambda: False,
    ))
    results = layer.monitor()
    assert len(results) == 1
    assert results[0].status == InvariantStatus.VIOLATED


def test_regulation_monitor_exception():
    """Monitor returns UNKNOWN for exception in check."""
def test_regulation_monitor_exception():
    """Monitor returns UNKNOWN for exception in check."""
    layer = RegulationLayer(register_defaults=False)
    layer.register(Invariant(
        name="error",
        description="raises exception",
        check=lambda: 1/0,
    ))
    results = layer.monitor()
    assert len(results) == 1
    assert results[0].status == InvariantStatus.UNKNOWN


def test_regulation_violations():
    """get_violations returns only violated invariants."""
def test_regulation_violations():
    """get_violations returns only violated invariants."""
    layer = RegulationLayer(register_defaults=False)
    layer.register(Invariant(name="ok", description="ok", check=lambda: True))
    layer.register(Invariant(name="bad", description="bad", check=lambda: False))
    layer.monitor()
    violations = layer.get_violations()
    assert len(violations) == 1
    assert violations[0].name == "bad"


def test_regulation_halt():
    """should_halt returns True when auto_halt invariant is violated."""
def test_regulation_halt():
    """should_halt returns True when auto_halt invariant is violated."""
    layer = RegulationLayer(register_defaults=False)
    layer.register(Invariant(
        name="halt_test",
        description="should halt",
        check=lambda: False,
        auto_halt=True,
    ))
    layer.monitor()
    assert layer.should_halt() is True
