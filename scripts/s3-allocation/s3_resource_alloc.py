#!/usr/bin/env python3
"""
s3_resource_alloc.py — S3 proportional resource bargain (Beer).

S3 monitors S1 viability (stasis_cos via NATS φ↑) and ALLOCATES resources
(CPU cores + RAM) by calling the Proxmox API when stress is sustained.

Policy (proportional):
  GRANT_SIZE = f(stress_depth): deeper stress → larger grant
    depth = (STRESS_THRESHOLD - stasis_cos) / STRESS_THRESHOLD, clamped [0, 1]
    grant_cores = max(GRANT_MIN_CORES, round(depth * GRANT_MAX_CORES))
    grant_mem    = max(GRANT_MIN_MEM,   round(depth * GRANT_MAX_MEM))

  SAFETY_MARGIN = 20% of pool always reserved (S3 management resource; Beer).

  Three pool zones:
    GREEN  < 60%  → normal grants
    YELLOW 60-80% → grants only when stress_depth >= SEVERE_DEPTH (0.30)
    RED    > 80%  → no grants, emit algedonic warning

  RESTORE: stasis_cos >= RECOVERY_THRESHOLD for >= RECOVERY_TICKS ticks
           → return to baseline. Restore is not zone-gated.
  A5 gate: no LXC start/stop/create/destroy (double-loop; requires human approval).
"""
import asyncio
import json
import ssl
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import nats
import os

# ── Proxmox API ──────────────────────────────────────────────────────────────
PROXMOX_URL   = os.environ.get("PROXMOX_URL",   "https://10.10.20.1:8006/api2/json")
PROXMOX_NODE  = os.environ.get("PROXMOX_NODE",  "n02")
PROXMOX_TOKEN = os.environ.get("PROXMOX_TOKEN", "")  # set in /etc/default/vsf-s3-alloc

# ── NATS ─────────────────────────────────────────────────────────────────────
NATS_URL          = "nats://10.10.20.20:4222"
GRANT_SUBJECT     = "vsf.alpha.s3.resource_grant"
AUDIT_SUBJECT     = "vsf.alpha.s3star.audit"   # AXIS 2 C2: S3* audit chain

# ── AXIS 2 C1: margin_free early-warning ──────────────────────────────────────
MARGIN_EARLY_WARNING = 0.05   # margin_free below this → anticipatory grant BEFORE stasis drops
MARGIN_STRESS_DEPTH_FACTOR = 2.0  # how aggressive: (MARGIN_EARLY_WARNING - margin_free) * factor -> depth

# ── AXIS 2 SECOND-LOOP: lyapunov drift-correction attenuator ─────────────────
# Policy defaults per axis2_second_loop.spec.vsm (RATIFIED):
DIVERGE_TICKS    = 5      # consecutive diverging ticks before acting
ATTEN_STEP       = 0.20   # reduce admit rate 20% per attenuation step
MIN_ADMIT        = 0.40   # covenant floor — never below 40% nominal admit
RECOVER_TICKS    = 10     # non-diverging ticks in-recurrent-set before reverting
ESCALATE_TICKS   = 20     # still diverging at max attenuation → escalate

# ── AXIS 2 SECOND-LOOP PHASE-2: S2 aggregation attenuator ────────────────────
# Phase-2 widens the debounce window (aggregation, not dropping) under sustained
# divergence. The v1 admit_rate is KEPT as the amplifier-brake (complementary).
# Policy defaults per axis2_second_loop.spec.vsm (RATIFIED 2026-07-04):
DEBOUNCE_BASELINE = 3      # normal debounce ticks (ITEM_18 default)
MAX_DEBOUNCE      = 15     # ceiling — never aggregate more than this
AGGREGATE_STEP    = 2      # widen debounce by this many ticks per attenuate step

# ── AXIS 2 C3: ESCALATE_THRESHOLD ─────────────────────────────────────────────
ESCALATE_MEM_MB      = 512    # single grant > this -> escalate (hold, don't act)
ESCALATE_CORES       = 1      # single grant > this -> escalate
ESCALATE_CUMULATIVE_MEM = 1024  # cumulative per target > this -> escalate
ESCALATE_THRESHOLD_DEPTH = 0.50 # stress depth > this combined with any yellow/red -> escalate

# ── Policy thresholds ─────────────────────────────────────────────────────────
STRESS_THRESHOLD    = 0.55   # stasis_cos below this = stressed (aligns with kernel "adjusting" boundary)
RECOVERY_THRESHOLD  = 0.70   # stasis_cos above this = recovered
STRESS_TICKS        = 3      # consecutive stressed ticks before grant
RECOVERY_TICKS      = 5      # consecutive recovered ticks before restore
SEVERE_DEPTH        = 0.30   # min depth for YELLOW-zone grants

# ── Proportional grant sizes (function of stress_depth) ──────────────────────
# grant_cores = max(GRANT_MIN_CORES, min(GRANT_MAX_CORES, round(depth * GRANT_MAX_CORES)))
# grant_mem   = max(GRANT_MIN_MEM,   min(GRANT_MAX_MEM,   round(depth * GRANT_MAX_MEM)))
GRANT_MIN_CORES = 1       # minimum extra cores per grant
GRANT_MAX_CORES = 2       # maximum extra cores per grant (at depth=1.0)
GRANT_MIN_MEM   = 128     # minimum extra RAM per grant (MB)
GRANT_MAX_MEM   = 512     # maximum extra RAM per grant (MB; at depth=1.0)
MAX_EXTRA_CORES = 3       # max above baseline per LXC (allow cumulatives from multiple grants)
MAX_EXTRA_MEM   = 1024    # max above baseline per LXC (MB)

# ── Resource pool — Beer: S3 keeps "management resource" always ──────────────
SAFETY_MARGIN   = 0.20    # fraction of pool permanently reserved (S3 mgmt reserve)
POOL_CORES      = 3       # total extra cores S3 can allocate across all LXCs
POOL_MEM_MB     = 1536    # total extra RAM S3 can allocate across all LXCs

# ── Pool zone thresholds (fraction of effective pool after safety margin) ────
ZONE_GREEN_MAX  = 0.60    # < 60%  → normal
ZONE_YELLOW_MAX = 0.80    # < 80%  → cautious; >= 80% → red

# ── TIER 2 — defensive OOM guard (all LXCs) ──────────────────────────────────
# Separate guard-pool for defensive bumps only. Does NOT participate in the
# proportional bargain (which stays S1-semantic). Ratified 2026-07-03.
GUARD_POOL_MB     = 1024   # total guard pool for all LXCs (MB)
GUARD_HI_PCT      = 0.90   # memory usage above this = pressured
GUARD_LO_PCT      = 0.60   # memory usage below this = clear
GUARD_HI_TICKS    = 3      # consecutive pressured ticks before grant
GUARD_LO_TICKS    = 5      # consecutive clear ticks before revert
GUARD_BUMP_MB     = 256    # MB to grant when pressured (fixed, not proportional)
GUARD_CAP_MB      = 512    # max total extra MB per LXC from guard
GUARD_TICK_S      = 60     # seconds between guard ticks

# ── LXC registry: vmid → {role, baseline_cores, baseline_mem_mb} ──────────────
LXC_REGISTRY = {
    "112": {"role": "s1-clima",    "baseline_cores": 2, "baseline_mem": 2048},
    "113": {"role": "s1-econ",     "baseline_cores": 2, "baseline_mem": 2048},
    "101": {"role": "s3s4-nucleus","baseline_cores": 4, "baseline_mem": 3072},
    "109": {"role": "s5-opsroom",  "baseline_cores": 2, "baseline_mem": 384},
    "106": {"role": "s2-broker",   "baseline_cores": 1, "baseline_mem": 128},
    "107": {"role": "s3star-audit","baseline_cores": 4, "baseline_mem": 128},
}

# DYN-LLM-GRANT P1: service floors — grant-revert/shrink paths never go below.
# state.db-backed in P3; constant dict for P1.
SERVICE_FLOORS = {
    "110": {"mem_mb": 5120, "reason": "ollama on s4-intelligence — qwen2.5-coder:7b requires ~4.7GB loaded"},  # W3-DYN-GRANT-RETARGET: ollama migrated 101→110 2026-06-26
}

# ── Domain → VMID mapping (from stasis_cos signal source) ────────────────────
DOMAIN_TO_VMID = {
    "s1-clima": "112",    # vsf.clima.*.phi_up stasis signals
    "vsf_nucleus": "101", # vsf.alpha.vsf_nucleus.up.kernel_tick
}

LOG_PATH = Path("/var/log/vsf/s3_resource_alloc.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proxmox_set(vmid: str, cores: int | None = None, memory: int | None = None) -> bool:
    """Call Proxmox API to adjust LXC cgroup resources. Returns True on success."""
    url = f"{PROXMOX_URL}/nodes/{PROXMOX_NODE}/lxc/{vmid}/config"
    params = {}
    if cores is not None:
        params["cores"] = str(cores)
    if memory is not None:
        params["memory"] = str(memory)
    if not params:
        return True

    data = urllib.parse.urlencode(params).encode()
    ctx  = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"PVEAPIToken={PROXMOX_TOKEN}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            body = json.loads(resp.read())
            # Proxmox PUT returns {"data": null} on success
            if resp.status not in (200, 201):
                print(f"  [alloc] proxmox set vmid={vmid} unexpected status={resp.status}: {body}", flush=True)
                return False
            print(f"  [alloc] pct set {vmid} cores={cores} mem={memory} → OK (status={resp.status})", flush=True)
            return True
    except Exception as e:
        print(f"  [alloc] proxmox API error vmid={vmid}: {e}", flush=True)
        return False


def _log(event: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")


# ── AXIS 2 C2/C3: escalation check + S3* audit ───────────────────────────────

_ESCALATION_EVENT_CACHE: set[str] = set()  # dedup: only emit escalate once per cluster

def _check_escalation(vmid: str, grant_cores: int, grant_mem_mb: int,
                      cumulative_cores: int, cumulative_mem: int,
                      depth: float, pool_zone: str, stasis_cos: float) -> str | None:
    """Return escalation reason string if this grant should ESCALATE (HOLD), else None.

    AXIS 2 C3 per RATIFIED policy:
      - pool > 80% (RED) + stressed                → escalate (was algedonic-only, now HOLD)
      - single grant > ESCALATE_MEM_MB/ESCALATE_CORES → escalate
      - cumulative per target > ESCALATE_CUMULATIVE_MEM → escalate
      - depth > ESCALATE_THRESHOLD_DEPTH + yellow zone → escalate
      - novel (grant would push green->red in one shot) → escalate (novel pattern)
    """
    if pool_zone == "red":
        return f"RED zone — pool exhausted, grant HOLD. zone={pool_zone} depth={depth:.3f}"
    if grant_mem_mb > ESCALATE_MEM_MB or grant_cores > ESCALATE_CORES:
        return f"over_E_threshold — grant {grant_cores}c/{grant_mem_mb}MB exceeds ESCALATE_MEM={ESCALATE_MEM_MB}MB or ESCALATE_CORES={ESCALATE_CORES} depth={depth:.3f}"
    if cumulative_mem + grant_mem_mb > ESCALATE_CUMULATIVE_MEM:
        return f"over_cumulative — cumulative {cumulative_mem}+{grant_mem_mb}MB > ESCALATE_CUMULATIVE_MEM={ESCALATE_CUMULATIVE_MEM}MB target={vmid}"
    if depth > ESCALATE_THRESHOLD_DEPTH and pool_zone in ("yellow", "red"):
        return f"deep_stress_escalation — depth={depth:.3f} > {ESCALATE_THRESHOLD_DEPTH} zone={pool_zone}"
    return None


def _build_audit_event(ev: dict, escalation: str | None = None) -> dict:
    """Augment an s3 event with S3* audit fields (AXIS 2 C2)."""
    audit = dict(ev)  # shallow copy
    audit["audit_source"] = "s3_resource_alloc"
    audit["audit_chain"] = "s3star"
    if escalation:
        audit["escalated"] = True
        audit["escalation_reason"] = escalation
        audit["action"] = "HOLD"
    else:
        audit["escalated"] = False
        audit["action"] = "EXECUTE"
    return audit


def _proxmox_get_status(vmid: str) -> dict | None:
    """Query Proxmox API for LXC current status. Returns dict with 'mem', 'maxmem', etc."""
    url = f"{PROXMOX_URL}/nodes/{PROXMOX_NODE}/lxc/{vmid}/status/current"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"PVEAPIToken={PROXMOX_TOKEN}")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            body = json.loads(resp.read())
            return body.get("data")
    except Exception as e:
        print(f"  [alloc] proxmox GET status vmid={vmid} err: {e}", flush=True)
        return None


class GuardMemory:
    """TIER 2 defensive OOM guard — all LXCs, not just S1."""

    def __init__(self):
        self.pressure_count: dict[str, int] = {}
        self.clear_count:    dict[str, int] = {}
        self.extra_mem:      dict[str, int] = {}
        self.guard_used_mb:  int = 0
        # Algedonic sentinel: only emit once per exhaustion cycle
        self._pool_exhausted: bool = False

    def _guard_extra(self, vmid: str) -> int:
        """Total guard bump currently active for this LXC."""
        return self.extra_mem.get(vmid, 0)

    def tick(self, vmid: str, baseline_mem_mb: int) -> list[dict]:
        """One memory-pressure check for one LXC. Returns list of events."""
        events = []
        status = _proxmox_get_status(vmid)
        if status is None:
            return events

        mem_used = status.get("mem")
        mem_max  = status.get("maxmem")
        if not mem_used or not mem_max or mem_max == 0:
            return events

        pct = mem_used / mem_max
        current_total = mem_max  # bytes

        guard_extra = self._guard_extra(vmid)

        if pct >= GUARD_HI_PCT:
            self.pressure_count[vmid] = self.pressure_count.get(vmid, 0) + 1
            self.clear_count[vmid] = 0

            if (self.pressure_count[vmid] >= GUARD_HI_TICKS
                    and guard_extra < GUARD_CAP_MB
                    and self.guard_used_mb + GUARD_BUMP_MB <= GUARD_POOL_MB):
                # Grant guard bump
                new_mem_mb = int(mem_max / 1024 / 1024) + GUARD_BUMP_MB
                ok = _proxmox_set(vmid, memory=new_mem_mb)
                if ok:
                    self.extra_mem[vmid] = guard_extra + GUARD_BUMP_MB
                    self.guard_used_mb += GUARD_BUMP_MB
                    self.pressure_count[vmid] = 0
                    self._pool_exhausted = False
                    ev = {
                        "ts":           _now(),
                        "event_type":   "s3_guard_grant",
                        "vsm_function": "S3",
                        "vmid":         vmid,
                        "guard_bump_mb":      GUARD_BUMP_MB,
                        "guard_extra_mb":      self.extra_mem[vmid],
                        "guard_pool_used_mb":  self.guard_used_mb,
                        "guard_pool_remaining": GUARD_POOL_MB - self.guard_used_mb,
                        "mem_usage_pct": round(pct, 3),
                        "reason":       f"mem={pct:.1%} >= {GUARD_HI_PCT:.0%} for {GUARD_HI_TICKS} ticks",
                    }
                    events.append(ev)
                    _log(ev)
                    print(f"[S3 GUARD] vmid={vmid} mem={pct:.1%} → +{GUARD_BUMP_MB}MB (total_extra={self.extra_mem[vmid]}MB pool={self.guard_used_mb}/{GUARD_POOL_MB}MB)", flush=True)
            elif (self.pressure_count[vmid] >= GUARD_HI_TICKS
                  and self.guard_used_mb + GUARD_BUMP_MB > GUARD_POOL_MB
                  and not self._pool_exhausted):
                # Guard pool exhausted — algedonic (once per cycle)
                self._pool_exhausted = True
                ev = {
                    "ts":           _now(),
                    "event_type":   "s3_guard_pool_exhausted",
                    "vsm_function": "S3",
                    "vmid":         vmid,
                    "guard_pool_used_mb":  self.guard_used_mb,
                    "guard_pool_remaining": 0,
                    "mem_usage_pct": round(pct, 3),
                    "reason":       f"GUARD POOL EXHAUSTED vmid={vmid} mem={pct:.1%} used={self.guard_used_mb}/{GUARD_POOL_MB}MB",
                }
                events.append(ev)
                _log(ev)
                print(f"[S3 ALGEDONIC] guard pool exhausted vmid={vmid} mem={pct:.1%} used={self.guard_used_mb}/{GUARD_POOL_MB}MB", flush=True)
            elif self.pressure_count[vmid] >= GUARD_HI_TICKS and guard_extra >= GUARD_CAP_MB:
                # At per-LXC cap — no further grant
                pass
        else:
            self.pressure_count[vmid] = 0
            if pct <= GUARD_LO_PCT and guard_extra > 0:
                self.clear_count[vmid] = self.clear_count.get(vmid, 0) + 1
                if self.clear_count[vmid] >= GUARD_LO_TICKS:
                    # Revert guard bump
                    new_mem_mb = int(mem_max / 1024 / 1024) - guard_extra
                    ok = _proxmox_set(vmid, memory=new_mem_mb)
                    if ok:
                        self.guard_used_mb -= guard_extra
                        freed = self.extra_mem.pop(vmid, 0)
                        self.clear_count[vmid] = 0
                        self._pool_exhausted = False
                        ev = {
                            "ts":           _now(),
                            "event_type":   "s3_guard_revert",
                            "vsm_function": "S3",
                            "vmid":         vmid,
                            "freed_mb":   freed,
                            "guard_pool_used_mb":  self.guard_used_mb,
                            "guard_pool_remaining": GUARD_POOL_MB - self.guard_used_mb,
                            "mem_usage_pct": round(pct, 3),
                            "reason":       f"mem={pct:.1%} <= {GUARD_LO_PCT:.0%} for {GUARD_LO_TICKS} ticks",
                        }
                        events.append(ev)
                        _log(ev)
                        print(f"[S3 GUARD REVERT] vmid={vmid} mem={pct:.1%} → -{freed}MB (pool={self.guard_used_mb}/{GUARD_POOL_MB}MB)", flush=True)
            else:
                self.clear_count[vmid] = 0
        return events


class ResourceBargain:
    """S3 resource bargain state machine per LXC.

    AXIS 2 C1: margin_free early-warning — monitors margin_free independently
    of stasis_cos to trigger anticipatory grants BEFORE stasis drops.
    """

    def __init__(self):
        # Per-vmid stress/recovery counters
        self.stress_count:    dict[str, int] = {}
        self.recovery_count:  dict[str, int] = {}
        # AXIS 2 C1: margin stress counters (separate from stasis stress)
        self.margin_stress_count: dict[str, int] = {}
        self.margin_recovery_count: dict[str, int] = {}
        # Current extra allocation above baseline
        self.extra_cores:     dict[str, int] = {}
        self.extra_mem:       dict[str, int] = {}
        # AXIS 2 SECOND-LOOP: lyapunov drift-correction state
        self.diverging_count:     dict[str, int] = {}  # consecutive diverging ticks
        self.recovery_lyap_count: dict[str, int] = {}  # consecutive non-diverging ticks
        self.admit_rate:          dict[str, float] = {}  # current admit multiplier [MIN_ADMIT, 1.0]
        self.diverging_started:   dict[str, float] = {}  # timestamp of first diverging tick
        self.escalated:           dict[str, bool] = {}   # True if escalation algedonic was emitted
        # AXIS 2 SECOND-LOOP PHASE-2: aggregation attenuator state
        self.debounce_window:     dict[str, int] = {}  # current debounce ticks per vmid
        self.buffer_events:       dict[str, list] = {}  # events buffered for aggregation per vmid
        # Pool accounting
        self.pool_cores_used: int = 0
        self.pool_mem_used:   int = 0

    def _stress_depth(self, stasis_cos: float) -> float:
        """Normalised distance below threshold, clamped [0, 1]."""
        if stasis_cos >= STRESS_THRESHOLD:
            return 0.0
        return min(1.0, (STRESS_THRESHOLD - stasis_cos) / STRESS_THRESHOLD)

    def _pool_zone(self) -> str:
        """Current pool zone: green / yellow / red.
        Based on effective pool after SAFETY_MARGIN reservation."""
        eff_c = POOL_CORES * (1.0 - SAFETY_MARGIN)
        eff_m = POOL_MEM_MB * (1.0 - SAFETY_MARGIN)
        usage_c = self.pool_cores_used / eff_c if eff_c > 0 else 1.0
        usage_m = self.pool_mem_used / eff_m if eff_m > 0 else 1.0
        usage = max(usage_c, usage_m)
        if usage >= ZONE_YELLOW_MAX:
            return "red"
        if usage >= ZONE_GREEN_MAX:
            return "yellow"
        return "green"

    def _pool_available(self) -> tuple[int, int]:
        return (
            POOL_CORES - self.pool_cores_used,
            POOL_MEM_MB - self.pool_mem_used,
        )

    def _apply_floor(self, vmid: str, cores: int | None = None, mem: int | None = None) -> tuple[int | None, int | None]:
        """Clamp resources to SERVICE_FLOORS. Returns (clamped_cores, clamped_mem)."""
        floor = SERVICE_FLOORS.get(vmid, {})
        mem_floor = floor.get("mem_mb")
        cores_floor = floor.get("cores")
        clamped_mem = max(mem, mem_floor) if (mem is not None and mem_floor is not None) else mem
        clamped_cores = max(cores, cores_floor) if (cores is not None and cores_floor is not None) else cores
        return (clamped_cores, clamped_mem)

    def _proportional_grant(self, depth: float) -> tuple[int, int]:
        """Grant size as f(depth), clamped to pool availability and per-LXC max."""
        if depth <= 0.0:
            return (0, 0)
        grant_c = max(GRANT_MIN_CORES, round(depth * GRANT_MAX_CORES))
        grant_m = max(GRANT_MIN_MEM,   round(depth * GRANT_MAX_MEM))
        return (grant_c, grant_m)

    def _margin_stress_depth(self, margin_free: float) -> float:
        """AXIS 2 C1: Convert margin_free shortfall into equivalent stress depth."""
        if margin_free >= MARGIN_EARLY_WARNING:
            return 0.0
        shortfall = MARGIN_EARLY_WARNING - margin_free
        return min(1.0, shortfall * MARGIN_STRESS_DEPTH_FACTOR)

    def observe_margin(self, vmid: str, margin_free: float) -> list[dict]:
        """AXIS 2 C1: Process one margin_free observation for early-warning.
        
        Triggers an anticipatory grant when margin_free stays below threshold
        for fewer ticks than stasis stress requires (catches it BEFORE stasis drops).
        Returns list of events (same format as observe_sync).
        """
        if vmid not in LXC_REGISTRY:
            return []
        baseline = LXC_REGISTRY[vmid]
        events   = []
        depth    = self._margin_stress_depth(margin_free)
        zone     = self._pool_zone()

        margin_stressed = margin_free < MARGIN_EARLY_WARNING
        margin_ok       = margin_free >= MARGIN_EARLY_WARNING * 2  # well above threshold

        if margin_stressed:
            self.margin_stress_count[vmid] = self.margin_stress_count.get(vmid, 0) + 1
            self.margin_recovery_count[vmid] = 0
        elif margin_ok:
            self.margin_recovery_count[vmid] = self.margin_recovery_count.get(vmid, 0) + 1
            self.margin_stress_count[vmid] = 0

        # Grant decision: margin stressed for only 2 ticks (anticipatory — beats stasis)
        margin_eligible = (
            self.margin_stress_count.get(vmid, 0) >= 2
            and self.extra_cores.get(vmid, 0) < MAX_EXTRA_CORES
        )
        zone_blocks = (zone == "red" or (zone == "yellow" and depth < SEVERE_DEPTH))

        if margin_eligible and not zone_blocks:
            raw_c, raw_m = self._proportional_grant(depth)
            # AXIS 2 SECOND-LOOP: scale margin grant by admit_rate (if attenuating)
            admit = self.admit_rate.get(vmid, 1.0)
            if admit < 1.0:
                raw_c = max(0, int(round(raw_c * admit)))
                raw_m = max(0, int(round(raw_m * admit)))
            avail_c, avail_m = self._pool_available()
            grant_c = min(raw_c, MAX_EXTRA_CORES - self.extra_cores.get(vmid, 0), avail_c)
            grant_m = min(raw_m, MAX_EXTRA_MEM - self.extra_mem.get(vmid, 0), avail_m)

            if grant_c > 0 or grant_m > 0:
                # Check escalation
                cumul_cores = self.extra_cores.get(vmid, 0) + grant_c
                cumul_mem   = self.extra_mem.get(vmid, 0)   + grant_m
                escalate_reason = _check_escalation(
                    vmid=vmid, grant_cores=grant_c, grant_mem_mb=grant_m,
                    cumulative_cores=cumul_cores, cumulative_mem=cumul_mem,
                    depth=depth, pool_zone=zone,
                    stasis_cos=1.0,  # stasis is still healthy, use 1.0
                )
                if escalate_reason:
                    ev = {
                        "ts": _now(), "event_type": "s3_margin_escalated",
                        "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                        "grant_cores": grant_c, "grant_mem_mb": grant_m,
                        "margin_free": round(margin_free, 4),
                        "margin_depth": round(depth, 4), "pool_zone": zone,
                        "reason": f"AXIS2 MARGIN-ESCALATED — {escalate_reason}",
                        "a5_class": "single_loop", "a5_gate": "ESCALATION — HOLD",
                        "pool_cores_remaining": POOL_CORES - self.pool_cores_used,
                        "pool_mem_remaining": POOL_MEM_MB - self.pool_mem_used,
                    }
                    ev = _build_audit_event(ev, escalation=escalate_reason)
                    events.append(ev)
                    _log(ev)
                    print(f"[S3 MARGIN ESCALATE] vmid={vmid} mf={margin_free:.4f} — HOLD", flush=True)
                else:
                    new_cores = baseline["baseline_cores"] + self.extra_cores.get(vmid, 0) + grant_c
                    new_mem   = baseline["baseline_mem"]   + self.extra_mem.get(vmid, 0)   + grant_m
                    new_cores, new_mem = self._apply_floor(vmid, new_cores, new_mem)
                    ok = _proxmox_set(vmid, cores=new_cores, memory=new_mem)
                    if ok:
                        self.extra_cores[vmid] = self.extra_cores.get(vmid, 0) + grant_c
                        self.extra_mem[vmid]   = self.extra_mem.get(vmid, 0)   + grant_m
                        self.pool_cores_used  += grant_c
                        self.pool_mem_used    += grant_m
                        self.margin_stress_count[vmid] = 0

                        ev = {
                            "ts": _now(), "event_type": "s3_margin_anticipatory_grant",
                            "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                            "grant_cores": grant_c, "grant_mem_mb": grant_m,
                            "margin_free": round(margin_free, 4),
                            "margin_depth": round(depth, 4), "pool_zone": zone,
                            "new_cores": new_cores, "new_mem_mb": new_mem,
                            "reason": f"AXIS2 MARGIN early-warning mf={margin_free:.4f} < {MARGIN_EARLY_WARNING} depth={depth:.3f}",
                            "a5_class": "single_loop",
                            "pool_cores_remaining": POOL_CORES - self.pool_cores_used,
                            "pool_mem_remaining": POOL_MEM_MB - self.pool_mem_used,
                        }
                        ev = _build_audit_event(ev)
                        events.append(ev)
                        _log(ev)
                        print(f"[S3 MARGIN GRANT] vmid={vmid} mf={margin_free:.4f} depth={depth:.2f} +{grant_c}c +{grant_m}MB", flush=True)

        # Revert if margin has been healthy for many ticks
        if self.margin_recovery_count.get(vmid, 0) >= RECOVERY_TICKS and margin_ok:
            if self.extra_cores.get(vmid, 0) > 0 or self.extra_mem.get(vmid, 0) > 0:
                new_cores, new_mem = self._apply_floor(vmid, baseline["baseline_cores"], baseline["baseline_mem"])
                ok = _proxmox_set(vmid, cores=new_cores, memory=new_mem)
                if ok:
                    self.pool_cores_used -= self.extra_cores.get(vmid, 0)
                    self.pool_mem_used   -= self.extra_mem.get(vmid, 0)
                    freed_c = self.extra_cores.pop(vmid, 0)
                    freed_m = self.extra_mem.pop(vmid, 0)
                    self.margin_recovery_count[vmid] = 0
                    ev = {
                        "ts": _now(), "event_type": "s3_margin_restore",
                        "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                        "freed_cores": freed_c, "freed_mem_mb": freed_m,
                        "margin_free": round(margin_free, 4),
                        "reason": f"AXIS2 MARGIN restored mf={margin_free:.4f} > {MARGIN_EARLY_WARNING*2} for {RECOVERY_TICKS} ticks",
                        "a5_class": "single_loop",
                    }
                    ev = _build_audit_event(ev)
                    events.append(ev)
                    _log(ev)
                    print(f"[S3 MARGIN RESTORE] vmid={vmid} mf={margin_free:.4f} → baseline", flush=True)

        return events

    # ── AXIS 2 SECOND-LOOP PHASE-2: aggregation (S2 debounce widening) ──────
    def _aggregate_phi_up(self, vmid: str, lyapunov: dict) -> list[dict]:
        """Buffer raw phi_up events within the debounce window, emit summaries.

        Instead of passing every tick individually (which amplifies noise→variety),
        buffer events and release a SUMMARY when the debounce window fills or
        the regime changes. This is lossless of SIGNAL (a real sustained change
        passes through) but collapsess redundant HIGH-FREQUENCY chatter.

        Returns:
            list of aggregated audit events (one per window flush).
        """
        if vmid not in self.buffer_events:
            self.buffer_events[vmid] = []
            self.debounce_window[vmid] = DEBOUNCE_BASELINE

        window = self.debounce_window.get(vmid, DEBOUNCE_BASELINE)

        # Always buffer
        self.buffer_events[vmid].append(lyapunov)

        # Check if we should flush
        regime = lyapunov.get("regime", "unknown")
        buf = self.buffer_events[vmid]
        should_flush = False

        if len(buf) >= window:
            should_flush = True
        elif len(buf) >= 2:
            # Regime change triggers early flush (don't mix regimes in same summary)
            prev_regime = buf[-2].get("regime", "unknown")
            if prev_regime != regime:
                should_flush = True

        if not should_flush:
            return []  # still buffering

        # Build summary from buffer
        mean_ls  = [ev.get("mean_l", 0) for ev in buf if isinstance(ev.get("mean_l"), (int, float))]
        mean_dls = [ev.get("mean_dl", 0) for ev in buf if isinstance(ev.get("mean_dl"), (int, float))]
        regimes  = [ev.get("regime", "?") for ev in buf]

        summary = {
            "ts": _now(),
            "event_type": "s3_phi_up_aggregated",
            "vmid": vmid,
            "buffer_size": len(buf),
            "debounce_window": window,
            "regime": regime,
            "mean_l": round(sum(mean_ls)/len(mean_ls), 4) if mean_ls else 0.0,
            "mean_dl": round(sum(mean_dls)/len(mean_dls), 6) if mean_dls else 0.0,
            "min_l": round(min(mean_ls), 4) if mean_ls else 0.0,
            "max_l": round(max(mean_ls), 4) if mean_ls else 0.0,
            "regime_span": list(dict.fromkeys(regimes)),  # unique regimes, ordered
            "diverging_count": regimes.count("diverging"),
            "recovering_count": sum(1 for r in regimes if r in ("in_recurrent_set", "contracting_to_R")),
            "reason": f"debounce flush: {len(buf)} events in {window}-tick window",
            "a5_class": "single_loop",
        }

        # Clear buffer
        self.buffer_events[vmid] = []

        audit = _build_audit_event(summary)
        _log(audit)
        return [audit]

    # ── AXIS 2 SECOND-LOOP: lyapunov drift-correction ──────────────────────
    # Route: margin_binding == budget → hand off to loop 1 (amplify, already done there).
    #        else → attenuate admit rate (this loop).
    # Cycle: DETECT → ROUTE → DECIDE → ACT → VERIFY → REVERT (+ ESCALATE).
    #
    # PHASE-2: also widen the S2 debounce window (P2.1) while keeping the v1
    # admit_rate amplifier-brake (P2.2). The two compose.
    def observe_divergence(self, vmid: str, lyapunov: dict, margin_binding: str = "") -> list[dict]:
        """Process one lyapunov regime observation for drift-correction.

        Args:
            vmid: LXC identifier.
            lyapunov: dict with regime, mean_dl, mean_l, epsilon, governed.
            margin_binding: binding constraint name (from omega).

        Returns:
            list of audit events (same format as observe_sync).
        """
        if vmid not in LXC_REGISTRY:
            return []
        baseline = LXC_REGISTRY[vmid]
        events   = []

        regime      = lyapunov.get("regime", "unknown")
        mean_dl     = lyapunov.get("mean_dl", 0.0)
        mean_l      = lyapunov.get("mean_l", 0.0)
        diverging   = regime == "diverging"
        recovering  = regime in ("in_recurrent_set", "contracting_to_R")

        # Track consecutive diverging/recovery ticks
        if diverging:
            self.diverging_count[vmid]     = self.diverging_count.get(vmid, 0) + 1
            self.recovery_lyap_count[vmid] = 0
            if self.diverging_count.get(vmid, 0) == 1:
                self.diverging_started[vmid] = time.time()
        elif recovering:
            self.recovery_lyap_count[vmid] = self.recovery_lyap_count.get(vmid, 0) + 1
            # Don't reset diverging_count — it's used for escalation even during
            # recovery pauses if the diverge is intermittent
        else:
            # Unknown regime — conservative: don't reset either counter
            pass

        div_count = self.diverging_count.get(vmid, 0)

        # ── ROUTE: check if budget-bound → hand off to loop 1 ──────────
        is_budget_bound = margin_binding and "budget" in margin_binding.lower()

        # Check if attenuation is at the covenant floor
        admit = self.admit_rate.get(vmid, 1.0)
        attenuated_already = admit < 1.0

        # ── DETECT + ROUTE + ACT ───────────────────────────────────────
        if div_count >= DIVERGE_TICKS and diverging:
            if is_budget_bound:
                # Budget-bound variety problem → hand off to loop 1 (amplify).
                # Loop 1 already handles grant decisions via margin_free.
                # We do nothing here, just log the hand-off once.
                if not attenuated_already:
                    print(
                        f"  [s3_alloc] LOOP2 HANDOFF vmid={vmid} margin_binding={margin_binding} "
                        f"→ loop1 (amplify)", flush=True
                    )
                    ev = {
                        "ts": _now(), "event_type": "s3_loop2_handoff",
                        "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                        "lyapunov_regime": regime, "mean_dl": round(mean_dl, 6),
                        "mean_l": round(mean_l, 6), "margin_binding": margin_binding,
                        "reason": "budget-bound → loop 1 (margin_free handles amplify)",
                        "a5_class": "single_loop",
                    }
                    ev = _build_audit_event(ev)
                    events.append(ev)
                    _log(ev)
            else:
                # NOT budget-bound → this loop: attenuate
                # P2.1: widen S2 debounce window (aggregation, not dropping)
                cur_window = self.debounce_window.get(vmid, DEBOUNCE_BASELINE)
                new_window = min(MAX_DEBOUNCE, cur_window + (div_count - DIVERGE_TICKS + 1) * AGGREGATE_STEP)
                window_widened = new_window > cur_window
                if window_widened:
                    self.debounce_window[vmid] = new_window
                    print(
                        f"  [s3_alloc] LOOP2 DEBOUNCE vmid={vmid} widen={cur_window}→{new_window} "
                        f"div_count={div_count}", flush=True
                    )
                    ev = {
                        "ts": _now(), "event_type": "s3_loop2_debounce_widen",
                        "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                        "debounce_window_prev": cur_window,
                        "debounce_window": new_window,
                        "aggregate_step": AGGREGATE_STEP, "diverging_ticks": div_count,
                        "lyapunov_regime": regime, "mean_dl": round(mean_dl, 6),
                        "mean_l": round(mean_l, 6), "margin_binding": margin_binding,
                        "reason": f"debounce widen {cur_window}→{new_window} diverging {div_count}",
                        "a5_class": "single_loop",
                    }
                    ev = _build_audit_event(ev)
                    events.append(ev)
                    _log(ev)

                # P2.2: keep v1 admit_rate as amplifier-brake (complementary)
                new_admit = max(MIN_ADMIT, admit - ATTEN_STEP)
                if new_admit < admit:
                    self.admit_rate[vmid] = new_admit
                    admit = new_admit
                    print(
                        f"  [s3_alloc] LOOP2 ATTENUATE vmid={vmid} admit={admit:.2f} "
                        f"regime={regime} ml={mean_l:.4f} mdl={mean_dl:.4f} "
                        f"div_count={div_count} debounce={new_window}",
                        flush=True
                    )
                    ev = {
                        "ts": _now(), "event_type": "s3_loop2_attenuate",
                        "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                        "admit_rate": round(admit, 4),
                        "debounce_window": cur_window,  # report widest reached
                        "atten_step": ATTEN_STEP, "diverging_ticks": div_count,
                        "lyapunov_regime": regime, "mean_dl": round(mean_dl, 6),
                        "mean_l": round(mean_l, 6), "margin_binding": margin_binding,
                        "reason": f"variety attenuate admit={admit:.2f} debounce={cur_window} div={div_count}",
                        "a5_class": "single_loop",
                    }
                    ev = _build_audit_event(ev)
                    events.append(ev)
                    _log(ev)

                # ── ESCALATE at max attenuation ─────────────────────────────
                if admit <= MIN_ADMIT and div_count >= ESCALATE_TICKS and not self.escalated.get(vmid, False):
                    self.escalated[vmid] = True
                    elapsed = time.time() - self.diverging_started.get(vmid, time.time())
                    print(
                        f"  [s3_alloc] LOOP2 ESCALATE vmid={vmid} admit={admit:.2f} "
                        f"div_count={div_count} elapsed={elapsed:.0f}s — HOLD + algedonic",
                        flush=True
                    )
                    ev = {
                        "ts": _now(), "event_type": "s3_loop2_escalate",
                        "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                        "admit_rate": round(admit, 4),
                        "lyapunov_regime": regime, "mean_dl": round(mean_dl, 6),
                        "mean_l": round(mean_l, 6), "margin_binding": margin_binding,
                        "action": "HOLD",
                        "reason": f"DIVERGENCE ESCALATED — admit={admit:.2f} div={div_count} "
                                  f"elapsed={elapsed:.0f}s — sustained variety divergence",
                        "a5_class": "single_loop",
                    }
                    ev = _build_audit_event(ev, escalation=ev["reason"])
                    events.append(ev)

        # ── REVERT after sustained recovery (P2.1: also restore debounce) ──
        recov_count = self.recovery_lyap_count.get(vmid, 0)
        if attenuated_already and recov_count >= RECOVER_TICKS and recovering:
            prev_window = self.debounce_window.get(vmid, DEBOUNCE_BASELINE)
            self.admit_rate[vmid] = 1.0
            self.debounce_window[vmid] = DEBOUNCE_BASELINE
            self.buffer_events[vmid] = []  # flush aggregation buffer
            self.diverging_count[vmid] = 0
            self.recovery_lyap_count[vmid] = 0
            self.escalated[vmid] = False
            print(
                f"  [s3_alloc] LOOP2 RESTORE vmid={vmid} admit=1.0 "
                f"debounce={prev_window}→{DEBOUNCE_BASELINE} "
                f"regime={regime} recov_ticks={recov_count}",
                flush=True
            )
            ev = {
                "ts": _now(), "event_type": "s3_loop2_restore",
                "vsm_function": "S3", "vmid": vmid, "role": baseline["role"],
                "debounce_window_prev": prev_window,
                "debounce_window": DEBOUNCE_BASELINE,
                "lyapunov_regime": regime, "mean_dl": round(mean_dl, 6),
                "mean_l": round(mean_l, 6),
                "reason": f"loop2 restore admit=1.0 debounce={prev_window}→{DEBOUNCE_BASELINE} "
                          f"after {recov_count} recovery ticks",
                "a5_class": "single_loop",
            }
            ev = _build_audit_event(ev)
            events.append(ev)
            _log(ev)

        return events

    def observe_sync(self, vmid: str, stasis_cos: float) -> list[dict]:
        """Process one stasis_cos observation. Returns list of events."""
        if vmid not in LXC_REGISTRY:
            return []
        baseline = LXC_REGISTRY[vmid]
        events   = []

        depth        = self._stress_depth(stasis_cos)
        zone         = self._pool_zone()
        stressed     = stasis_cos < STRESS_THRESHOLD
        recovered    = stasis_cos >= RECOVERY_THRESHOLD
        currently_granted = self.extra_cores.get(vmid, 0) > 0 or self.extra_mem.get(vmid, 0) > 0

        if stressed:
            self.stress_count[vmid]   = self.stress_count.get(vmid, 0) + 1
            self.recovery_count[vmid] = 0
        elif recovered:
            self.recovery_count[vmid] = self.recovery_count.get(vmid, 0) + 1
            self.stress_count[vmid]   = 0

        # ── GRANT decision with AXIS 2 C2/C3 ───────────────────────────────────
        grant_eligible = (
            self.stress_count.get(vmid, 0) >= STRESS_TICKS
            and self.extra_cores.get(vmid, 0) < MAX_EXTRA_CORES
        )
        zone_blocks = (
            zone == "red"
            or (zone == "yellow" and depth < SEVERE_DEPTH)
        )

        if grant_eligible and not zone_blocks:
            raw_c, raw_m = self._proportional_grant(depth)
            # AXIS 2 SECOND-LOOP: scale grants by admit_rate (attenuation)
            admit = self.admit_rate.get(vmid, 1.0)
            if admit < 1.0:
                raw_c = max(0, int(round(raw_c * admit)))
                raw_m = max(0, int(round(raw_m * admit)))
            avail_c, avail_m = self._pool_available()
            grant_c = min(raw_c, MAX_EXTRA_CORES - self.extra_cores.get(vmid, 0), avail_c)
            grant_m = min(raw_m, MAX_EXTRA_MEM - self.extra_mem.get(vmid, 0), avail_m)

            if grant_c > 0 or grant_m > 0:
                # ── AXIS 2 C3: escalation check ──────────────────────────────
                cumulative_cores = self.extra_cores.get(vmid, 0) + grant_c
                cumulative_mem   = self.extra_mem.get(vmid, 0)   + grant_m
                escalate_reason = _check_escalation(
                    vmid=vmid,
                    grant_cores=grant_c,
                    grant_mem_mb=grant_m,
                    cumulative_cores=cumulative_cores,
                    cumulative_mem=cumulative_mem,
                    depth=depth,
                    pool_zone=zone,
                    stasis_cos=stasis_cos,
                )
                if escalate_reason:
                    # ESCALATE → HOLD, do NOT execute grant, emit algedonic
                    ev = {
                        "ts":           _now(),
                        "event_type":   "s3_resource_grant_escalated",
                        "vsm_function": "S3",
                        "vmid":         vmid,
                        "role":         baseline["role"],
                        "grant_cores":  grant_c,
                        "grant_mem_mb": grant_m,
                        "stress_depth": round(depth, 4),
                        "pool_zone":    zone,
                        "stasis_cos":   round(stasis_cos, 4),
                        "reason":       f"ESCALATED — {escalate_reason}",
                        "a5_class":     "single_loop",
                        "a5_gate":      "ESCALATION — HOLD (double-loop triggered)",
                        "pool_cores_remaining": POOL_CORES - self.pool_cores_used,
                        "pool_mem_remaining":   POOL_MEM_MB - self.pool_mem_used,
                    }
                    ev = _build_audit_event(ev, escalation=escalate_reason)
                    events.append(ev)
                    _log(ev)
                    # Also publish to global algedonic subject
                    events.append({"ts": _now(), "event_type": "algedonic_s3_escalation",
                                   "vmid": vmid, "reason": escalate_reason,
                                   "pool_zone": zone})
                    print(f"[S3 ESCALATE] vmid={vmid} reason={escalate_reason} — HOLD grant", flush=True)
                else:
                    new_cores = baseline["baseline_cores"] + self.extra_cores.get(vmid, 0) + grant_c
                    new_mem   = baseline["baseline_mem"]   + self.extra_mem.get(vmid, 0)   + grant_m
                    new_cores, new_mem = self._apply_floor(vmid, new_cores, new_mem)
                    ok = _proxmox_set(vmid, cores=new_cores, memory=new_mem)
                    if ok:
                        self.extra_cores[vmid] = self.extra_cores.get(vmid, 0) + grant_c
                        self.extra_mem[vmid]   = self.extra_mem.get(vmid, 0)   + grant_m
                        self.pool_cores_used  += grant_c
                        self.pool_mem_used    += grant_m
                        self.stress_count[vmid] = 0

                        ev = {
                            "ts":           _now(),
                            "event_type":   "s3_resource_grant",
                            "vsm_function": "S3",
                            "vmid":         vmid,
                            "role":         baseline["role"],
                            "grant_cores":  grant_c,
                            "grant_mem_mb": grant_m,
                            "stress_depth": round(depth, 4),
                            "pool_zone":    zone,
                            "new_cores":    new_cores,
                            "new_mem_mb":   new_mem,
                            "stasis_cos":   round(stasis_cos, 4),
                            "reason":       f"depth={depth:.3f} zone={zone} stasis_cos={stasis_cos:.3f} ticks={self.stress_count.get(vmid,0)}",
                            "a5_class":     "single_loop",
                            "pool_cores_remaining": POOL_CORES - self.pool_cores_used,
                            "pool_mem_remaining":   POOL_MEM_MB - self.pool_mem_used,
                        }
                        ev = _build_audit_event(ev)
                        events.append(ev)
                        _log(ev)
                        print(f"[S3 GRANT] vmid={vmid} depth={depth:.2f} zone={zone} +{grant_c}c +{grant_m}MB → {new_cores}c/{new_mem}MB", flush=True)

        # ── RESTORE decision (not zone-gated) ─────────────────────────────────
        if (self.recovery_count.get(vmid, 0) >= RECOVERY_TICKS and currently_granted):
            new_cores, new_mem = self._apply_floor(vmid, baseline["baseline_cores"], baseline["baseline_mem"])
            ok = _proxmox_set(vmid, cores=new_cores, memory=new_mem)
            if ok:
                self.pool_cores_used -= self.extra_cores.get(vmid, 0)
                self.pool_mem_used   -= self.extra_mem.get(vmid, 0)
                freed_c = self.extra_cores.pop(vmid, 0)
                freed_m = self.extra_mem.pop(vmid, 0)
                self.recovery_count[vmid] = 0

                ev = {
                    "ts":           _now(),
                    "event_type":   "s3_resource_restore",
                    "vsm_function": "S3",
                    "vmid":         vmid,
                    "role":         baseline["role"],
                    "freed_cores":  freed_c,
                    "freed_mem_mb": freed_m,
                    "restored_cores": new_cores,
                    "restored_mem_mb": new_mem,
                    "stasis_cos":   round(stasis_cos, 4),
                    "reason":       f"stasis_cos={stasis_cos:.3f}>={RECOVERY_THRESHOLD} for {RECOVERY_TICKS} ticks",
                    "a5_class":     "single_loop",
                    "pool_cores_remaining": POOL_CORES - self.pool_cores_used,
                    "pool_mem_remaining":   POOL_MEM_MB - self.pool_mem_used,
                }
                ev = _build_audit_event(ev)
                events.append(ev)
                _log(ev)
                print(f"[S3 RESTORE] vmid={vmid} → baseline {new_cores}c/{new_mem}MB (freed {freed_c}c/{freed_m}MB)", flush=True)

        # ── Zone-alert for RED pool (algedonic + AXIS 2 C2 audit) ──────────────
        if zone == "red" and self.stress_count.get(vmid, 0) >= STRESS_TICKS:
            ev = {
                "ts":           _now(),
                "event_type":   "s3_pool_red_algedonic",
                "vsm_function": "S3",
                "vmid":         vmid,
                "role":         baseline["role"],
                "stress_depth": round(depth, 4),
                "pool_zone":    "red",
                "stasis_cos":   round(stasis_cos, 4),
                "reason":       f"RED zone — pool exhausted, grant blocked. depth={depth:.3f} used_cores={self.pool_cores_used}/{POOL_CORES}",
                "a5_class":     "single_loop",
                "pool_cores_remaining": POOL_CORES - self.pool_cores_used,
                "pool_mem_remaining":   POOL_MEM_MB - self.pool_mem_used,
            }
            ev = _build_audit_event(ev, escalation=ev["reason"])
            events.append(ev)
            _log(ev)
            print(f"[S3 ALGEDONIC] vmid={vmid} RED zone — pool exhausted, grant blocked", flush=True)

        return events


async def run():
    bargain = ResourceBargain()
    guard   = GuardMemory()
    nc      = await nats.connect(NATS_URL)
    print(f"[s3_alloc] started  node={PROXMOX_NODE}  pool={POOL_CORES}c/{POOL_MEM_MB}MB  "
          f"safety_margin={SAFETY_MARGIN:.0%}  zones:green<{ZONE_GREEN_MAX:.0%} yellow<{ZONE_YELLOW_MAX:.0%} red>={ZONE_YELLOW_MAX:.0%}  "
          f"grant_scale=GRANT_MIN_CORES={GRANT_MIN_CORES}c/{GRANT_MIN_MEM}MB → GRANT_MAX_CORES={GRANT_MAX_CORES}c/{GRANT_MAX_MEM}MB  "
          f"guard_pool={GUARD_POOL_MB}MB bump={GUARD_BUMP_MB}MB cap={GUARD_CAP_MB}MB  "
          f"guard_hi={GUARD_HI_PCT:.0%}×{GUARD_HI_TICKS} guard_lo={GUARD_LO_PCT:.0%}×{GUARD_LO_TICKS}",
          flush=True)

    # ── Publish grant events to NATS φ↑ + S3* audit chain ───────────────────
    async def publish_events(events: list[dict]):
        for ev in events:
            await nc.publish(GRANT_SUBJECT, json.dumps(ev).encode())
            print(f"  [s3_alloc] → {GRANT_SUBJECT}: {ev['event_type']} vmid={ev['vmid']}", flush=True)
            # AXIS 2 C2: also publish to S3* audit chain
            if ev.get("audit_source") == "s3_resource_alloc":
                await nc.publish(AUDIT_SUBJECT, json.dumps(ev).encode())
                print(f"  [s3_alloc] → {AUDIT_SUBJECT}: {ev['event_type']} vmid={ev['vmid']} (audit trail)", flush=True)

    # ── Subscribe: S1-clima φ↑ — system-level aggregates only ──────────────
    # S3 resource decisions respond to SYSTEM-level stasis_cos (continental),
    # not to individual zone events (S2-level noise would reset stress counters
    # from intermediate sc values and prevent grants from ever firing).
    async def on_clima(msg):
        try:
            e = json.loads(msg.data)
            # Only act on the system-level aggregate (vsf.clima.continental.phi_up)
            if e.get("vsm_level", 0) < 3 and "continental" not in msg.subject:
                return
            # Accept stasis_cos from either zone-aggregate or system-aggregate events
            sc = (e.get("stasis_cos") if e.get("stasis_cos") is not None
                  else e.get("stasis_cos_sys") if e.get("stasis_cos_sys") is not None
                  else e.get("mean_stasis_cos"))
            if sc is None:
                return
            sc = float(sc)
            vmid = "112"
            print(f"  [s3_alloc] clima system φ↑ subj={msg.subject} sc={sc:.3f} vmid={vmid}", flush=True)
            # Run blocking Proxmox API in thread pool to not block async event loop
            evts = await asyncio.to_thread(bargain.observe_sync, vmid, sc)
            if evts:
                await publish_events(evts)
        except Exception as ex:
            print(f"  [s3_alloc] clima err: {ex}", flush=True)

    # ── Subscribe: S1-econ φ↑ — system-level (chile aggregate) only ─────────
    async def on_econ(msg):
        try:
            e = json.loads(msg.data)
            sc = e.get("stasis_cos")
            if sc is None:
                return
            vmid = "113"
            print(f"  [s3_alloc] econ φ↑ subj={msg.subject} sc={float(sc):.3f} vmid={vmid}", flush=True)
            evts = await asyncio.to_thread(bargain.observe_sync, vmid, float(sc))
            if evts:
                await publish_events(evts)
        except Exception as ex:
            print(f"  [s3_alloc] econ err: {ex}", flush=True)

    # ── Subscribe: nucleus kernel_tick (S3S4 self-monitoring) ────────────────
    # AXIS 2 C1: extracts margin_free for early-warning anticipatory grant.
    async def on_nucleus(msg):
        try:
            e = json.loads(msg.data)
            m = e.get("metrics", {})
            kernel = m.get("kernel", {})
            sc = kernel.get("stasis_cos")
            if sc is None:
                return
            vmid = "101"

            # ── Stasis-based grant (existing) ──────────────────────────────────
            evts = await asyncio.to_thread(bargain.observe_sync, vmid, float(sc))
            if evts:
                await publish_events(evts)

            # ── AXIS 2 C1: margin_free early-warning (independent) ──────────
            margin_free = kernel.get("margin_free")
            if margin_free is None:
                omega = m.get("omega", {})
                margin_free = omega.get("margin_free")
            if margin_free is not None:
                mf = float(margin_free)
                if mf < MARGIN_EARLY_WARNING:
                    print(f"  [s3_alloc] MARGIN early-warning vmid={vmid} mf={mf:.4f} < {MARGIN_EARLY_WARNING}", flush=True)
                    margin_evts = await asyncio.to_thread(bargain.observe_margin, vmid, mf)
                    if margin_evts:
                        await publish_events(margin_evts)

            # ── AXIS 2 SECOND-LOOP PHASE-2: aggregation attenuator ──────
            # Before divergence detection, buffer/aggregate phi_up events
            # within the debounce window to reduce input variety.
            lyapunov      = m.get("lyapunov", {})
            lyapunov_regime = lyapunov.get("regime")
            if lyapunov_regime is not None and lyapunov_regime != "unknown":
                # Phase-2: aggregate (buffer within debounce window)
                agg_evts = await asyncio.to_thread(
                    bargain._aggregate_phi_up, vmid, lyapunov
                )
                if agg_evts:
                    await publish_events(agg_evts)

                # Phase-2 v1+v2: divergence detection + admit_rate + debounce
                omega = m.get("omega", {})
                margin_binding = omega.get("margin_binding", "")
                div_evts = await asyncio.to_thread(
                    bargain.observe_divergence, vmid, lyapunov, margin_binding
                )
                if div_evts:
                    await publish_events(div_evts)
        except Exception as ex:
            print(f"  [s3_alloc] nucleus err: {ex}", flush=True)

    await nc.subscribe("vsf.clima.>",                          cb=on_clima)
    await nc.subscribe("vsf.econ.chile.phi_up",                cb=on_econ)
    await nc.subscribe("vsf.alpha.vsf_nucleus.up.kernel_tick", cb=on_nucleus)

    print(f"[s3_alloc] subscribed to φ↑ channels. Watching stasis_cos...", flush=True)

    guard_ticks = 0  # guard runs every 2nd loop iteration (~60s)
    try:
        while True:
            await asyncio.sleep(30)
            guard_ticks += 1

            # ── Bargain pool zone report ──────────────────────────────────────
            zone = bargain._pool_zone()
            print(
                f"[s3_alloc] zone={zone} pool: {bargain.pool_cores_used}/{POOL_CORES}c "
                f"{bargain.pool_mem_used}/{POOL_MEM_MB}MB used  "
                f"grants_active={len([v for v in bargain.extra_cores if bargain.extra_cores[v]>0])}  "
                f"guard_used={guard.guard_used_mb}/{GUARD_POOL_MB}MB "
                f"guard_bumps={len([v for v in guard.extra_mem if guard.extra_mem[v]>0])}",
                flush=True
            )

            # ── TIER 2 guard tick (every other loop = ~60s) ──────────────────
            if guard_ticks % 2 == 0:
                for vmid, cfg in sorted(LXC_REGISTRY.items()):
                    evts = guard.tick(vmid, cfg["baseline_mem"])
                    if evts:
                        await publish_events(evts)
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(run())
