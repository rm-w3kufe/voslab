"""tests/test_vsf_common.py — Tests for vsf-common protocol."""

import pytest
from vsf_common import (
    ComponentType,
    ComponentStatus,
    Event,
    StatusCode,
    PackageMetadata,
    validate_event,
    validate_metadata,
)


def test_component_type_enum():
    """ComponentType enum has all required types."""
    assert ComponentType.TREE.value == "tree"
    assert ComponentType.PREDICATE.value == "predicate"
    assert ComponentType.SCRIPT.value == "script"
    assert ComponentType.PLUGIN.value == "plugin"
    assert ComponentType.ADAPTER.value == "adapter"
    assert ComponentType.PROTOCOL.value == "protocol"


def test_component_status_enum():
    """ComponentStatus enum has all required statuses."""
    assert ComponentStatus.ACTIVE.value == "active"
    assert ComponentStatus.INACTIVE.value == "inactive"
    assert ComponentStatus.ERROR.value == "error"
    assert ComponentStatus.PENDING.value == "pending"
    assert ComponentStatus.DEPRECATED.value == "deprecated"


def test_event_creation():
    """Event can be created with required fields."""
    event = Event(
        event_type="test",
        component="test.py",
        component_type=ComponentType.SCRIPT,
        status=ComponentStatus.ACTIVE,
    )
    assert event.event_type == "test"
    assert event.component == "test.py"
    assert event.component_type == ComponentType.SCRIPT
    assert event.status == ComponentStatus.ACTIVE


def test_event_to_dict():
    """Event serializes to dict correctly."""
    event = Event(
        event_type="test",
        component="test.py",
        component_type=ComponentType.SCRIPT,
        status=ComponentStatus.ACTIVE,
        data={"key": "value"},
    )
    d = event.to_dict()
    assert d["event_type"] == "test"
    assert d["component"] == "test.py"
    assert d["component_type"] == "script"
    assert d["status"] == "active"
    assert d["data"]["key"] == "value"


def test_event_from_dict():
    """Event deserializes from dict correctly."""
    d = {
        "event_type": "test",
        "component": "test.py",
        "component_type": "script",
        "status": "active",
        "data": {"key": "value"},
    }
    event = Event.from_dict(d)
    assert event.event_type == "test"
    assert event.component == "test.py"
    assert event.component_type == ComponentType.SCRIPT
    assert event.status == ComponentStatus.ACTIVE


def test_validate_event_valid():
    """validate_event accepts valid event."""
    event = {
        "event_type": "test",
        "component": "test.py",
        "component_type": "script",
        "status": "active",
    }
    is_valid, error = validate_event(event)
    assert is_valid is True
    assert error == ""


def test_validate_event_missing_field():
    """validate_event rejects event with missing field."""
    event = {
        "event_type": "test",
        "component": "test.py",
        # Missing component_type and status
    }
    is_valid, error = validate_event(event)
    assert is_valid is False
    assert "Missing" in error


def test_validate_event_invalid_type():
    """validate_event rejects event with invalid component_type."""
    event = {
        "event_type": "test",
        "component": "test.py",
        "component_type": "invalid",
        "status": "active",
    }
    is_valid, error = validate_event(event)
    assert is_valid is False
    assert "Invalid" in error


def test_package_metadata():
    """PackageMetadata can be created and serialized."""
    metadata = PackageMetadata(
        name="test-package",
        version="1.0.0",
        component_type=ComponentType.SCRIPT,
        description="A test package",
    )
    d = metadata.to_dict()
    assert d["name"] == "test-package"
    assert d["version"] == "1.0.0"
    assert d["component_type"] == "script"


def test_validate_metadata_valid():
    """validate_metadata accepts valid metadata."""
    metadata = {
        "name": "test-package",
        "version": "1.0.0",
        "component_type": "script",
    }
    is_valid, error = validate_metadata(metadata)
    assert is_valid is True
    assert error == ""


def test_validate_metadata_missing_field():
    """validate_metadata rejects metadata with missing field."""
    metadata = {
        "name": "test-package",
        # Missing version and component_type
    }
    is_valid, error = validate_metadata(metadata)
    assert is_valid is False
    assert "Missing" in error


def test_status_code_enum():
    """StatusCode enum has all required codes."""
    assert StatusCode.OK.value == 0
    assert StatusCode.ERROR.value == 1
    assert StatusCode.TIMEOUT.value == 2
    assert StatusCode.NOT_FOUND.value == 3
