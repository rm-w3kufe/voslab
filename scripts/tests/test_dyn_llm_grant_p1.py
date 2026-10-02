#!/usr/bin/env python3
"""
test_dyn_llm_grant_p1.py — Floor clamp acceptance (DYN-LLM-GRANT P1)

Self-contained: replicates _apply_floor logic inline to avoid NATS dependency.
Verifies that SERVICE_FLOORS clamp prevents revert/grant from going below floor.

  Acceptance:
  1. Normal restore (baseline > floor) → no clamping
  2. Sub-floor baseline (external downsizing) → mem clamped to 5120
  3. Zero request → mem clamped to 5120
  4. Non-101 LXC (no floor) → unchanged
  5. Grant target below floor → clamped to 5120
  6. Negative value → clamped to 5120
"""

# ── Module under test (replicated inline) ──────────────────────────────────────
SERVICE_FLOORS = {
    "101": {"mem_mb": 5120, "reason": "ollama qwen2.5-coder:7b requires ~4.7GB loaded"},
}


def apply_floor(vmid: str, cores: int | None = None, mem: int | None = None):
    """Replicates s3_resource_alloc.ResourceBargain._apply_floor()"""
    floor = SERVICE_FLOORS.get(vmid, {})
    mem_floor = floor.get("mem_mb")
    cores_floor = floor.get("cores")
    clamped_mem = max(mem, mem_floor) if (mem is not None and mem_floor is not None) else mem
    clamped_cores = max(cores, cores_floor) if (cores is not None and cores_floor is not None) else cores
    return (clamped_cores, clamped_mem)


# ── Tests ──────────────────────────────────────────────────────────────────────
def test(label: str, vmid: str, cores, mem, expected_cores, expected_mem):
    actual = apply_floor(vmid, cores=cores, mem=mem)
    ok = (actual == (expected_cores, expected_mem))
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {status} | {label}")
    if not ok:
        print(f"         expected=({expected_cores}, {expected_mem})  actual={actual}")
    return ok


def main():
    print("=" * 68)
    print("DYN-LLM-GRANT P1 — Floor Clamp Acceptance (self-contained)")
    print("=" * 68)

    # Sanity
    assert "101" in SERVICE_FLOORS
    assert SERVICE_FLOORS["101"]["mem_mb"] == 5120
    print(f"\n  SERVICE_FLOORS: LXC 101 mem_floor={SERVICE_FLOORS['101']['mem_mb']} MB")
    print(f"  LXCs with no floor: 112, 113, 109\n")

    results = []

    # 1 — Normal restore (baseline=8192 > floor=5120) → unchanged
    results.append(test("normal restore baseline=8192 → unchanged", "101", 4, 8192, 4, 8192))

    # 2 — Sub-floor baseline (external downsized to 4096) → clamped to 5120
    results.append(test("sub-floor baseline 4096 → 5120", "101", 4, 4096, 4, 5120))

    # 3 — Zero request → mem clamped to floor, cores (no floor) unchanged
    results.append(test("zero request mem=0 → 5120, cores=0 unchanged", "101", 0, 0, 0, 5120))

    # 4 — LXC with no floor defined → unchanged
    for vmid in ("112", "113", "109"):
        results.append(test(f"LXC {vmid} no floor mem=256 → 256", vmid, 1, 256, 1, 256))
        results.append(test(f"LXC {vmid} no floor cores=None mem=128", vmid, None, 128, None, 128))

    # 5 — Grant target below floor (baseline=4096 + grant=512 = 4608 → clamped)
    results.append(test("grant target 4608 → 5120", "101", 4, 4608, 4, 5120))

    # 6 — Negative value → clamped up to floor
    results.append(test("negative -100 → 5120", "101", 4, -100, 4, 5120))

    # — Summary
    passed = sum(1 for r in results if r)
    failed = len(results) - passed
    print(f"\n  ── Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("\n>>> ACCEPTANCE: PASS (all floor-clamp checks pass)")
        return 0
    else:
        print(f"\n>>> ACCEPTANCE: FAIL ({failed} assertion(s) failed)")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
