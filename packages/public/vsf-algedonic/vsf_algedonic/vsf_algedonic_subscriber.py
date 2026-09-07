#!/usr/bin/env python3
"""VSF Algedonic Subscriber — S5 Console listener + M3 Caution Mode + M7 HMAC chain.

Subscribes to vsf.<vsf_id>.algedonic via nats-py (resilient connection).
Persists incoming algedonic events to a local jsonl + prints loud notifications.

Closes BRECHA-4 ('algedonic sin oyente') from docs/WRITER_READER_DECIDER_MATRIX.md.

ITEM_4.1 M3 — S5 Caution Mode:
  High-severity algedonic (sev >= CAUTION_THRESHOLD) or trigger categories
  → S5 enters caution mode → publishes vsf.<id>.s5.caution {active: true}
  → nucleus S3 auto-controller holds all autonomous actions.
  Auto-expires after CAUTION_DURATION_S (default 30 min).
  Explicit clearing: category == CLEARING_CATEGORY.
  HTTP endpoint: GET http://<host>:8091/caution  (for ac_algedonic.py polling)

M7 — HMAC alert chain (2026-06-26):
  Each persisted event includes _c_prev (hash of previous entry content) and
  _c_hash = HMAC-SHA256(key, prev_hash || content).
  Key: /var/lib/vsf/alg_hmac.key (offline copy on WSL).
  Verify: scripts/vsl/alg_chain_verify.py  or GET :8091/chain_anchor
  Chain epoch: 2026-06-26 (entries before this date have no chain fields).

Per docs/operational/bbh_publisher_contract.md §5 — algedonic channel is binary
{0,1}. Payload always includes source_id and category for differentiation at S5.

MIGRATION NOTE (2026-08-28): Migrated from raw TCP sockets to nats-py for
resilient connections with automatic reconnection. Uses vsf_nats.connect_resilient().
"""
import asyncio
import json
import os
import sys
import time
import hmac as _hmac
import hashlib
import threading
from datetime import datetime, timezone

# Add scripts/state/shared to path for vsf_nats import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "state", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
import vsf_nats
from http_server_mixin import SilentHTTPHandler, create_silent_server

NATS_HOST = os.environ.get("NATS_HOST", "10.10.20.20")
NATS_PORT = int(os.environ.get("NATS_PORT", "4222"))
NATS_URL = f"nats://{NATS_HOST}:{NATS_PORT}"


def _nats_token() -> str:
    """Token from the environment, else from the canonical creds file.

    The unit may not carry an EnvironmentFile, so fall back to the same
    /etc/vsf/nats-creds.env every other component reads. Returning "" is
    reported loudly at connect time rather than failing silently.
    """
    tok = os.environ.get("NATS_TOKEN", "")
    if tok:
        return tok
    try:
        with open("/etc/vsf/nats-creds.env", "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("NATS_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


NATS_TOKEN = _nats_token()
VSF_ID = os.environ.get("VSF_ID", "alpha")
SUBJECT = f"vsf.{VSF_ID}.algedonic"
CAUTION_SUBJECT = f"vsf.{VSF_ID}.s5.caution"
OUT_PATH = os.environ.get("VSF_ALGEDONIC_LOG", "/root/algedonic/vsf_algedonic.jsonl")
CAUTION_STATE_FILE = os.environ.get("VSF_CAUTION_STATE", "/root/algedonic/caution_mode.json")
CHAIN_KEY_PATH = os.environ.get("VSF_CHAIN_KEY", "/var/lib/vsf/alg_hmac.key")
CHAIN_ANCHOR_PATH = os.environ.get("VSF_CHAIN_ANCHOR", "/root/algedonic/chain_anchor.json")
CAUTION_HTTP_PORT = int(os.environ.get("CAUTION_HTTP_PORT", "8091"))
RECONNECT_DELAY_S = 5
SUB_ID = "vsf-s5-console-1"

# M3 Caution Mode thresholds
CAUTION_THRESHOLD_SEV = float(os.environ.get("CAUTION_THRESHOLD_SEV", "8.0"))
CAUTION_TRIGGER_CATEGORIES = {
    "service_down", "covenant_drift", "covenant_ops_binding_drift",
    "s5_stress",  # explicit stress signal
}
CLEARING_CATEGORY = "s5_clear"
CAUTION_DURATION_S = int(os.environ.get("CAUTION_DURATION_S", "1800"))  # 30 min default

# M7 HMAC chain state (module-level, updated by persist())
_chain_state = {"prev_hash": "genesis", "count": 0}
_chain_key: bytes | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# ── M7: HMAC chain ─────────────────────────────────────────────────────────────

def _load_chain_key() -> bytes | None:
    try:
        return bytes.fromhex(open(CHAIN_KEY_PATH).read().strip())
    except Exception as e:
        print(f"[s5-chain] key not loaded ({CHAIN_KEY_PATH}): {e} — chain disabled", flush=True)
        return None


def _compute_chain_hash(key: bytes, prev: str, content: str) -> str:
    return _hmac.new(key, (prev + content).encode(), hashlib.sha256).hexdigest()


def _write_chain_anchor() -> None:
    anchor = {
        "prev_hash": _chain_state["prev_hash"],
        "count": _chain_state["count"],
        "updated_at": now_iso(),
    }
    os.makedirs(os.path.dirname(CHAIN_ANCHOR_PATH), exist_ok=True)
    with open(CHAIN_ANCHOR_PATH, "w") as f:
        json.dump(anchor, f)


def _init_chain_state() -> None:
    """Resume chain from last entry in log (continuity across service restarts)."""
    global _chain_state
    if not os.path.exists(OUT_PATH):
        return
    try:
        with open(OUT_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return
            pos = max(0, size - 4096)
            f.seek(pos)
            tail = f.read()
        last_line = tail.rstrip(b"\n").rsplit(b"\n", 1)[-1]
        last = json.loads(last_line)
        if "_c_hash" in last:
            _chain_state["prev_hash"] = last["_c_hash"]
            try:
                anchor = json.loads(open(CHAIN_ANCHOR_PATH).read())
                _chain_state["count"] = anchor.get("count", 0)
            except Exception:
                pass
            print(f"[s5-chain] resumed: prev={_chain_state['prev_hash'][:16]}... count={_chain_state['count']}", flush=True)
        else:
            print(f"[s5-chain] last entry has no chain fields — starting fresh chain epoch", flush=True)
    except Exception as e:
        print(f"[s5-chain] init error: {e}", flush=True)


def persist(record: dict) -> None:
    """Append record to algedonic jsonl. Adds HMAC chain fields if key available."""
    if _chain_key is not None:
        clean = json.dumps(record, sort_keys=True, ensure_ascii=False)
        new_hash = _compute_chain_hash(_chain_key, _chain_state["prev_hash"], clean)
        record = {**record, "_c_prev": _chain_state["prev_hash"], "_c_hash": new_hash}
        _chain_state["prev_hash"] = new_hash
        _chain_state["count"] += 1
        if _chain_state["count"] % 10 == 0:
            _write_chain_anchor()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── M3: HTTP server for caution state polling ──────────────────────────────────

class _CautionHTTPHandler(SilentHTTPHandler):
    """HTTP handler for caution state polling. Uses SilentHTTPHandler mixin."""
    
    def do_GET(self):
        if self.path == "/caution":
            try:
                data = open(CAUTION_STATE_FILE, "rb").read()
            except Exception:
                data = b'{"active": false}'
            self._respond(200, data)
        elif self.path == "/chain_anchor":
            try:
                data = open(CHAIN_ANCHOR_PATH, "rb").read()
            except Exception:
                data = b'{"count": 0}'
            self._respond(200, data)
        else:
            self._respond(404, b'{"error": "not found"}')


def _start_caution_http_server() -> None:
    server = create_silent_server(("0.0.0.0", CAUTION_HTTP_PORT), _CautionHTTPHandler)
    print(f"[s5-caution] HTTP state server listening :{CAUTION_HTTP_PORT}", flush=True)
    server.serve_forever()


# ── Caution state machine ──────────────────────────────────────────────────────

def loud_notify(record: dict) -> None:
    """Tier α: stderr print with bell + obvious banner."""
    ts = record.get("received_at", "?")
    payload = record.get("payload") or {}
    category = payload.get("category") or "?"
    severity = payload.get("severity") or "?"
    source = payload.get("source_id") or "?"
    print(
        f"\007\n"
        f"════════════════════════════════════════════════════════════\n"
        f"  ALGEDONIC RECEIVED — VSF S5 CONSOLE                    \n"
        f"  ts={ts}\n"
        f"  source_id={source}  category={category}  severity={severity}\n"
        f"  subject={record.get('subject','?')}\n"
        f"  payload={json.dumps(payload, ensure_ascii=False)[:200]}\n"
        f"════════════════════════════════════════════════════════════\n",
        flush=True,
    )


class CautionState:
    """M3 — S5 Caution Mode state machine.

    Transitions:
      clear → active  when high-severity or trigger_category arrives
      active → clear  when CAUTION_DURATION_S elapses OR clearing signal arrives
    """

    def __init__(self):
        self.active = False
        self.entered_at: float = 0.0
        self.trigger_category: str = ""
        self.trigger_sev: float = 0.0
        self._load_from_file()

    def _load_from_file(self):
        try:
            with open(CAUTION_STATE_FILE) as f:
                st = json.load(f)
            if st.get("active") and st.get("entered_at_epoch", 0) + CAUTION_DURATION_S > time.time():
                self.active = True
                self.entered_at = st["entered_at_epoch"]
                self.trigger_category = st.get("trigger_category", "?")
                self.trigger_sev = st.get("trigger_sev", 0.0)
                print(f"[s5-caution] RESTORED caution mode (entered {self.trigger_category} sev={self.trigger_sev})", flush=True)
        except Exception:
            pass

    def _write_file(self):
        os.makedirs(os.path.dirname(CAUTION_STATE_FILE), exist_ok=True)
        state = {
            "active": self.active,
            "entered_at_epoch": self.entered_at,
            "entered_at_iso": datetime.fromtimestamp(self.entered_at, tz=timezone.utc).isoformat() if self.entered_at else None,
            "expires_at_iso": datetime.fromtimestamp(self.entered_at + CAUTION_DURATION_S, tz=timezone.utc).isoformat() if self.active and self.entered_at else None,
            "trigger_category": self.trigger_category,
            "trigger_sev": self.trigger_sev,
            "updated_at": now_iso(),
        }
        with open(CAUTION_STATE_FILE, "w") as f:
            json.dump(state, f)

    def check_expiry(self) -> bool:
        """Returns True if caution mode just expired (caller should publish clear)."""
        if self.active and time.time() > self.entered_at + CAUTION_DURATION_S:
            self.active = False
            self._write_file()
            print(f"[s5-caution] EXPIRED — returning to clear (was {self.trigger_category})", flush=True)
            return True
        return False

    def process_event(self, payload: dict) -> tuple[bool, bool]:
        """Process incoming algedonic payload.
        Returns (was_changed: bool, new_state: bool).
        """
        category = payload.get("category", "")
        severity = float(payload.get("severity", 0.0))

        if category == CLEARING_CATEGORY:
            if self.active:
                self.active = False
                self._write_file()
                print(f"[s5-caution] CLEARED via explicit signal", flush=True)
                return True, False
            return False, False

        triggers = severity >= CAUTION_THRESHOLD_SEV or category in CAUTION_TRIGGER_CATEGORIES
        if triggers and not self.active:
            self.active = True
            self.entered_at = time.time()
            self.trigger_category = category
            self.trigger_sev = severity
            self._write_file()
            print(
                f"[s5-caution] ENTERED — category={category} sev={severity} "
                f"duration={CAUTION_DURATION_S}s",
                flush=True,
            )
            return True, True

        return False, self.active


# ── NATS helpers (async) ──────────────────────────────────────────────────────

async def publish_caution(nc, active: bool, caution: CautionState) -> None:
    """Publish caution state to NATS."""
    payload = {
        "active": active,
        "ts": now_iso(),
        "trigger_category": caution.trigger_category,
        "trigger_sev": caution.trigger_sev,
        "expires_in_s": max(0, int(caution.entered_at + CAUTION_DURATION_S - time.time())) if active else 0,
    }
    await nc.publish(CAUTION_SUBJECT, json.dumps(payload).encode())
    state_str = "ACTIVE" if active else "CLEAR"
    print(f"[s5-caution] published {state_str} → {CAUTION_SUBJECT}", flush=True)


# ── Main loop (async) ─────────────────────────────────────────────────────────

async def message_handler(msg):
    """Handle incoming NATS messages."""
    try:
        payload = json.loads(msg.data.decode())
    except Exception as e:
        payload = {"_parse_error": str(e), "_raw": msg.data.decode(errors="replace")[:200]}
    
    record = {
        "received_at": now_iso(),
        "subject": msg.subject,
        "payload": payload,
    }
    persist(record)
    loud_notify(record)

    # Process caution state (global caution object)
    changed, new_state = _caution_state.process_event(payload)
    if changed:
        await publish_caution(msg._client, new_state, _caution_state)


# Global caution state (initialized in main)
_caution_state: CautionState = None


async def run_async():
    """Main async loop using nats-py with resilient connection."""
    global _chain_key, _caution_state
    
    print(f"[s5-alg] starting — target {NATS_URL} subj {SUBJECT}", flush=True)

    # M7: init HMAC chain
    _chain_key = _load_chain_key()
    if _chain_key:
        _init_chain_state()
        _write_chain_anchor()
        print(f"[s5-chain] HMAC chain active — prev={_chain_state['prev_hash'][:16]}...", flush=True)

    # M3: start HTTP state server (background thread)
    t = threading.Thread(target=_start_caution_http_server, daemon=True)
    t.start()

    # Build URL with token if available
    url = NATS_URL
    if NATS_TOKEN:
        url = f"nats://{NATS_TOKEN}@{NATS_HOST}:{NATS_PORT}"

    # Connect using vsf_nats resilient connection
    nc = await vsf_nats.connect_resilient(
        url,
        name="vsf-s5-algedonic-console",
        log_prefix="s5-alg",
    )

    # Subscribe to algedonic subject
    await nc.subscribe(SUBJECT, cb=message_handler)
    print(f"[s5-alg] subscribed {SUBJECT} sid={SUB_ID} — log → {OUT_PATH}", flush=True)

    # Publish initial caution state if active
    if _caution_state.active:
        await publish_caution(nc, True, _caution_state)

    # Keep alive and check caution expiry
    while True:
        await asyncio.sleep(1)
        if _caution_state.check_expiry():
            await publish_caution(nc, False, _caution_state)


def main():
    global _caution_state
    _caution_state = CautionState()
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
