"""tests/test_backbone.py — Tests for integration backbone."""

import json
import tempfile
from pathlib import Path

import pytest
from vos_kernel.backbone import (
    Backbone,
    BackboneEvent,
    BackboneEventLogger,
    ComponentType,
    EventStatus,
    Step,
)


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def backbone(temp_state_dir):
    """Create a backbone instance."""
    return Backbone(temp_state_dir)


def test_backbone_init(backbone):
    """Backbone initializes correctly."""
    assert backbone.state_dir.exists()
    assert backbone.logger is not None


def test_event_logger(temp_state_dir):
    """EventLogger creates files and logs events."""
    logger = BackboneEventLogger(temp_state_dir)

    event = BackboneEvent(
        step=Step.ROUTE,
        component="/tmp/test.py",
        component_type=ComponentType.SCRIPT,
        status=EventStatus.OK,
        evidence={"routed": True},
    )
    logger.log(event)

    # Check events file
    events_file = temp_state_dir / "backbone_events.jsonl"
    assert events_file.exists()
    with open(events_file) as f:
        lines = f.readlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["step"] == "route"
    assert logged["status"] == "ok"

    # Check status file
    status_file = temp_state_dir / "backbone_status.json"
    assert status_file.exists()
    with open(status_file) as f:
        status = json.load(f)
    assert "/tmp/test.py" in status
    assert status["/tmp/test.py"]["current_step"] == "route"


def test_backbone_ingest_script(backbone, temp_state_dir):
    """Backbone ingests a script file through full lifecycle."""
    # Create a test script
    script = temp_state_dir / "test_script.py"
    script.write_text("#!/usr/bin/env python3\nprint('hello')\n")

    result = backbone.ingest(script, ComponentType.SCRIPT)
    assert result.success is True

    # Check events were logged
    events = backbone.get_events()
    assert len(events) == 7  # 7 steps in lifecycle


def test_backbone_ingest_syntax_error(backbone, temp_state_dir):
    """Backbone fails on syntax error during verify."""
    # Create a script with syntax error
    script = temp_state_dir / "bad_script.py"
    script.write_text("def broken(\n")

    result = backbone.ingest(script, ComponentType.SCRIPT)
    assert result.success is False
    assert "verify" in result.evidence.get("failed_step", "")


def test_backbone_get_status(backbone, temp_state_dir):
    """Backbone returns status for components."""
    script = temp_state_dir / "test.py"
    script.write_text("# test")
    backbone.ingest(script, ComponentType.SCRIPT)

    status = backbone.get_status(str(script))
    assert status["current_step"] == "monitor"
    assert status["status"] == "ok"


def test_step_enum():
    """Step enum has all lifecycle steps."""
    steps = [s.value for s in Step]
    assert "route" in steps
    assert "register" in steps
    assert "verify" in steps
    assert "load" in steps
    assert "evaluate" in steps
    assert "activate" in steps
    assert "monitor" in steps
