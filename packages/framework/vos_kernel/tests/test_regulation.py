"""tests/test_regulation.py — Tests for regulation layer."""

import pytest
from vos_kernel.regulation import RegulationLayer, Invariant, InvariantStatus


def test_regulation_init():
    """RegulationLayer initializes without error."""
    layer = RegulationLayer()
    assert len(layer._invariants) == 0


def test_regulation_register():
    """Can register invariants."""
    layer = RegulationLayer()
    layer.register(Invariant(
        name="test",
        description="test invariant",
        check=lambda: True,
    ))
    assert len(layer._invariants) == 1


def test_regulation_monitor_healthy():
    """Monitor returns HEALTHY for passing invariant."""
    layer = RegulationLayer()
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
    layer = RegulationLayer()
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
    layer = RegulationLayer()
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
    layer = RegulationLayer()
    layer.register(Invariant(name="ok", description="ok", check=lambda: True))
    layer.register(Invariant(name="bad", description="bad", check=lambda: False))
    layer.monitor()
    violations = layer.get_violations()
    assert len(violations) == 1
    assert violations[0].name == "bad"


def test_regulation_halt():
    """should_halt returns True when auto_halt invariant is violated."""
    layer = RegulationLayer()
    layer.register(Invariant(
        name="halt_test",
        description="should halt",
        check=lambda: False,
        auto_halt=True,
    ))
    layer.monitor()
    assert layer.should_halt() is True
