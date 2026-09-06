"""tests/test_adapters.py — Tests for state-canon adapters."""

import tempfile
from pathlib import Path

import pytest
from vos_kernel.adapters import (
    StateCanonInfra,
    InfraConfig,
    StateCanonAgent,
    AgentConfig,
)


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def infra(temp_state_dir):
    """Create a infra adapter instance."""
    config = InfraConfig(canon_path=temp_state_dir)
    return StateCanonInfra(config)


@pytest.fixture
def agent(temp_state_dir):
    """Create an agent adapter instance."""
    config = AgentConfig(
        canon_path=temp_state_dir,
        session_id="test-session",
    )
    return StateCanonAgent(config)


def test_infra_init(infra):
    """StateCanonInfra initializes correctly."""
    assert infra.config is not None
    assert infra._connected is False


def test_infra_connect(infra):
    """StateCanonInfra connects successfully."""
    result = infra.connect()
    assert result.success is True
    assert infra._connected is True


def test_infra_record_status(infra):
    """StateCanonInfra records status."""
    infra.connect()
    result = infra.record_status("test_component.py", {"status": "ok"})
    assert result.success is True


def test_infra_health_check(infra):
    """StateCanonInfra performs health check."""
    infra.connect()
    health = infra.health_check()
    assert health["healthy"] is True


def test_infra_reconcile(infra):
    """StateCanonInfra reconciles state."""
    infra.connect()
    result = infra.reconcile()
    assert result.success is True


def test_agent_init(agent):
    """StateCanonAgent initializes correctly."""
    assert agent.config.session_id == "test-session"
    assert agent._connected is False


def test_agent_connect(agent):
    """StateCanonAgent connects successfully."""
    result = agent.connect()
    assert result.success is True
    assert agent._connected is True


def test_agent_focus_mark(agent):
    """StateCanonAgent marks focus entries."""
    agent.connect()
    result = agent.focus_mark("TASK-001", status="active", note="Working on X")
    assert result.success is True


def test_agent_focus_close(agent):
    """StateCanonAgent closes focus entries."""
    agent.connect()
    agent.focus_mark("TASK-001", status="active")
    result = agent.focus_close("TASK-001", note="Done")
    assert result.success is True


def test_agent_journal_mark(agent):
    """StateCanonAgent marks journal snapshots."""
    agent.connect()
    result = agent.journal_mark(session_id="test-session")
    assert result.success is True


def test_agent_detect_drift(agent):
    """StateCanonAgent detects drift."""
    agent.connect()
    drifts = agent.detect_drift()
    assert isinstance(drifts, list)


def test_agent_get_session_context(agent):
    """StateCanonAgent returns session context."""
    context = agent.get_session_context()
    assert context["session_id"] == "test-session"
    assert context["connected"] is False
