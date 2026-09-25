#!/usr/bin/env python3
"""BBS Decisions Bridge — S4 thoughts → φ↓ actions (Tier α whitelist-gated).

Closes BRECHA-5 + BRECHA-6 from docs/WRITER_READER_DECIDER_MATRIX.md:
  - BRECHA-5: φ↓ solo manual (humano via NATS publish)
  - BRECHA-6: S4 decisions die in BBS without enforcement

Architecture (Beer-faithful):
  S4 (Qwen) → s4-analysis event (BBS + events.jsonl)
       ↓
  γ.2 nats_publisher relays event to vsf.alpha.vsf_nucleus.up.s4-analysis
       ↓
  THIS bridge subscribes that subject
       ↓
  Check metrics.first_action against WHITELIST regex
       ↓
  IF match:    emit phi_down patch on vsf.alpha.phi_down.params
  IF no match: log "skipped, requires human" + algedonic info

Per Beer:
  - S5 owns the WHITELIST (policy)
  - S3 implements whitelisted decisions on S1 (this bridge IS that S3 actuator)
  - Non-whitelisted decisions require S5 human review (algedonic visibility)

Tier α scope:
  - whitelist embedded in script (will move to s5_policy.json Tier β)
  - regex-based matching on first_action
  - whitelisted actions limited to safe config tweaks (log_level changes)
  - cooldown to prevent oscillation (1 patch per 5min max)

Subject hierarchy:
  in:  vsf.alpha.vsf_nucleus.up.s4-analysis
  out: vsf.alpha.phi_down.params
  algedonic if non-whitelisted: vsf.alpha.algedonic

MIGRATION NOTE (2026-08-28): Migrated from raw TCP sockets to nats-py for
resilient connections with automatic reconnection. Uses vsf_nats.connect_resilient().
"""
import asyncio
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone

# vsf_nats: try installed package, then checkout-relative path (legacy
# scripts/state/shared layout). Unavailable -> None; connection sites
# raise an informative error instead of breaking import (2026-09-24).
try:
    import vsf_nats
    _VSF_NATS_OK = True
except ImportError:
    vsf_nats = None  # type: ignore
    _VSF_NATS_OK = False

NATS_HOST = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT = int(os.environ.get("NATS_PORT", "4222"))
NATS_URL = f"nats://{NATS_HOST}:{NATS_PORT}"
VSF_ID = os.environ.get("VSF_ID", "alpha")
LOG_PATH = os.environ.get("BBS_BRIDGE_LOG", "/root/algedonic/bbs_bridge.jsonl")
S5_POLICY_PATH = os.environ.get("S5_POLICY_PATH", "/etc/vsf/s5_policy.json")

SUB_S4 = f"vsf.{VSF_ID}.vsf_nucleus.up.s4-analysis"
PUB_PHI_DOWN = f"vsf.{VSF_ID}.phi_down.params"
PUB_ALGEDONIC = f"vsf.{VSF_ID}.algedonic"
SUB_ID = "vsf-bbs-bridge-1"

RECONNECT_DELAY_S = 5
DEFAULT_COOLDOWN_S = 20  # default when policy doesn't specify (Phase 4.2 ALG-1 coupled)

# Phase 4.1 — WHITELIST and COOLDOWN now come from s5_policy.json :: bbs_bridge.
# Policy reloads on SIGHUP. Falls back to embedded default if policy unreadable.
FALLBACK_WHITELIST = [
    {
        "name": "set_log_debug",
        "pattern": r"(?i)(set|change|enable).*(log[\s_]*level).*(debug|verbose)",
        "patch": {"log_level": "debug"},
        "rationale": "[FALLBACK] policy unreadable, embedded default rule"
    },
]

# Compiled state — replaced on policy load
_WHITELIST = []  # list of dicts with .pattern (compiled regex), .patch, .name, .rationale
_COOLDOWN_S = DEFAULT_COOLDOWN_S
_POLICY_LOADED_AT = 0.0


def _resolve_cooldown(policy: dict) -> float:
    """Phase 4.2 — resolve effective cooldown.
    Precedence:
      1. bbs_bridge.cooldown_secs (if set and not null) → fixed override
      2. bbs_bridge.cooldown_coupling == 'k_times_tau_algedonic' →
         k * (1/algedonic.decay_lambda)
      3. fallback DEFAULT_COOLDOWN_S
    """
    bbs_cfg = policy.get("bbs_bridge") or {}
    explicit = bbs_cfg.get("cooldown_secs")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return float(explicit)
    coupling = bbs_cfg.get("cooldown_coupling", "k_times_tau_algedonic")
    if coupling == "k_times_tau_algedonic":
        decay = (policy.get("algedonic") or {}).get("decay_lambda", 0.1)
        if not isinstance(decay, (int, float)) or decay <= 0:
            return DEFAULT_COOLDOWN_S
        k = bbs_cfg.get("cooldown_k", 2)
        if not isinstance(k, (int, float)) or k < 0:
            k = 2
        derived = float(k) * (1.0 / float(decay))
        return derived
    return DEFAULT_COOLDOWN_S


def load_policy_whitelist(path: str = None):
    """Load bbs_bridge.allowed_actions[] from s5_policy.json + compile regex.
    Falls back to FALLBACK_WHITELIST on any read/parse error. Updates module
    globals. Idempotent — safe to call from SIGHUP handler or startup.
    """
    global _WHITELIST, _COOLDOWN_S, _POLICY_LOADED_AT
    path = path or S5_POLICY_PATH
    try:
        with open(path) as f:
            policy = json.load(f)
        bbs_cfg = policy.get("bbs_bridge") or {}
        raw_rules = bbs_cfg.get("allowed_actions") or []
        cooldown = _resolve_cooldown(policy)
        compiled = []
        for r in raw_rules:
            try:
                compiled.append({
                    "name": r["name"],
                    "pattern": re.compile(r["pattern"]),
                    "patch": dict(r["patch"]),
                    "rationale": r.get("rationale", ""),
                })
            except Exception as e:
                print(f"[bbs-bridge] skip malformed rule {r.get('name')}: {e}", flush=True)
        if not compiled:
            print(f"[bbs-bridge] WARN: policy bbs_bridge has zero rules — using FALLBACK", flush=True)
            compiled = [
                {**r, "pattern": re.compile(r["pattern"])} for r in FALLBACK_WHITELIST
            ]
        _WHITELIST = compiled
        _COOLDOWN_S = float(cooldown)
        _POLICY_LOADED_AT = time.time()
        print(
            f"[bbs-bridge] policy loaded from {path}: "
            f"{len(_WHITELIST)} rules, cooldown={_COOLDOWN_S}s",
            flush=True,
        )
    except Exception as e:
        print(f"[bbs-bridge] policy load FAILED ({path}): {e} — using FALLBACK", flush=True)
        _WHITELIST = [
            {**r, "pattern": re.compile(r["pattern"])} for r in FALLBACK_WHITELIST
        ]
        _COOLDOWN_S = DEFAULT_COOLDOWN_S
        _POLICY_LOADED_AT = time.time()


def _on_sighup(_signum, _frame):
    print("[bbs-bridge] SIGHUP received — reloading policy", flush=True)
    load_policy_whitelist()


# (Legacy hardcoded WHITELIST removed Phase 4.1 — rules now live in
#  s5_policy.json :: bbs_bridge.allowed_actions[])

_last_phi_down_ts = 0.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def log_record(record: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def loud(line: str) -> None:
    print(line, flush=True)


def evaluate_whitelist(first_action: str):
    """Return (rule_dict, None) on match OR (None, "no match") on miss.
    Reads from _WHITELIST module global (populated by load_policy_whitelist
    on startup + SIGHUP reload)."""
    if not first_action:
        return None, "empty first_action"
    for rule in _WHITELIST:
        if rule["pattern"].search(first_action):
            return rule, None
    return None, "no whitelist match"


# ── NATS message handler (async) ──────────────────────────────────────────────

async def message_handler(msg):
    """Handle incoming NATS messages from S4 analysis."""
    global _last_phi_down_ts
    
    try:
        payload = json.loads(msg.data.decode())
    except Exception as e:
        loud(f"[bbs-bridge] skip malformed: {e}")
        return
    
    metrics = (payload or {}).get("metrics") or {}
    first_action = (metrics.get("first_action") or "").strip()
    decisions_count = metrics.get("decisions_count", 0)

    record = {
        "received_at": now_iso(),
        "in_subject": msg.subject,
        "first_action": first_action,
        "decisions_count": decisions_count,
        "bbs_msg_id": metrics.get("bbs_msg_id"),
    }

    rule, miss_reason = evaluate_whitelist(first_action)

    if rule is None:
        # Non-whitelisted — log + ping S5 via algedonic (info severity, not alarm)
        record["outcome"] = "skipped_no_whitelist"
        record["reason"] = miss_reason
        log_record(record)
        loud(f"[bbs-bridge] SKIP first_action={first_action!r} ({miss_reason})")
        # Emit info-level algedonic so S5 console sees it (advisory, not alarm)
        alg_payload = json.dumps({
            "ts": now_iso(),
            "source_id": "vsf-bbs-bridge",
            "category": "decision_not_whitelisted",
            "severity": 3.0,
            "signal": 1,
            "first_action": first_action,
            "_note": "S4 decision skipped — needs human review (not in whitelist)",
        }).encode()
        await msg._client.publish(PUB_ALGEDONIC, alg_payload)
        return

    # Cooldown check
    now = time.time()
    gap = now - _last_phi_down_ts
    if gap < _COOLDOWN_S:
        record["outcome"] = "rate_limited"
        record["matched_rule"] = rule["name"]
        record["cooldown_remaining_s"] = round(_COOLDOWN_S - gap, 1)
        log_record(record)
        loud(f"[bbs-bridge] COOLDOWN rule={rule['name']} remaining={_COOLDOWN_S-gap:.1f}s")
        return

    # Emit phi_down patch
    # G-H.2: _origin now carries the originating bbs_msg_id of the
    # s4-analysis event that triggered this patch. With #112 + G-K.2 in
    # place upstream, this lets k_phi_down_meter pair param_change.origin
    # against s4-analysis.origin causally — closing the meter-bounded
    # caveat on K_φ↓.
    _last_phi_down_ts = now
    patch = dict(rule["patch"])
    patch["_origin"] = record.get("bbs_msg_id") or "vsf-bbs-bridge"
    patch["_emitter"] = "vsf-bbs-bridge"  # human-readable tag, separate from causal origin
    patch["_reason"] = f"S4 decision matched rule '{rule['name']}': {rule['rationale']}"
    patch["_source_first_action"] = first_action
    payload_bytes = json.dumps(patch).encode()
    await msg._client.publish(PUB_PHI_DOWN, payload_bytes)

    record["outcome"] = "phi_down_emitted"
    record["matched_rule"] = rule["name"]
    record["patch"] = patch
    log_record(record)
    loud(f"\n════════════════════════════════════════════════════════════\n"
         f"  ✓ φ↓ EMITTED via BBS bridge\n"
         f"  rule={rule['name']}  patch={patch}\n"
         f"  source first_action={first_action!r}\n"
         f"════════════════════════════════════════════════════════════")


# ── Main loop (async) ─────────────────────────────────────────────────────────

async def run_async():
    """Main async loop using nats-py with resilient connection."""
    loud(f"[bbs-bridge] starting — target {NATS_URL}")
    loud(f"[bbs-bridge] subscribe={SUB_S4}  publish={PUB_PHI_DOWN}|{PUB_ALGEDONIC}")
    
    # Phase 4.1 — load policy whitelist from s5_policy.json + wire SIGHUP reload
    load_policy_whitelist()
    try:
        signal.signal(signal.SIGHUP, _on_sighup)
        loud(f"[bbs-bridge] SIGHUP handler wired — kill -HUP $(pid) to reload policy")
    except (AttributeError, ValueError) as e:
        loud(f"[bbs-bridge] SIGHUP unavailable on this platform: {e}")

    # Build URL with token if available
    NATS_TOKEN = os.environ.get("NATS_TOKEN", "")
    url = NATS_URL
    if NATS_TOKEN:
        url = f"nats://{NATS_TOKEN}@{NATS_HOST}:{NATS_PORT}"

    # Connect using vsf_nats resilient connection
    if not _VSF_NATS_OK:
        raise RuntimeError("vsf_nats unavailable: install it or run inside vOSlab checkout")
    nc = await vsf_nats.connect_resilient(
        url,
        name="vsf-bbs-decisions-bridge",
        log_prefix="bbs-bridge",
    )

    # Subscribe to S4 analysis subject
    await nc.subscribe(SUB_S4, cb=message_handler)
    loud(f"[bbs-bridge] ready — whitelist rules={len(_WHITELIST)} cooldown={_COOLDOWN_S}s")

    # Keep alive
    while True:
        await asyncio.sleep(1)


def main():
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
