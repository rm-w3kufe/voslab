"""Integration test: vsf-common is pinned into vOSLAB and usable.

This proves the hybrid packaging pattern works end-to-end: the durable package
(~/packages/public/vsf-common) is pinned into vOSLAB (packages/public/vsf-common)
and its negative-control contract holds through the pin.
"""

from vsf_common import CouplingSpec, validate, positive_case, negative_case


def test_pinned_common_importable():
    assert CouplingSpec is not None


def test_pinned_common_contract_holds():
    assert validate(positive_case()) == 0
    assert validate(negative_case()) != 0
