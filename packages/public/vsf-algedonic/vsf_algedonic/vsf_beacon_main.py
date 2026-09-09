"""
vsf_beacon_main.py — BEACON-ACTIVATION: VSF Beacon with Ed25519 attestation protocol.

This is the ACTIVATED version of the beacon (was dormant main.py).
Replaces the old main.py (port 8080) which had RSA hybrid encryption but NO
cert verification and no registry.jsonl.

Changes from original main.py (2026-07-04):
  - Adds Ed25519 attestation verification (cert chain + payload sig + covenant)
  - Writes TRUSTED/REJECTED to registry.jsonl
  - Binds to 127.0.0.1 (behind Caddy, not public-facing)
  - Systemd-managed (not manual/nohup)

Deploy to n01:
  scp scripts/vsf_beacon_main.py n01-vsf:/opt/vsf-beacon/main.py
  scp scripts/beacon_attestation.py n01-vsf:/opt/vsf-beacon/
  scp _beacon_ca/ca.pubkey.hex n01-vsf:/opt/vsf-beacon/
  # Caddy: add route → reverse_proxy localhost:8080
  # systemd: vsf-beacon.service

Usage:
  uvicorn vsf_beacon_main:app --host 127.0.0.1 --port 8080
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, field_validator

# ── Attestation module ─────────────────────────────────────────────────────
from pathlib import Path
from typing import Literal

from beacon_attestation import BeaconAttestation, write_registry_entry

# ── Paths (configurable via env) ─────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
COVENANT_PATH     = Path(os.getenv("COVENANT_PATH", str(BASE_DIR / "covenant.vsm")))
DB_PATH           = Path(os.getenv("DB_PATH", str(BASE_DIR / "bastion.db")))
CA_PUBKEY_PATH    = Path(os.getenv("CA_PUBKEY_PATH", str(BASE_DIR / "ca.pubkey.hex")))
REGISTRY_PATH     = os.getenv("REGISTRY_PATH", str(BASE_DIR / "registry.jsonl"))

# ── Logging ──────────────────────────────────────────────────────────────────
_honeypot_log = logging.getLogger("vsf.honeypot")
_h = logging.FileHandler("/var/log/vsf-honeypot.log")
_h.setFormatter(logging.Formatter("%(asctime)s HONEYPOT %(message)s"))
_honeypot_log.addHandler(_h)
_honeypot_log.setLevel(logging.WARNING)

# ── Constants ────────────────────────────────────────────────────────────────
TARPIT_SECS   = 8
RATE_LIMIT    = 20
MONITOR_TOKEN = os.getenv("MONITOR_TOKEN", "")
_start_time   = datetime.now(timezone.utc)
_rate_blocked = 0


# ── Load CA pubkey + init attestation verifier ──────────────────────────────

def _load_ca_pubkey() -> str | None:
    """Load S5 CA root public key from ca.pubkey.hex."""
    if CA_PUBKEY_PATH.exists():
        with open(CA_PUBKEY_PATH) as f:
            return f.read().strip()
    return None

_ca_pubkey_hex = _load_ca_pubkey()

# The attestation verifier (initialized after covenant is read)
_attestation: BeaconAttestation | None = None

def _get_attestation() -> BeaconAttestation | None:
    global _attestation
    if _attestation is None and _ca_pubkey_hex:
        from beacon_attestation import BeaconAttestation
        # Get current covenant sha
        cov_sha = _canonical_hash()
        _attestation = BeaconAttestation(_ca_pubkey_hex, current_covenant_sha=cov_sha)
    return _attestation


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(docs_url=None, redoc_url=None)


# ── Database ─────────────────────────────────────────────────────────────────

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS beacons (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT NOT NULL,
            version   TEXT,
            platform  TEXT,
            run_id    TEXT,
            cov_hash  TEXT
        );
        CREATE TABLE IF NOT EXISTS nodes (
            run_id    TEXT PRIMARY KEY,
            last_seen TEXT,
            version   TEXT,
            platform  TEXT
        );
        CREATE TABLE IF NOT EXISTS honeypot_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT NOT NULL,
            ip        TEXT,
            method    TEXT,
            path      TEXT,
            ua        TEXT,
            headers   TEXT,
            body      TEXT
        );
    """)
    con.commit()
    con.close()

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

init_db()


# ── Rate limiting ────────────────────────────────────────────────────────────

_rate: dict[str, list] = {}

def is_rate_limited(ip: str) -> bool:
    now  = time.time()
    hits = _rate.setdefault(ip, [])
    _rate[ip] = [t for t in hits if now - t < 60]
    if len(_rate[ip]) >= RATE_LIMIT:
        return True
    _rate[ip].append(now)
    return False


# ── Covenant hash ────────────────────────────────────────────────────────────

_cov_mismatch_count = 0
_CANONICAL_HASH_CACHE: list[str | None] = [None]

def _canonical_hash() -> str | None:
    if _CANONICAL_HASH_CACHE[0] is None:
        for candidate in (BASE_DIR / "LICENSE", BASE_DIR.parent / "LICENSE"):
            if candidate.exists():
                for line in candidate.read_text().splitlines():
                    if line.startswith("Covenant SHA-256:"):
                        h = line.split(":", 1)[1].strip()
                        if len(h) == 64 and all(c in "0123456789abcdef" for c in h):
                            _CANONICAL_HASH_CACHE[0] = h
                        break
                break
    return _CANONICAL_HASH_CACHE[0]


# ── Models ───────────────────────────────────────────────────────────────────

class Beacon(BaseModel):
    version:       str
    platform:      Literal["linux", "mac", "windows"]
    run_id:        str
    covenant_hash: str
    timestamp:     str

    @field_validator("run_id", "covenant_hash")
    @classmethod
    def must_be_sha256(cls, v: str) -> str:
        if len(v) != 64 or not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError("must be SHA-256 hex")
        return v.lower()


class AttestedBeacon(Beacon):
    """Extended beacon payload with attestation protocol fields."""
    vsf_version:  str = ""
    watermark:    str = ""
    calibration:  str = ""
    cert:         dict = {}
    sig:          str = ""


class EncryptedBeacon(BaseModel):
    ek: str
    ct: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health(t: str = ""):
    if not MONITOR_TOKEN or t != MONITOR_TOKEN:
        raise HTTPException(status_code=404)
    with db() as con:
        beacons = con.execute("SELECT COUNT(*) FROM beacons").fetchone()[0]
        nodes   = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        threats = con.execute("SELECT COUNT(*) FROM honeypot_log").fetchone()[0]
    return {
        "status": "ok", "beacons": beacons, "nodes": nodes,
        "threats_logged": threats,
        "attestation_active": _ca_pubkey_hex is not None,
    }


@app.get("/registry")
def get_registry():
    """Return the current registry.jsonl contents (for monitoring)."""
    if not MONITOR_TOKEN or os.getenv("MONITOR_TOKEN", "") != MONITOR_TOKEN:
        raise HTTPException(status_code=404)
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH) as f:
            lines = f.readlines()
        return {"entries": [json.loads(l) for l in lines[-100:]]}  # last 100
    return {"entries": []}


@app.post("/api/v1/attested_check", status_code=202)
async def attested_beacon(data: AttestedBeacon, request: Request):
    """
    BEACON-ACTIVATION: Signed attestation endpoint.

    Accepts an AttestedBeacon with cert + signature.
    Verifies: cert chain → S5 CA root, signature over payload, covenant_sha.
    Writes TRUSTED/REJECTED to registry.jsonl.
    """
    if is_rate_limited(request.client.host):
        global _rate_blocked
        _rate_blocked += 1
        return JSONResponse({"error": "rate limited"}, status_code=429)

    attestation = _get_attestation()
    if attestation is None:
        return JSONResponse(
            {"status": "error", "reason": "attestation not configured (no CA pubkey)"},
            status_code=503,
        )

    # Build the verification payload
    payload = {
        "kernel_id": data.run_id,
        "vsf_version": data.vsf_version,
        "watermark": data.watermark,
        "covenant_sha": data.covenant_hash,
        "calibration": data.calibration,
        "cert": data.cert,
        "sig": data.sig,
    }

    # Verify
    result = attestation.verify(payload)

    # Write to registry
    entry = write_registry_entry(REGISTRY_PATH, result, remote_ip=request.client.host)

    # Track covenant mismatches
    canonical = _canonical_hash()
    if result["status"] == "rejected" and "covenant" in result.get("reason", ""):
        global _cov_mismatch_count
        _cov_mismatch_count += 1
        _honeypot_log.warning(
            f"ATTESTATION_REJECTED ip={request.client.host} node={data.run_id} "
            f"reason={result['reason']}"
        )

    # Also record to legacy DB for backward compat
    with db() as con:
        con.execute(
            "INSERT INTO beacons (ts,version,platform,run_id,cov_hash) VALUES (?,?,?,?,?)",
            (data.timestamp, data.vsf_version or data.version,
             data.platform, data.run_id, data.covenant_hash),
        )
        con.execute(
            """INSERT INTO nodes (run_id,last_seen,version,platform) VALUES (?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET
               last_seen=excluded.last_seen,
               version=excluded.version,
               platform=excluded.platform""",
            (data.run_id, data.timestamp, data.version, data.platform),
        )

    if result["status"] == "rejected":
        return JSONResponse(
            {"status": "rejected", "reason": result["reason"]},
            status_code=403,
        )
    return {"status": "trusted", "node_id": data.run_id}


@app.post("/api/v1/check", status_code=202)
async def legacy_beacon(data: EncryptedBeacon, request: Request):
    """
    Legacy beacon endpoint (RSA-2048-OAEP + AES-256-GCM hybrid encryption).
    PRESERVED for backward compatibility.
    For new deployments, use POST /api/v1/attested_check instead.
    """
    if is_rate_limited(request.client.host):
        global _rate_blocked
        _rate_blocked += 1
        return JSONResponse({"error": "rate limited"}, status_code=429)
    try:
        raw = decrypt_beacon(data.ek, data.ct)
        payload = Beacon(**raw)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid payload")
    canonical = _canonical_hash()
    if canonical and payload.covenant_hash != canonical:
        global _cov_mismatch_count
        _cov_mismatch_count += 1
        _honeypot_log.warning(
            f"COVENANT_MISMATCH ip={request.client.host} "
            f"received={payload.covenant_hash[:16]} expected={canonical[:16]}"
        )
    with db() as con:
        con.execute(
            "INSERT INTO beacons (ts,version,platform,run_id,cov_hash) VALUES (?,?,?,?,?)",
            (payload.timestamp, payload.version, payload.platform,
             payload.run_id, payload.covenant_hash),
        )
        con.execute(
            """INSERT INTO nodes (run_id,last_seen,version,platform) VALUES (?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET
               last_seen=excluded.last_seen,
               version=excluded.version,
               platform=excluded.platform""",
            (payload.run_id, payload.timestamp, payload.version, payload.platform),
        )
    return {"status": "accepted"}


# ── Pages (condensed — identical to original main.py) ────────────────────────

from vsf_style import VSF_CSS as _WIKI_CSS
_W = 93; _SEP = "=" * _W; _sep = "-" * _W

def _page(title: str, body: str, refresh: int = 0) -> str:
    rt = f'<meta http-equiv="refresh" content="{refresh}">\n' if refresh else ""
    return f'<!DOCTYPE html>\n<html lang="en"><head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n{rt}<title>{title}</title>\n<style>{_WIKI_CSS}</style>\n</head><body><pre>{body}</pre></body></html>'

# ── Honeypot ─────────────────────────────────────────────────────────────────

HONEY_PATHS = {
    "/admin", "/admin/login", "/wp-admin", "/wp-login.php",
    "/.env", "/config.json", "/.git/config", "/config",
    "/shell", "/cmd", "/exec", "/phpmyadmin",
    "/api/v1/admin", "/api/admin", "/login",
    "/manager", "/console", "/setup", "/install", "/dashboard",
}

DECOY = {"status": "ok", "node": "vsf", "auth": "required"}

@app.middleware("http")
async def honeypot(request: Request, call_next):
    path = request.url.path
    if (path in HONEY_PATHS or
            path.endswith((".php", ".asp", ".aspx", ".cgi", ".bak", ".sql"))):
        body = (await request.body())[:512].decode("utf-8", errors="replace")
        with db() as con:
            con.execute(
                "INSERT INTO honeypot_log (ts,ip,method,path,ua,headers,body)"
                " VALUES (?,?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 request.client.host, request.method, path,
                 request.headers.get("user-agent", ""),
                 json.dumps(dict(request.headers)), body),
            )
        _honeypot_log.warning("%s %s %s", request.client.host, request.method, path)
        await asyncio.sleep(TARPIT_SECS)
        return JSONResponse(DECOY, status_code=200)
    return await call_next(request)


# ── Beacon crypto (preserved from original) ──────────────────────────────────

_DEFAULT_KEY = Path(os.getenv("HOME", "~")) / ".vsf-bastion" / "private.pem"

def _load_private_key():
    from cryptography.hazmat.primitives import serialization
    key_file = Path(os.getenv("BASTION_PRIVATE_KEY_FILE", str(_DEFAULT_KEY)))
    if key_file.exists():
        pem = key_file.read_bytes()
        return serialization.load_pem_private_key(pem, password=None)
    return None

_privkey = _load_private_key()

def decrypt_beacon(ek_b64: str, ct_b64: str) -> dict:
    if _privkey is None:
        raise ValueError("no private key")
    import base64
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    ek = base64.b64decode(ek_b64)
    ct = base64.b64decode(ct_b64)
    aes_key = _privkey.decrypt(ek, asym_padding.OAEP(
        mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(), label=None,
    ))
    nonce, body = ct[:12], ct[12:]
    plaintext = AESGCM(aes_key).decrypt(nonce, body, None)
    return json.loads(plaintext)


# ── 404 ──────────────────────────────────────────────────────────────────────

from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    if exc.status_code == 404:
        return HTMLResponse(_page("404  ::  vsf.u2738.org", "<h1>404</h1><p>Not found.</p>"), status_code=404)
    return HTMLResponse(f"<pre>{exc.status_code}</pre>", status_code=exc.status_code)
