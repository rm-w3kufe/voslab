"""Integration: the installable vos-chassis wires vOSLAB's endpoint registry."""

import os

import pytest

from vos_chassis import Chassis
from vsf_common import CouplingSpec

ROOT = os.path.dirname(os.path.dirname(__file__))  # vOSLAB root


def test_chassis_wires_voslab_endpoints():
    ch = Chassis(ROOT)
    res = ch.wire(
        couplings=[
            CouplingSpec(
                name="state-canon-bridge",
                provider="state-canon-mcp",
                consumer="state-canon-infra",
                interface="state.canon.mcp",
                version="0.1.0",
            )
        ]
    )
    assert len(res.endpoints) == 2
    assert len(res.couplings) == 1


def test_chassis_rejects_bad_coupling():
    ch = Chassis(ROOT)
    with pytest.raises(ValueError):
        ch.wire(
            couplings=[
                CouplingSpec(
                    name="bad", provider="x", consumer="y",
                    interface="", version="1.0.0"
                )
            ]
        )
