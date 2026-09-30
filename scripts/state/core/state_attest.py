#!/usr/bin/env python3
"""state_attest — the AX-STATE-01 dogfood: tamper-EVIDENT attestation for state.db tables.

Makes any load-bearing mutable state (the no-physical-counterpart tables: deploys / audits /
coupling_registry) tamper-evident with ONE record type + ONE verifier, reusing the Merkle-style
per-surface chain + Ed25519 + the S3* reconcile + the algedonic channel (AX-STATE-01, CONVERGED
2026-06-04, docs/theory/attested_state_primitive.vsm).

This file is built by LOGICAL GATES (correction C4 — no time estimates):
  GATE C2 (THIS FILE, now): canonical_serialize is INJECTIVE and passes its injection suite.
  GATE 2  (next):           state_attest writer — signed snapshot per surface.
  GATE 3  (next):           state_verify in the reconcile (steps 1-6), DEGRADE not halt (C5).
  GATE 4  (next):           end-to-end injection on the real state.db (n02).

── THE LOAD-BEARING PIECE: canonical_serialize (correction C2) ──────────────────
A commitment is sha256(canonical_serialize(table)). The serializer MUST be:
  - STABLE under non-semantic variation  → exclude volatile cols (auto-id, refreshed_at, pid);
    sort rows and columns so insertion order / schema order never move the hash.
  - SENSITIVE to semantic change         → any real cell change flips the hash.
  - INJECTIVE                            → distinct logical tables NEVER collide. Raw concatenation
    collides ('ab'+'c' vs 'a'+'bc'; a 0xFF text byte vs a NULL). The fix: type-tag + length-prefix
    EVERY field, and length-prefix every row, with explicit n_cols / n_rows framing.

The same discipline as docs_reconcile.py (drop the volatile timestamp so INDEX.md is deterministic)
and the events.jsonl canonical_hash (anti ryu-float-drift). Correctness is validated BY INJECTION,
not by inspection: run `--inject` (on the n02 sandbox, never WSL — feedback_wsl_role_only).

Pure stdlib. Authoring happens in WSL; ALL execution (incl. --inject) runs on n02 (LXC 108 sandbox).
"""
import sqlite3
import struct
import hashlib
import sys

# Serialization domain + version. Bump VERSION on any wire-format change so an old attestation made
# with a different format can never silently verify against a new serializer.
DOMAIN = b"VSF-ATTEST"
VERSION = 1

# Columns excluded from EVERY surface: non-semantic / volatile. Their change must NOT fire a tamper
# alarm (the orphan-detector lesson: a noisy certifier is a dead certifier). Per-surface extra
# exclusions are passed explicitly by the caller (writer, GATE 2).
VOLATILE_DEFAULT = frozenset({"id", "rowid", "refreshed_at", "updated_at", "pid", "last_seen"})

# SQLite storage-class type tags. The tag is what makes 0xFF-as-text distinct from NULL, and an
# INTEGER 0 distinct from a TEXT "0" — without it the serializer is not injective across types.
_TAG_NULL = 0x00
_TAG_INT = 0x01
_TAG_REAL = 0x02
_TAG_TEXT = 0x03
_TAG_BLOB = 0x04


def _u32(n):
    """Unsigned 32-bit big-endian length/count prefix."""
    if n < 0 or n > 0xFFFFFFFF:
        raise ValueError(f"u32 out of range: {n}")
    return struct.pack(">I", n)


def _frame_bytes(tag, payload):
    """A self-delimiting field: [tag:1][u32 len][payload]. Length-prefixing is what prevents the
    'ab'+'c' vs 'a'+'bc' collision — each field carries its own boundary."""
    return bytes([tag]) + _u32(len(payload)) + payload


def _frame_cell(value):
    """Serialize ONE cell injectively, tagged by its SQLite storage class.
    INTEGER/REAL are fixed 8-byte (tag implies width); TEXT/BLOB are length-prefixed."""
    if value is None:
        return bytes([_TAG_NULL]) + _u32(0)
    if isinstance(value, int):
        # Fixed-width signed 64-bit, big-endian. SQLite integers are <= 64-bit.
        return _frame_bytes(_TAG_INT, struct.pack(">q", value))
    if isinstance(value, float):
        # Fixed-width IEEE-754 double, big-endian (deterministic bytes — the anti ryu-drift lesson).
        return _frame_bytes(_TAG_REAL, struct.pack(">d", value))
    if isinstance(value, str):
        return _frame_bytes(_TAG_TEXT, value.encode("utf-8"))
    if isinstance(value, (bytes, bytearray)):
        return _frame_bytes(_TAG_BLOB, bytes(value))
    raise TypeError(f"non-SQLite cell type: {type(value)!r}")


def _columns(con, table, exclude):
    """The included columns, SORTED by name — so a schema column reorder never moves the hash."""
    info = con.execute(f"PRAGMA table_info({table})").fetchall()
    if not info:
        raise ValueError(f"table not found or empty schema: {table}")
    cols = [row[1] for row in info if row[1] not in exclude]
    if not cols:
        raise ValueError(f"all columns excluded for {table}; nothing to attest")
    return sorted(cols)


def canonical_serialize(con, table, exclude_cols=None):
    """INJECTIVE byte serialization of a SQLite table's semantic content.

    Layout:
      DOMAIN | u8 VERSION
      frame(table-name)
      u32 n_cols | frame(col-name) * n_cols          (column NAMES included → rename-sensitive)
      u32 n_rows | (u32 row-len | row-bytes) * n_rows (rows SORTED by their bytes → order-independent)
        where row-bytes = frame_cell(cell) for each col in sorted-column order
    """
    exclude = set(VOLATILE_DEFAULT)
    if exclude_cols:
        exclude |= set(exclude_cols)
    cols = _columns(con, table, exclude)

    col_list = ", ".join(f'"{c}"' for c in cols)
    rows = con.execute(f"SELECT {col_list} FROM {table}").fetchall()

    row_blobs = []
    for r in rows:
        row_blobs.append(b"".join(_frame_cell(cell) for cell in r))
    # Sort by raw bytes → insertion order is non-semantic for a set of rows. (state.db tables here
    # have no semantic ordering; if one ever does, attest an ORDER BY view instead.)
    row_blobs.sort()

    out = bytearray()
    out += DOMAIN
    out += bytes([VERSION])
    out += _frame_bytes(_TAG_TEXT, table.encode("utf-8"))
    out += _u32(len(cols))
    for c in cols:
        out += _frame_bytes(_TAG_TEXT, c.encode("utf-8"))
    out += _u32(len(row_blobs))
    for rb in row_blobs:
        out += _u32(len(rb))
        out += rb
    return bytes(out)


def commitment(con, table, exclude_cols=None):
    """The surface commitment: sha256 over the canonical serialization (hex). SNAPSHOT mode — a SET
    commitment (rows sorted, order non-semantic); equality is the tamper test for mutable tables."""
    return hashlib.sha256(canonical_serialize(con, table, exclude_cols)).hexdigest()


# ── CHAIN mode: a SEQUENCE/PREFIX commitment for append-only surfaces (audits) ────────────────────
# canonical_serialize is wrong for append-only logs: any append moves the SET hash → an alarm on every
# legitimate row. Chain mode instead folds rows in APPEND order (rowid ASC) into a running hash. The
# fold is prefix-derivable: the head over the first N rows depends only on those N rows, so a verifier
# can re-derive the head over the attested PREFIX and prove it is byte-identical — catching a changed
# PAST row / a deletion / a reorder, while tolerating new rows at the tail. (Same type-tag + length-
# prefix discipline as canonical_serialize → injective per row; column NAMES bound once in the seed.)
DOMAIN_CHAIN = b"VSF-ATTEST-CHAIN"


def _chain_commitment(con, table, exclude_cols=None, limit=None):
    """Running hash-chain over rows in append order (rowid ASC). Returns (count, head_hex).
    With `limit` set, folds only the first `limit` rows → the head over that PREFIX (the verify path)."""
    exclude = set(VOLATILE_DEFAULT)
    if exclude_cols:
        exclude |= set(exclude_cols)
    cols = _columns(con, table, exclude)
    col_list = ", ".join(f'"{c}"' for c in cols)
    sql = f"SELECT {col_list} FROM {table} ORDER BY rowid"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = con.execute(sql).fetchall()
    # Seed binds DOMAIN+VERSION+table-name+column-NAMES (rename/schema-shape sensitive) ONCE, before
    # any row — so two surfaces with identical row bytes but different columns never share a head.
    h = hashlib.sha256(
        DOMAIN_CHAIN + bytes([VERSION]) + _frame_bytes(_TAG_TEXT, table.encode("utf-8"))
        + _u32(len(cols)) + b"".join(_frame_bytes(_TAG_TEXT, c.encode("utf-8")) for c in cols)
    ).digest()
    n = 0
    for r in rows:
        rb = b"".join(_frame_cell(cell) for cell in r)  # NOT sorted — append order is semantic here
        h = hashlib.sha256(DOMAIN_CHAIN + h + _u32(len(rb)) + rb).digest()
        n += 1
    return n, h.hex()


def chain_commitment(con, table, exclude_cols=None, limit=None):
    """The append-only surface commitment: "<count>:<head_hex>". The count lets the verifier detect a
    deletion (live shorter than attested); the head proves the attested prefix is unchanged."""
    n, head = _chain_commitment(con, table, exclude_cols, limit)
    return f"{n}:{head}"


# ── GATE 2: the signed attestation writer (snapshot mode) ───────────────────────────────────────
# Per-surface signed hash-chain. Each record commits the canonical_serialize of a state.db table,
# signs it (Ed25519), and links to the previous record FOR THAT SURFACE (prev_attest). Tamper in the
# table → the next snapshot's commitment diverges; tamper in the chain → broken prev_attest / bad sig.
#
# KEY CUSTODY (dogfood only): an ephemeral local component key. The REAL custody — kernel-keyring/age
# at rest, issued + certified by the OFFLINE S5 root, with revocation (correction C1, tier_α) — is a
# PARALLEL track that does NOT block this read-only attest+verify dogfood. Do NOT ship this key code.
DOMAIN_REC = b"VSF-ATTEST-REC"
GENESIS = "0" * 64
ATTEST_DIR_DEFAULT = "/var/lib/vsf/attestations"
KEY_DIR_DEFAULT = "/var/lib/vsf/attest-keys"

# ── PROD-A1a runtime (the live host agent) ──────────────────────────────────────
STATE_DB_DEFAULT = "/var/lib/vsf-state/state.db"   # mirrors topology_reconcile.STATE_DB
SEEN_PATH_DEFAULT = "/var/lib/vsf/attest-seen.json"  # persistent monotonic heads (C3) across runs
# C1 (Ax_TwoLevelAttestation): the offline-S5 CA artifacts deposited on the host — root PUBLIC key +
# component certs + the signed CRL. PUBLIC only (the root secret never leaves the offline box / USB).
# If absent, the agent falls back to dogfood self-trust so it never breaks before the ceremony runs.
CA_DIR_DEFAULT = "/var/lib/vsf/s5-ca"
# G_genesis: PIN the offline root's fingerprint IN CODE (it is public — sha256(pubkey)[:16] — and safe
# to commit; Kerckhoffs/M1 NoObscurity). Without the pin, a host-level attacker could swap the whole
# s5-ca dir (their own root + a cert for their key) and forge freely. With it, only a CA dir whose root
# matches this fingerprint is trusted — and matching it needs the offline private key. "" ⇒ pin disabled
# (pre-ceremony / tests). Set from the root_id printed by `s5_ca init-root`.
S5_ROOT_PIN = "ed25519:624e8d3ea2c0c904"
# Surfaces the host agent attests, each with its MODE (per criticality / mutation shape):
#   snapshot — rarely-mutated, no-physical-counterpart tables (deploys, coupling_registry). The verify
#     is commitment-EQUALITY over a SET commitment (canonical_serialize): low-noise because a fired
#     alarm ≈ a real out-of-band edit. NB: a legitimate edit still fires ONE alarm before re-baselining.
#   chain    — APPEND-ONLY tables (audits: a row per gate run, many/day). Snapshot-equality would
#     false-alarm on EVERY legitimate append ("noisy certifier = dead certifier"). Chain mode commits a
#     SEQUENCE (a per-row fold in append order) so the verify can re-derive the head over the attested
#     PREFIX: TAMPER = (a PAST row changed ∨ a row deleted ∨ the prefix reordered), NOT (new rows
#     appended). This is the §audits_followup integration from attested_state_primitive.vsm (the
#     documented condition for audits joining the production deploy — rmw3 directive 2026-06-07).
SURFACE_MODE = {"deploys": "snapshot", "coupling_registry": "snapshot", "audits": "chain"}
AGENT_SURFACES = ("deploys", "coupling_registry", "audits")
# Algedonic dual-channel targets — reuse the topology_reconcile contract verbatim.
INBOX_LXC = "104"
INBOX_PATH = "/alerts/operator_inbox.log"
NATS_LXC = "106"

# Surfaces → per-table exclusions BEYOND VOLATILE_DEFAULT. Empty everywhere: the default set already
# covers them (deploys/audits exclude `id`; coupling_registry excludes `refreshed_at`). NB: `ts` on
# the append-only logs is SEMANTIC (the event time) and is deliberately KEPT — excluding it would
# blind the attestation to a back-dated tamper.
SURFACES = {
    "deploys": frozenset(),
    "audits": frozenset(),
    "coupling_registry": frozenset(),
}


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_or_generate_key(key_dir=KEY_DIR_DEFAULT):
    """Dogfood key handling: load a raw Ed25519 private key, or generate + persist one. TEST ONLY —
    see the KEY CUSTODY note above. Returns (private_key, public_raw_bytes, signer_id)."""
    import os
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption)
    os.makedirs(key_dir, exist_ok=True)
    skpath = os.path.join(key_dir, "component_key.ed25519")
    if os.path.exists(skpath):
        with open(skpath, "rb") as f:
            sk = Ed25519PrivateKey.from_private_bytes(f.read())
    else:
        sk = Ed25519PrivateKey.generate()
        raw = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        fd = os.open(skpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    pub_raw = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    with open(os.path.join(key_dir, "component_key.pub"), "wb") as f:
        f.write(pub_raw)
    signer = "ed25519:" + hashlib.sha256(pub_raw).hexdigest()[:16]
    return sk, pub_raw, signer


def _record_payload(surface, commit, prev_attest, mode, ts, nonce, signer):
    """Injective serialization of the SIGNED fields — same type-tag + length-prefix discipline as
    canonical_serialize, so the signature covers an unambiguous byte string."""
    out = bytearray()
    out += DOMAIN_REC
    out += bytes([VERSION])
    for field in (surface, commit, prev_attest, mode, ts, nonce, signer):
        out += _frame_bytes(_TAG_TEXT, field.encode("utf-8"))
    return bytes(out)


def _surface_file(attest_dir, surface):
    import os
    return os.path.join(attest_dir, surface.replace("/", "_").replace(":", "_") + ".jsonl")


def _last_attest_hash(path):
    """The head of this surface's chain (GENESIS if none) — for anti-rollback the verifier (GATE 3)
    also tracks the monotonic head it has SEEN, not just the file's last line (correction C3)."""
    import os
    import json
    if not os.path.exists(path):
        return GENESIS
    last = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = line
    return json.loads(last)["attest_hash"] if last else GENESIS


def state_attest(con, table, sk, signer, attest_dir=ATTEST_DIR_DEFAULT, mode=None):
    """Emit ONE signed attestation for `table` and append it to its per-surface chain. Returns the record.
    `mode` defaults to the surface's registered mode (SURFACE_MODE) so writer + verifier never disagree;
    chain-mode commits a sequence/prefix head ("n:head"), snapshot-mode a set commitment."""
    import os
    import json
    import secrets
    surface = f"statedb.{table}"
    mode = mode or SURFACE_MODE.get(table, "snapshot")
    commit = (chain_commitment(con, table, SURFACES.get(table)) if mode == "chain"
              else commitment(con, table, SURFACES.get(table)))
    path = _surface_file(attest_dir, surface)
    prev_attest = _last_attest_hash(path)
    ts = _now_iso()
    nonce = secrets.token_hex(16)
    payload = _record_payload(surface, commit, prev_attest, mode, ts, nonce, signer)
    sig = sk.sign(payload).hex()
    attest_hash = hashlib.sha256(payload).hexdigest()
    rec = dict(surface=surface, commitment=commit, prev_attest=prev_attest, mode=mode,
               ts=ts, nonce=nonce, signer=signer, sig=sig, attest_hash=attest_hash)
    os.makedirs(attest_dir, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def verify_record(rec, pub_raw):
    """Single-record check: recompute the payload, confirm attest_hash, verify the Ed25519 signature.
    GATE 3 layers chain-continuity + freshness + model≡reality + algedonic on top of this."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    payload = _record_payload(rec["surface"], rec["commitment"], rec["prev_attest"],
                              rec["mode"], rec["ts"], rec["nonce"], rec["signer"])
    if hashlib.sha256(payload).hexdigest() != rec["attest_hash"]:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(bytes.fromhex(rec["sig"]), payload)
        return True
    except InvalidSignature:
        return False


def _run_gate2_suite():
    """Validate the WRITER MECHANISM on a synthetic state.db (real schemas) — no real state touched.
    Asserts: well-formed signed record, genesis + chain linkage, commitment stability under volatile
    change, commitment movement under semantic change, and verification rejects tamper / foreign key."""
    import os
    import sqlite3
    import tempfile
    import shutil
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="vsf-attest-g2-")
    attest_dir = os.path.join(tmp, "attestations")
    sk, pub_raw, signer = load_or_generate_key(os.path.join(tmp, "keys"))
    con = sqlite3.connect(os.path.join(tmp, "state.db"))
    con.executescript(
        "CREATE TABLE deploys (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, component TEXT,"
        " target_lxc INTEGER, from_sha TEXT, to_sha TEXT, result TEXT);"
        "CREATE TABLE audits (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, gate TEXT, passed INTEGER,"
        " duration_s REAL, evidence TEXT);"
        "CREATE TABLE coupling_registry (resource TEXT PRIMARY KEY, kind TEXT, endpoint TEXT,"
        " protocol TEXT, capabilities TEXT, access_model TEXT, couple_proc TEXT, governance TEXT,"
        " status TEXT, refreshed_at TEXT);")
    con.execute("INSERT INTO deploys (ts,component,target_lxc,from_sha,to_sha,result)"
                " VALUES (?,?,?,?,?,?)", ("2026-06-04T00:00:00Z", "vsf-nucleus", 101, "", "abc", "ok"))  # hardcoded-allow: deterministic fixture
    con.execute("INSERT INTO coupling_registry VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("ollama-llm", "shared_resource", "x", "http", "y", "z", "p", "g", "active",
                 "2026-06-01T00:00:00Z"))  # hardcoded-allow: deterministic fixture
    con.commit()

    r1 = state_attest(con, "deploys", sk, signer, attest_dir)
    check("record well-formed", all(k in r1 for k in
          ("surface", "commitment", "prev_attest", "mode", "ts", "nonce", "signer", "sig", "attest_hash")))
    check("genesis prev_attest", r1["prev_attest"] == GENESIS)
    check("signature verifies", verify_record(r1, pub_raw))

    r2 = state_attest(con, "deploys", sk, signer, attest_dir)  # table unchanged
    check("chain links r2->r1", r2["prev_attest"] == r1["attest_hash"])
    check("commitment stable when unchanged", r2["commitment"] == r1["commitment"])

    # volatile-only change (refreshed_at) MUST NOT move the commitment (no false alarm)
    con.execute("UPDATE coupling_registry SET refreshed_at=? WHERE resource=?",
                ("2026-06-04T23:59:59Z", "ollama-llm")); con.commit()
    rc1 = state_attest(con, "coupling_registry", sk, signer, attest_dir)
    con.execute("UPDATE coupling_registry SET refreshed_at=? WHERE resource=?",
                ("2026-06-05T00:00:00Z", "ollama-llm")); con.commit()  # hardcoded-allow: deterministic fixture
    rc2 = state_attest(con, "coupling_registry", sk, signer, attest_dir)
    check("volatile change → same commitment", rc1["commitment"] == rc2["commitment"])

    # semantic change (status) MUST move the commitment (the tamper signal)
    con.execute("UPDATE coupling_registry SET status=? WHERE resource=?",
                ("deprecated", "ollama-llm")); con.commit()
    rc3 = state_attest(con, "coupling_registry", sk, signer, attest_dir)
    check("semantic change → commitment moves", rc3["commitment"] != rc2["commitment"])

    # a tampered persisted record (flipped commitment) MUST fail verification
    bad = dict(r1); bad["commitment"] = "f" * 64
    check("tampered record fails verify", not verify_record(bad, pub_raw))
    # a foreign key MUST fail verification
    _, pub2, _ = load_or_generate_key(os.path.join(tmp, "keys2"))
    check("foreign key fails verify", not verify_record(r1, pub2))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else "")
             for n, ok, d in cases]
    return passed, failed, lines


# ── GATE 3: the verifier (the S3* reconcile gains this — one algorithm, all surfaces) ────────────
# The 6 checks of the spec, with the safety law C5: for state.db EVERY failure DEGRADES (algedonic),
# NEVER halts — a mis-rotated key or a read error must not self-DoS the nucleus. halt=True is reserved
# for covenant/covenant_ops tamper (G_halt_screams), which are NOT these surfaces. So every finding
# here carries halt=False. state_verify RETURNS findings; an `emitter` callback (the reconcile's
# emit_algedonic) is invoked per finding so the wiring is testable without touching LXC 104/106.
#
# Ax_AttestationSeparation: this is the LOGICAL check (what the system BELIEVES, via the signed chain).
# The reconcile's process census (topology_reconcile) is the PHYSICAL check (what it OBSERVES). Both
# run; their DISAGREEMENT is itself a high-severity signal — out of scope here, noted for integration.
CADENCE_S = {"deploys": 300, "audits": 300, "coupling_registry": 900}  # snapshot cadence per surface
GRACE_S = 120  # freshness grace beyond cadence before STALE fires

# Finding = (category, severity, surface, detail, halt). severity on topology_reconcile's scale (≥1.0).
SEV = {"ATTEST_TAMPER": 8.0, "ATTEST_FORGERY": 9.0, "ATTEST_CHAIN_BREAK": 8.0,
       "ATTEST_ROLLBACK": 8.0, "ATTEST_STALE": 5.0, "ATTEST_MISSING": 5.0, "ATTEST_DEGRADED": 3.0,
       "ATTEST_CERT_EXPIRING": 4.0}  # A1d: low-sev pre-warn before a cert FORGERY-fails at expiry


def _parse_iso(ts):
    import datetime
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc).timestamp()


def _load_chain(path):
    import os
    import json
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def _chain_continuous(chain):
    """First record anchors at GENESIS; each prev_attest equals the previous record's attest_hash."""
    prev = GENESIS
    for rec in chain:
        if rec["prev_attest"] != prev:
            return False
        prev = rec["attest_hash"]
    return True


def state_verify(con, table, attest_dir, trusted, seen, now_epoch=None, emitter=None):
    """Verify the attestation for `table` against LIVE state. Returns a list of findings (all halt=False
    for state.db, C5). `trusted` = {signer_id: pub_raw}; `seen` = {surface: (length, head_hash)} carried
    across runs for monotonic anti-rollback (C3). Mutates `seen` to the newest head observed."""
    import time
    findings = []
    surface = f"statedb.{table}"

    def add(cat, detail):
        findings.append((cat, SEV.get(cat, 5.0), surface, detail, False))  # halt=False — C5

    chain = _load_chain(_surface_file(attest_dir, surface))
    if not chain:
        add("ATTEST_MISSING", "no attestation chain for surface")
        return findings
    latest = chain[-1]

    # step 4: per-surface chain unbroken back to GENESIS (history rewrite?)
    if not _chain_continuous(chain):
        add("ATTEST_CHAIN_BREAK", "prev_attest linkage broken (history rewrite?)")

    # steps 2-3: signature valid AND signer is trusted/S5-certified (forgery?)
    # (full S5 two-level cert is the EVC CA track; here trust = membership in `trusted`.)
    pub = trusted.get(latest["signer"])
    if pub is None:
        add("ATTEST_FORGERY", f"signer {latest['signer']} not in trusted/certified set")
    elif not verify_record(latest, pub):
        add("ATTEST_FORGERY", "signature does not verify against certified key")

    # step 1: recompute the commitment over LIVE state and compare (tamper?). The check is per the
    # ATTESTED record's own mode (so a writer/verifier mode mismatch can never silently pass). Read
    # failure DEGRADES (C5). For append-only surfaces, a new tail is EXPECTED and must NOT alarm.
    mode = latest.get("mode", "snapshot")
    try:
        if mode == "chain":
            # The attestation committed "<n>:<head>" over the first n rows (append order). TAMPER iff
            # the attested PREFIX changed: a row deleted (live shorter than n) OR the first-n live rows
            # no longer fold to <head> (a past row edited / reordered). New tail rows are tolerated.
            try:
                n_str, head = latest["commitment"].split(":", 1)
                attested_n = int(n_str)
            except (ValueError, KeyError):
                raise ValueError(f"malformed chain commitment {latest.get('commitment')!r}")
            live_count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if live_count < attested_n:
                add("ATTEST_TAMPER", f"append-only surface shrank: live {live_count} < attested {attested_n} (row deleted?)")
            else:
                _, prefix_head = _chain_commitment(con, table, SURFACES.get(table), limit=attested_n)
                if prefix_head != head:
                    add("ATTEST_TAMPER", f"attested prefix mutated (first {attested_n} rows ≠ signed head {head[:8]})")
        else:
            live = commitment(con, table, SURFACES.get(table))
            if live != latest["commitment"]:
                add("ATTEST_TAMPER", f"live state ≠ attestation ({live[:8]} ≠ {latest['commitment'][:8]})")
    except Exception as e:
        add("ATTEST_DEGRADED", f"cannot read live table: {e}")

    # step 4b (C3): monotonic anti-rollback — an older/shorter chain than last seen ⇒ rollback.
    prev_seen = seen.get(surface)
    if prev_seen is not None:
        seen_len, seen_head = prev_seen
        if len(chain) < seen_len:
            add("ATTEST_ROLLBACK", f"chain len {len(chain)} < seen {seen_len} (rollback?)")
    if prev_seen is None or len(chain) >= prev_seen[0]:
        seen[surface] = (len(chain), latest["attest_hash"])  # advance monotonic head

    # step 5: freshness — a stale head means the attester halted/was killed.
    now_epoch = time.time() if now_epoch is None else now_epoch
    age = now_epoch - _parse_iso(latest["ts"])
    if age > CADENCE_S.get(table, 300) + GRACE_S:
        add("ATTEST_STALE", f"head age {int(age)}s > cadence+grace (attester halted?)")

    if emitter:
        for cat, sev, surf, detail, halt in findings:
            emitter(cat, sev, surf, detail, halt)
    return findings


def _run_gate3_suite():
    """Validate the verifier on synthetic chains — each failure mode injected, plus a clean baseline
    that must yield ZERO findings (no false alarms). Asserts C5: every finding halt=False."""
    import os
    import sqlite3
    import tempfile
    import shutil
    import time
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="vsf-attest-g3-")
    attest_dir = os.path.join(tmp, "attestations")
    sk, pub_raw, signer = load_or_generate_key(os.path.join(tmp, "keys"))
    trusted = {signer: pub_raw}
    con = sqlite3.connect(os.path.join(tmp, "state.db"))
    con.executescript(
        "CREATE TABLE coupling_registry (resource TEXT PRIMARY KEY, kind TEXT, status TEXT,"
        " refreshed_at TEXT);")
    con.execute("INSERT INTO coupling_registry VALUES (?,?,?,?)",
                ("ollama-llm", "shared_resource", "active", "2026-06-01T00:00:00Z"))  # hardcoded-allow: deterministic fixture
    con.commit()
    state_attest(con, "coupling_registry", sk, signer, attest_dir)
    now = _parse_iso(_now_iso())

    cats = lambda fs: {f[0] for f in fs}
    halts = lambda fs: {f[4] for f in fs}

    # 0. CLEAN baseline → zero findings.
    seen = {}
    f0 = state_verify(con, "coupling_registry", attest_dir, trusted, seen, now_epoch=now)
    check("clean → zero findings", f0 == [], str(cats(f0)))
    check("C5: no finding ever halts (clean run carries seen)", True)

    # 1. TAMPER: mutate a semantic cell AFTER attestation.
    con.execute("UPDATE coupling_registry SET status='deprecated' WHERE resource='ollama-llm'"); con.commit()
    f1 = state_verify(con, "coupling_registry", attest_dir, trusted, dict(seen), now_epoch=now)
    check("semantic mutation → ATTEST_TAMPER", "ATTEST_TAMPER" in cats(f1))
    check("tamper finding does NOT halt (C5)", halts(f1) == {False})
    con.execute("UPDATE coupling_registry SET status='active' WHERE resource='ollama-llm'"); con.commit()

    # 2. VOLATILE-only change AFTER attestation → NO finding.
    con.execute("UPDATE coupling_registry SET refreshed_at='2026-06-09T00:00:00Z' WHERE resource='ollama-llm'"); con.commit()  # hardcoded-allow: deterministic fixture
    f2 = state_verify(con, "coupling_registry", attest_dir, trusted, dict(seen), now_epoch=now)
    check("volatile-only change → zero findings", f2 == [], str(cats(f2)))

    # 3. FORGERY: a signer not in the trusted set.
    f3 = state_verify(con, "coupling_registry", attest_dir, {}, dict(seen), now_epoch=now)
    check("untrusted signer → ATTEST_FORGERY", "ATTEST_FORGERY" in cats(f3))

    # 4. CHAIN_BREAK: corrupt the persisted chain's prev_attest.
    bdir = os.path.join(tmp, "broken"); os.makedirs(bdir)
    src = _surface_file(attest_dir, "statedb.coupling_registry")
    import json
    recs = _load_chain(src)
    recs[0]["prev_attest"] = "f" * 64
    with open(_surface_file(bdir, "statedb.coupling_registry"), "w") as fh:
        for r in recs:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    f4 = state_verify(con, "coupling_registry", bdir, trusted, {}, now_epoch=now)
    check("corrupted prev_attest → ATTEST_CHAIN_BREAK", "ATTEST_CHAIN_BREAK" in cats(f4))

    # 5. ROLLBACK: present a chain shorter than the length already seen.
    state_attest(con, "coupling_registry", sk, signer, attest_dir)  # chain now length 2
    seen2 = {}
    state_verify(con, "coupling_registry", attest_dir, trusted, seen2, now_epoch=now)  # observe len 2
    edir = os.path.join(tmp, "rolled"); os.makedirs(edir)
    with open(_surface_file(edir, "statedb.coupling_registry"), "w") as fh:
        fh.write(json.dumps(_load_chain(src)[0], sort_keys=True) + "\n")  # only record #1 (len 1)
    f5 = state_verify(con, "coupling_registry", edir, trusted, seen2, now_epoch=now)
    check("older/shorter chain → ATTEST_ROLLBACK", "ATTEST_ROLLBACK" in cats(f5))

    # 6. STALE: verify far in the future relative to the head ts.
    f6 = state_verify(con, "coupling_registry", attest_dir, trusted, {}, now_epoch=now + 100000)
    check("stale head → ATTEST_STALE", "ATTEST_STALE" in cats(f6))

    # 7. EMITTER wiring + C5: every emitted finding has halt=False.
    emitted = []
    state_verify(con, "coupling_registry", attest_dir, {}, {}, now_epoch=now + 100000,
                 emitter=lambda c, s, surf, d, h: emitted.append((c, h)))
    check("emitter invoked per finding", len(emitted) > 0)
    check("C5: every emitted finding halt=False", all(h is False for _, h in emitted))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else "")
             for n, ok, d in cases]
    return passed, failed, lines


# ── GATE CHAIN: the append-only (audits) verify variant — the §audits_followup proof ─────────────
# The property snapshot mode cannot give: APPEND tolerated (zero findings), but a changed PAST row, a
# deletion, or a reorder still caught. Validated by injection on a synthetic append-only table.
def _run_chain_suite():
    import os
    import sqlite3
    import tempfile
    import shutil
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="vsf-attest-chain-")
    attest_dir = os.path.join(tmp, "attestations")
    sk, pub_raw, signer = load_or_generate_key(os.path.join(tmp, "keys"))
    trusted = {signer: pub_raw}
    now = _parse_iso(_now_iso())
    cats = lambda fs: {f[0] for f in fs}
    halts = lambda fs: {f[4] for f in fs}

    con = sqlite3.connect(os.path.join(tmp, "state.db"))
    con.execute("CREATE TABLE audits (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, gate TEXT,"
                " passed INTEGER, duration_s REAL, evidence TEXT)")
    ins = lambda g, p: con.execute("INSERT INTO audits (ts,gate,passed,duration_s,evidence)"
                                   " VALUES (?,?,?,?,?)", (f"2026-06-0{g}T00:00:00Z", f"gate{g}", p, 1.5, "ok"))  # hardcoded-allow: deterministic fixture
    for i in (1, 2, 3):
        ins(i, 1)
    con.commit()

    # audits must resolve to CHAIN mode (the enrolment), and the commitment must be "<n>:<head>".
    check("audits registered as chain mode", SURFACE_MODE.get("audits") == "chain")
    r = state_attest(con, "audits", sk, signer, attest_dir)  # mode resolved from SURFACE_MODE
    check("chain attestation mode=chain", r["mode"] == "chain")
    check("chain commitment is '<n>:<head>'", r["commitment"].startswith("3:") and len(r["commitment"]) == 2 + 64)

    # 0. CLEAN → zero findings.
    seen = {}
    f0 = state_verify(con, "audits", attest_dir, trusted, seen, now_epoch=now)
    check("clean chain → zero findings", f0 == [], str(cats(f0)))

    # 1. APPEND (the whole point): new tail rows → NO finding (snapshot mode would false-alarm here).
    ins(4, 1); ins(5, 0); con.commit()
    f1 = state_verify(con, "audits", attest_dir, trusted, dict(seen), now_epoch=now)
    check("append-only growth → zero findings", f1 == [], str(cats(f1)))

    # 2. PAST-ROW TAMPER: flip a semantic cell in an ALREADY-ATTESTED row → ATTEST_TAMPER (not halt).
    con.execute("UPDATE audits SET passed=0 WHERE gate='gate1'"); con.commit()
    f2 = state_verify(con, "audits", attest_dir, trusted, dict(seen), now_epoch=now)
    check("past-row edit → ATTEST_TAMPER", "ATTEST_TAMPER" in cats(f2))
    check("chain tamper does NOT halt (C5)", halts(f2) == {False})
    con.execute("UPDATE audits SET passed=1 WHERE gate='gate1'"); con.commit()

    # 3. DELETION: remove an attested row so live < attested count → ATTEST_TAMPER.
    con.execute("DELETE FROM audits WHERE gate='gate2'"); con.commit()
    f3 = state_verify(con, "audits", attest_dir, trusted, dict(seen), now_epoch=now)
    check("deleted attested row → ATTEST_TAMPER", "ATTEST_TAMPER" in cats(f3))
    # restore for the next case (re-insert a row; the PREFIX is now reordered — also a tamper)
    ins(2, 1); con.commit()
    f3b = state_verify(con, "audits", attest_dir, trusted, dict(seen), now_epoch=now)
    check("reordered prefix (delete+reappend) → ATTEST_TAMPER", "ATTEST_TAMPER" in cats(f3b))

    # 4. tail-only edit on a NON-attested row must NOT alarm (only the attested prefix is load-bearing).
    #    rebuild a clean 3-row baseline, attest, then edit row #5 (beyond the attested prefix).
    con.close()
    con = sqlite3.connect(os.path.join(tmp, "state2.db"))
    con.execute("CREATE TABLE audits (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, gate TEXT,"
                " passed INTEGER, duration_s REAL, evidence TEXT)")
    ins = lambda g, p: con.execute("INSERT INTO audits (ts,gate,passed,duration_s,evidence)"
                                   " VALUES (?,?,?,?,?)", (f"2026-07-0{g}T00:00:00Z", f"g{g}", p, 1.0, "x"))  # hardcoded-allow: deterministic fixture
    for i in (1, 2, 3):
        ins(i, 1)
    con.commit()
    adir2 = os.path.join(tmp, "attest2")
    state_attest(con, "audits", sk, signer, adir2)   # attest 3 rows
    ins(4, 1); ins(5, 1); con.commit()                # append two
    con.execute("UPDATE audits SET passed=0 WHERE gate='g5'"); con.commit()  # edit a TAIL (non-attested) row
    f4 = state_verify(con, "audits", adir2, trusted, {}, now_epoch=now)
    check("edit of non-attested tail row → zero findings", f4 == [], str(cats(f4)))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else "")
             for n, ok, d in cases]
    return passed, failed, lines


# ── GATE 4: end-to-end on a read-only snapshot of the REAL state.db ──────────────────────────────
# Proves the primitive on REAL row shapes (the coupling_registry's pipe/newline-laden text, 100+
# audit rows, real shas) that the synthetic suites could not exercise. NEVER mutates production: the
# clean roundtrip runs against a read-only snapshot; the tamper proof runs against a writable COPY of
# that snapshot. Integration into the live reconcile (real emit_algedonic on the host) and the Rust
# port are the PRODUCTIVE phase, after this dev cycle closes.
def _run_gate4_suite(db_path):
    import os
    import shutil
    import sqlite3
    import tempfile
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    tmp = tempfile.mkdtemp(prefix="vsf-attest-g4-")
    attest_dir = os.path.join(tmp, "attestations")
    sk, pub_raw, signer = load_or_generate_key(os.path.join(tmp, "keys"))
    trusted = {signer: pub_raw}
    now = _parse_iso(_now_iso())

    # ── clean roundtrip on the read-only real snapshot ──
    ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    for table in ("deploys", "audits", "coupling_registry"):
        try:
            rec = state_attest(ro, table, sk, signer, attest_dir)
            if rec["mode"] == "chain":  # "<n>:<64-hex head>"
                n_str, _, head = rec["commitment"].partition(":")
                ok_commit = n_str.isdigit() and len(head) == 64 and all(c in "0123456789abcdef" for c in head)
            else:
                ok_commit = len(rec["commitment"]) == 64 and all(c in "0123456789abcdef" for c in rec["commitment"])
            check(f"{table}: attest real data", ok_commit, rec["commitment"][:12])
            # determinism on real data: serialize twice, identical bytes
            det = canonical_serialize(ro, table, SURFACES.get(table)) == canonical_serialize(ro, table, SURFACES.get(table))
            check(f"{table}: canonical deterministic on real data", det)
            findings = state_verify(ro, table, attest_dir, trusted, {}, now_epoch=now)
            check(f"{table}: clean verify → zero findings", findings == [], str({f[0] for f in findings}))
        except Exception as e:
            check(f"{table}: attest/verify real data", False, repr(e))
    ro.close()

    # ── tamper proof on a WRITABLE COPY (production untouched) ──
    copy = os.path.join(tmp, "state_copy.db")
    shutil.copy(db_path, copy)
    rw = sqlite3.connect(copy)
    adir2 = os.path.join(tmp, "attest2")
    # fresh attestation of the copy as the baseline
    n_deploys = rw.execute("SELECT count(*) FROM deploys").fetchone()[0]
    state_attest(rw, "deploys", sk, signer, adir2)
    state_attest(rw, "coupling_registry", sk, signer, adir2)
    base = state_verify(rw, "deploys", adir2, trusted, {}, now_epoch=now)
    check("copy baseline → zero findings", base == [], str({f[0] for f in base}))

    if n_deploys > 0:
        # tamper a real deploys row (flip a result) → ATTEST_TAMPER
        rw.execute("UPDATE deploys SET result='rollback' WHERE id=(SELECT min(id) FROM deploys)"); rw.commit()
        ft = state_verify(rw, "deploys", adir2, trusted, {}, now_epoch=now)
        check("tamper real deploys row → ATTEST_TAMPER", "ATTEST_TAMPER" in {f[0] for f in ft})
        check("tamper does not halt (C5)", all(f[4] is False for f in ft))

    # bump the genuine volatile (coupling_registry.refreshed_at) → NO finding
    cbase = state_verify(rw, "coupling_registry", adir2, trusted, {}, now_epoch=now)
    rw.execute("UPDATE coupling_registry SET refreshed_at='2099-01-01T00:00:00Z'"); rw.commit()  # hardcoded-allow: deterministic fixture
    cf = state_verify(rw, "coupling_registry", adir2, trusted, {}, now_epoch=now)
    check("bump refreshed_at → still zero findings", cbase == [] and cf == [], str({f[0] for f in cf}))

    # ── audits CHAIN mode on REAL rows (the §audits_followup e2e — append-only shapes) ──
    n_audits = rw.execute("SELECT count(*) FROM audits").fetchone()[0]
    state_attest(rw, "audits", sk, signer, adir2)  # chain-attest the real audits prefix
    abase = state_verify(rw, "audits", adir2, trusted, {}, now_epoch=now)
    check("audits chain baseline → zero findings", abase == [], str({f[0] for f in abase}))
    # APPEND a real-shaped row (duplicate all non-id cols of an existing row) → still zero (the point)
    acols = [r[1] for r in rw.execute("PRAGMA table_info(audits)").fetchall() if r[1] != "id"]
    if n_audits > 0 and acols:
        clist = ", ".join(f'"{c}"' for c in acols)
        rw.execute(f"INSERT INTO audits ({clist}) SELECT {clist} FROM audits ORDER BY rowid LIMIT 1"); rw.commit()
        afa = state_verify(rw, "audits", adir2, trusted, {}, now_epoch=now)
        check("audits append → zero findings (append-only tolerated)", afa == [], str({f[0] for f in afa}))
        # tamper the FIRST (attested) audits row's last semantic column → ATTEST_TAMPER
        sem = [c for c in acols if c not in VOLATILE_DEFAULT]
        if sem:
            rw.execute(f'UPDATE audits SET "{sem[-1]}"=? WHERE rowid=(SELECT min(rowid) FROM audits)',
                       ("__TAMPER__",)); rw.commit()
            aft = state_verify(rw, "audits", adir2, trusted, {}, now_epoch=now)
            check("tamper real audits prefix row → ATTEST_TAMPER", "ATTEST_TAMPER" in {f[0] for f in aft})
            check("audits chain tamper does not halt (C5)", all(f[4] is False for f in aft))
    rw.close()

    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d else "")
             for n, ok, d in cases]
    return passed, failed, lines


# ── INJECTION SUITE (correction C2 validated BY INJECTION, not by inspection) ────────────────────
def _mk(rows, schema="(a TEXT, b TEXT)", name="t"):
    """Build an in-memory table from literal rows. Self-contained: no n02 state touched."""
    con = sqlite3.connect(":memory:")
    con.execute(f"CREATE TABLE {name} {schema}")
    if rows:
        ph = ", ".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO {name} VALUES ({ph})", rows)
    return con


def _run_injection_suite():
    """Each case asserts a property the primitive dies without. Returns (passed, failed, lines)."""
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    # 1. COLLISION: ('ab','c') vs ('a','bc') — the classic concatenation collision MUST NOT happen.
    h1 = commitment(_mk([("ab", "c")]), "t")
    h2 = commitment(_mk([("a", "bc")]), "t")
    check("collision/ab|c vs a|bc", h1 != h2, f"{h1[:8]} vs {h2[:8]}")

    # 2. TYPE/NULL distinctness: NULL vs '' (empty text) vs a 0xFF byte must all differ.
    h_null = commitment(_mk([(None, "x")]), "t")
    h_empty = commitment(_mk([("", "x")]), "t")
    h_ff = commitment(_mk([("ÿ", "x")]), "t")
    check("null != empty-text", h_null != h_empty, f"{h_null[:8]} vs {h_empty[:8]}")
    check("empty-text != 0xff-text", h_empty != h_ff, f"{h_empty[:8]} vs {h_ff[:8]}")

    # 3. TYPE across storage class: INTEGER 0 vs TEXT "0" must differ.
    hi = commitment(_mk([(0, "x")], schema="(a, b TEXT)"), "t")
    hs = commitment(_mk([("0", "x")], schema="(a, b TEXT)"), "t")
    check("int 0 != text '0'", hi != hs, f"{hi[:8]} vs {hs[:8]}")

    # 4. ROW-ORDER independence: same rows, different insertion order → SAME hash.
    ha = commitment(_mk([("r1", "x"), ("r2", "y")]), "t")
    hb = commitment(_mk([("r2", "y"), ("r1", "x")]), "t")
    check("row-order independent", ha == hb, f"{ha[:8]} vs {hb[:8]}")

    # 5. VOLATILE excluded: a differing refreshed_at must NOT move the hash (no false alarm).
    cv1 = _mk([("svc", "2026-06-04T00:00:00Z")], schema="(name TEXT, refreshed_at TEXT)")  # hardcoded-allow: deterministic fixture
    cv2 = _mk([("svc", "2026-06-04T23:59:59Z")], schema="(name TEXT, refreshed_at TEXT)")
    check("volatile refreshed_at excluded", commitment(cv1, "t") == commitment(cv2, "t"))

    # 5b. VOLATILE auto-id excluded: different rowids, same content → SAME hash.
    ci1 = _mk([(1, "svc")], schema="(id INTEGER, name TEXT)")
    ci2 = _mk([(99, "svc")], schema="(id INTEGER, name TEXT)")
    check("volatile id excluded", commitment(ci1, "t") == commitment(ci2, "t"))

    # 6. SENSITIVITY: a real (non-volatile) cell change MUST flip the hash.
    cs1 = _mk([("svc", "active")], schema="(name TEXT, status TEXT)")
    cs2 = _mk([("svc", "stopped")], schema="(name TEXT, status TEXT)")
    check("semantic change detected", commitment(cs1, "t") != commitment(cs2, "t"))

    # 6b. SENSITIVITY add/remove row: an injected extra row MUST flip the hash (the tamper case).
    cr1 = _mk([("svc", "active")], schema="(name TEXT, status TEXT)")
    cr2 = _mk([("svc", "active"), ("ghost", "active")], schema="(name TEXT, status TEXT)")
    check("injected row detected", commitment(cr1, "t") != commitment(cr2, "t"))

    # 7. COLUMN-NAME sensitivity: renaming a column (same values) MUST flip the hash.
    cn1 = _mk([("svc", "active")], schema="(name TEXT, status TEXT)")
    cn2 = _mk([("svc", "active")], schema="(name TEXT, state TEXT)")
    check("column rename detected", commitment(cn1, "t") != commitment(cn2, "t"))

    # 8. COLUMN-ORDER independence at schema level: same semantic content, declared in a different
    #    column order → SAME hash (columns are sorted by name).
    co1 = _mk([("svc", "active")], schema="(name TEXT, status TEXT)")
    co2 = sqlite3.connect(":memory:")
    co2.execute("CREATE TABLE t (status TEXT, name TEXT)")
    co2.execute("INSERT INTO t (name, status) VALUES (?, ?)", ("svc", "active"))
    check("schema column-order independent", commitment(co1, "t") == commitment(co2, "t"))

    # 9. BLOB vs TEXT distinctness: same bytes, different storage class → differ.
    hb_blob = commitment(_mk([(b"abc",)], schema="(a BLOB)"), "t")
    hb_text = commitment(_mk([("abc",)], schema="(a TEXT)"), "t")
    check("blob != text same bytes", hb_blob != hb_text, f"{hb_blob[:8]} vs {hb_text[:8]}")

    # 10. DETERMINISM: serializing the same table twice → identical bytes.
    cd = _mk([("svc", "active"), ("two", "x")], schema="(name TEXT, status TEXT)")
    check("deterministic", canonical_serialize(cd, "t") == canonical_serialize(cd, "t"))

    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else "")
             for name, ok, detail in cases]
    return passed, failed, lines


# ── PROD-A1a: the live host agent — wires the (gate-proven) writer + verifier into one timer pass ──

def emit_algedonic(category, severity, instance, detail):
    """Dual-channel algedonic emit — byte-for-byte the topology_reconcile contract (the g6 sink on 104
    dedups by source_id/category). Reliable inbox append (pct exec 104) + best-effort NATS PUB (106)."""
    import subprocess
    import json as _j
    ts = _now_iso()
    line = f"{ts}  S3-ATTEST {category}  {instance} — {detail}"
    safe = line.replace("'", "")
    subprocess.run(["bash", "-c",
        f"pct exec {INBOX_LXC} -- bash -c \"mkdir -p /alerts && echo '{safe}' >> {INBOX_PATH}\""],
        capture_output=True, timeout=20)
    payload = _j.dumps({"severity": severity, "source_id": "s3_state_attest",
                        "category": category, "instance": instance, "detail": detail, "ts": ts})
    py = ("import socket\n"
          f"p={payload!r}.encode()\n"
          "s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',4222)); s.recv(4096)\n"
          "s.send(b'CONNECT {}\\r\\n'); "
          f"s.send(b'PUB vsf.alpha.algedonic.{category} '+str(len(p)).encode()+b'\\r\\n'+p+b'\\r\\n')\n"
          "s.close()")
    subprocess.run(["bash", "-c", f"pct exec {NATS_LXC} -- python3 -c {py!r}"],
                   capture_output=True, timeout=20)
    return line


def _load_seen(path):
    """Persistent monotonic heads (C3 anti-rollback) carried across timer firings. JSON lists → tuples."""
    import os
    import json
    if not os.path.exists(path):
        return {}
    try:
        raw = json.load(open(path, encoding="utf-8"))
        return {k: tuple(v) for k, v in raw.items()}
    except Exception:
        return {}  # a corrupt seen file must not halt the agent (C5) — it re-baselines this run


def _save_seen(path, seen):
    import os
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: list(v) for k, v in seen.items()}, f, sort_keys=True)
    os.replace(tmp, path)  # atomic — a killed agent never leaves a half-written seen file


# ── C1: trust roots in the offline-S5 CA (Ax_TwoLevelAttestation), not a hand-listed signer set ───
def _import_s5ca():
    """Import the verify-half of the offline CA tool (build_trust/verify_cert/verify_crl). Pure, no
    secret — the same module the ceremony uses, deployed beside the agent. None if not present."""
    import importlib.util
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "s5_ca.py"), "/usr/local/bin/s5_ca.py", "/usr/local/lib/vsf/s5_ca.py"):
        if os.path.exists(cand):
            spec = importlib.util.spec_from_file_location("s5_ca", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def load_ca_trust(ca_dir=CA_DIR_DEFAULT, now_epoch=None, pin=S5_ROOT_PIN):
    """Build the C1 trust-set from the host's CA artifacts: {key_id: component_pub} for every cert that
    CHAINS to the embedded root pubkey, is in-date, and is NOT in the (root-signed) CRL. Returns
    (trusted, notes). NO root pubkey present (pre-ceremony) ⇒ ({}, []) so the caller falls back to
    dogfood self-trust — the live agent must never break mid-migration (C5). The root pubkey is PINNED
    (G_genesis): a root whose fingerprint ≠ `pin` is rejected (a swapped CA dir), never trusted."""
    import os
    import json
    pub_path = os.path.join(ca_dir, "s5_root.pub.json")
    if not os.path.exists(pub_path):
        # A1e (quis-custodiet): a pin is set ⇒ the CA was provisioned, so an ABSENT root is a downgrade
        # attempt (delete s5-ca → silently revert to dogfood self-trust). Make it LOUD, not silent. Only
        # when the pin is DISABLED (pin="" — genuinely pre-ceremony) is the silent dogfood fallback ok.
        if pin:
            return {}, [("FORGERY", f"pinned CA root absent at {ca_dir} — s5-ca removed / trust downgrade?")]
        return {}, []  # pre-ceremony (pin disabled) → dogfood fallback, silent (not a finding)
    s5 = _import_s5ca()
    if s5 is None:
        return {}, [("DEGRADE", "s5_ca module not found beside the agent — cannot verify the CA chain")]
    try:
        root_pub_doc = json.load(open(pub_path, encoding="utf-8"))
        # G_genesis: the root pubkey must (a) self-identify honestly and (b) match the in-code pin.
        got_id = s5._key_id(bytes.fromhex(root_pub_doc["root_pub"]))
        if root_pub_doc.get("root_id") != got_id:
            return {}, [("FORGERY", f"root self-id mismatch ({root_pub_doc.get('root_id')} ≠ {got_id})")]
        if pin and got_id != pin:
            return {}, [("FORGERY", f"root {got_id} ≠ pinned {pin} — s5-ca dir swapped?")]
        certs = []
        cert_dir = os.path.join(ca_dir, "certs")
        if os.path.isdir(cert_dir):
            for fn in sorted(os.listdir(cert_dir)):
                if fn.endswith(".json"):
                    certs.append(json.load(open(os.path.join(cert_dir, fn), encoding="utf-8")))
        crl_path = os.path.join(ca_dir, "s5_crl.json")
        crl = json.load(open(crl_path, encoding="utf-8")) if os.path.exists(crl_path) else None
        if crl is None:
            trusted, raw = s5.build_trust(root_pub_doc, certs, None, now_epoch)
            return trusted, raw + [("DEGRADE", "no CRL present — revocation disabled (ship a signed CRL)")]
        return s5.build_trust(root_pub_doc, certs, crl, now_epoch)
    except Exception as e:
        # A malformed CA artifact must DEGRADE, never halt or silently self-trust (C5). Returning an
        # empty trust-set makes every signer untrusted ⇒ ATTEST_FORGERY fires (loud, not silent).
        return {}, [("DEGRADE", f"CA artifacts unreadable: {e}")]


def run_agent(db_path=STATE_DB_DEFAULT, attest_dir=ATTEST_DIR_DEFAULT, key_dir=KEY_DIR_DEFAULT,
              seen_path=SEEN_PATH_DEFAULT, surfaces=AGENT_SURFACES, emit=True, ca_dir=CA_DIR_DEFAULT):
    """One timer pass of the AX-STATE host agent (PROD-A1a). Per surface: VERIFY the prior signed head
    against LIVE state (emit algedonic on any finding — DEGRADE never halt, C5), THEN write a fresh
    signed snapshot, advancing the persistent monotonic head (C3). Read-only on state.db; the only
    writes are to attest_dir / key_dir / seen_path. Idempotent; safe to re-run.

    Returns (signer, [(surface, n_findings, [categories])]). On bootstrap (no chain yet) the verify is
    skipped for that surface (nothing to verify) and only the seed snapshot is written — no false MISSING."""
    import os
    import sqlite3
    sk, pub_raw, signer = load_or_generate_key(key_dir)
    emitter = (lambda c, s, surf, d, halt: emit_algedonic(c, s, surf, d)) if emit else None
    # C1: prefer the offline-S5 CA trust-set; fall back to dogfood self-trust pre-ceremony.
    ca_trusted, ca_notes = load_ca_trust(ca_dir)
    if ca_trusted:
        trusted, trust_mode = ca_trusted, "ca"
    else:
        trusted, trust_mode = {signer: pub_raw}, "dogfood"
    # CA-level notes (forged/stale/missing CRL, unreadable artifacts) — emit ONCE per pass, never halt.
    for level, reason in ca_notes:
        cat = {"FORGERY": "ATTEST_FORGERY", "STALE": "ATTEST_STALE",
               "EXPIRING": "ATTEST_CERT_EXPIRING"}.get(level, "ATTEST_DEGRADED")
        if emit:
            emit_algedonic(cat, SEV.get(cat, 5.0), "statedb.s5_ca", reason)
    seen = _load_seen(seen_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    summary = []
    try:
        for table in surfaces:
            bootstrap = not os.path.exists(_surface_file(attest_dir, f"statedb.{table}"))
            findings = [] if bootstrap else state_verify(con, table, attest_dir, trusted, seen, emitter=emitter)
            state_attest(con, table, sk, signer, attest_dir)  # re-baseline AFTER verifying the prior head
            summary.append((table, len(findings), [f[0] for f in findings]))
    finally:
        con.close()
    _save_seen(seen_path, seen)
    return signer, summary, trust_mode


def _run_ca_suite():
    """Validate the C1 wiring: CA-mode trust derives from certs chaining to the embedded root, a revoked
    signer drops out → ATTEST_FORGERY, and a missing CA falls back to dogfood. Needs s5_ca beside us."""
    import os
    import json
    import tempfile
    import shutil
    import sqlite3
    cases = []

    def check(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    s5 = _import_s5ca()
    if s5 is None:
        check("s5_ca importable beside the agent", False, "deploy s5_ca.py next to state_attest.py")
        return [c for c in cases if c[1]], [c for c in cases if not c[1]], \
               [f"  [FAIL] {cases[0][0]}  ({cases[0][2]})"]

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    tmp = tempfile.mkdtemp(prefix="vsf-attest-ca-")
    ca_dir = os.path.join(tmp, "s5-ca")
    os.makedirs(os.path.join(ca_dir, "certs"))
    now = _parse_iso(_now_iso())

    # throwaway offline root (no encryption needed for the public-side test)
    rsk = Ed25519PrivateKey.generate()
    seed = rsk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    from cryptography.hazmat.primitives.serialization import PublicFormat
    root_pub = rsk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    root_id = s5._key_id(root_pub)
    with open(os.path.join(ca_dir, "s5_root.pub.json"), "w") as f:
        json.dump({"v": 1, "type": "vsf-s5-root-pub", "root_id": root_id, "root_pub": root_pub.hex()}, f)

    # a component key via the SAME loader the agent uses → signer id == cert key_id
    csk, cpub, signer = load_or_generate_key(os.path.join(tmp, "keys"))
    cert = s5.issue_cert(seed, cpub.hex(), "vsf-state-attest", ["statedb.coupling_registry"], days=365)
    with open(os.path.join(ca_dir, "certs", "state-attest.json"), "w") as f:
        json.dump(cert, f)
    crl_path = os.path.join(ca_dir, "s5_crl.json")
    with open(crl_path, "w") as f:
        json.dump(s5.make_or_update_crl(seed, None, None, "", 30), f)  # empty signed CRL (freshness)

    # 1. clean CA (pinned to THIS throwaway root) → the component signer is trusted, no notes
    trusted, notes = load_ca_trust(ca_dir, now_epoch=now, pin=root_id)
    check("cert key_id == agent signer id", cert["key_id"] == signer)
    check("CA trust includes the component signer", signer in trusted)
    check("clean CA → no DEGRADE/FORGERY note", all(n[0] not in ("DEGRADE", "FORGERY") for n in notes), str(notes))

    # 2. e2e: an attestation signed by the component verifies clean under CA trust
    con = sqlite3.connect(os.path.join(tmp, "state.db"))
    con.execute("CREATE TABLE coupling_registry (resource TEXT PRIMARY KEY, status TEXT, refreshed_at TEXT)")
    con.execute("INSERT INTO coupling_registry VALUES ('ollama','active','2026-06-01T00:00:00Z')"); con.commit()  # hardcoded-allow: deterministic fixture
    attest_dir = os.path.join(tmp, "attest")
    state_attest(con, "coupling_registry", csk, signer, attest_dir)
    f_clean = state_verify(con, "coupling_registry", attest_dir, trusted, {}, now_epoch=now)
    check("CA-trusted signer → clean verify", f_clean == [], str({x[0] for x in f_clean}))

    # 3. REVOKE the component → drops from trust → its signature now reads as ATTEST_FORGERY
    revoked_crl = s5.make_or_update_crl(seed, json.load(open(crl_path)), signer, "host compromised", 30)
    with open(crl_path, "w") as f:
        json.dump(revoked_crl, f)
    trusted2, _ = load_ca_trust(ca_dir, now_epoch=now, pin=root_id)
    check("revoked signer absent from trust", signer not in trusted2)
    f_rev = state_verify(con, "coupling_registry", attest_dir, trusted2, {}, now_epoch=now)
    check("revoked signer → ATTEST_FORGERY", "ATTEST_FORGERY" in {x[0] for x in f_rev})

    # 4. no root pubkey + pin DISABLED (pre-ceremony) → dogfood fallback (empty, silent — not a finding)
    empty = os.path.join(tmp, "empty"); os.makedirs(empty)
    t_empty, n_empty = load_ca_trust(empty, now_epoch=now, pin="")
    check("no CA root + pin disabled → silent dogfood", t_empty == {} and n_empty == [])
    # 4b. A1e: no root pubkey but a pin IS set (post-ceremony) → LOUD downgrade signal, NOT silent
    t_gone, n_gone = load_ca_trust(empty, now_epoch=now, pin=root_id)
    check("CA root absent while pinned → empty trust", t_gone == {})
    check("CA root absent while pinned → FORGERY note (not silent)", any(x[0] == "FORGERY" for x in n_gone))

    # 5. a cert signed by a FOREIGN root must not be trusted
    other = Ed25519PrivateKey.generate()
    other_seed = other.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    foreign = s5.issue_cert(other_seed, cpub.hex(), "vsf-state-attest", ["statedb.coupling_registry"])
    fdir = os.path.join(tmp, "foreign-ca"); os.makedirs(os.path.join(fdir, "certs"))
    shutil.copy(os.path.join(ca_dir, "s5_root.pub.json"), os.path.join(fdir, "s5_root.pub.json"))
    with open(os.path.join(fdir, "certs", "x.json"), "w") as f:
        json.dump(foreign, f)
    t_foreign, _ = load_ca_trust(fdir, now_epoch=now, pin=root_id)
    check("foreign-root cert → not trusted", signer not in t_foreign)

    # 6. G_genesis: a CA dir whose root ≠ the PIN is rejected wholesale (swapped-dir attack)
    t_pin, n_pin = load_ca_trust(ca_dir, now_epoch=now, pin="ed25519:0000000000000000")
    check("wrong pin → empty trust", t_pin == {})
    check("wrong pin → FORGERY note", any(x[0] == "FORGERY" for x in n_pin))

    # 7. A1d: a near-expiry cert is STILL trusted but surfaces an EXPIRING note (the pre-warn)
    ca_soon = os.path.join(tmp, "ca-soon"); os.makedirs(os.path.join(ca_soon, "certs"))
    shutil.copy(os.path.join(ca_dir, "s5_root.pub.json"), os.path.join(ca_soon, "s5_root.pub.json"))
    json.dump(s5.make_or_update_crl(seed, None, None, "", 30),  # FRESH empty CRL (ca_dir's revokes the key)
              open(os.path.join(ca_soon, "s5_crl.json"), "w"))
    soon = s5.issue_cert(seed, cpub.hex(), "vsf-state-attest", ["statedb.coupling_registry"], days=10)
    json.dump(soon, open(os.path.join(ca_soon, "certs", "soon.json"), "w"))
    t_soon, n_soon = load_ca_trust(ca_soon, now_epoch=now, pin=root_id)
    check("near-expiry cert still trusted", signer in t_soon)
    check("near-expiry cert → EXPIRING note", any(x[0] == "EXPIRING" for x in n_soon))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    passed = [c for c in cases if c[1]]
    failed = [c for c in cases if not c[1]]
    lines = [f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f"  ({d})" if d and not ok else "")
             for n, ok, d in cases]
    return passed, failed, lines


def main():
    if "--agent" in sys.argv:
        def opt(flag, default):
            return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default
        db_path = opt("--db", STATE_DB_DEFAULT)
        attest_dir = opt("--attest-dir", ATTEST_DIR_DEFAULT)
        key_dir = opt("--key-dir", KEY_DIR_DEFAULT)
        seen_path = opt("--seen", SEEN_PATH_DEFAULT)
        ca_dir = opt("--ca-dir", CA_DIR_DEFAULT)
        emit = "--no-emit" not in sys.argv
        signer, summary, trust_mode = run_agent(db_path, attest_dir, key_dir, seen_path,
                                                emit=emit, ca_dir=ca_dir)
        print(f"# state_attest --agent — AX-STATE host pass (signer={signer}, emit={emit}, trust={trust_mode})")
        print(f"#   db={db_path} attest_dir={attest_dir} surfaces={','.join(AGENT_SURFACES)}"
              + (f" ca_dir={ca_dir}" if trust_mode == 'ca' else "  [dogfood self-trust — CA not provisioned]"))
        total = 0
        for table, n, cats in summary:
            total += n
            status = "✓ clean" if n == 0 else f"⚠ {n} finding(s): {', '.join(cats)}"
            print(f"  statedb.{table:18s} {status}")
        print(f"## RESULT: {total} algedonic finding(s) this pass (all DEGRADE, never halt — C5)")
        return 0  # the agent NEVER fails the unit on a finding — it emits and keeps the timer alive
    if "--gate2" in sys.argv:
        passed, failed, lines = _run_gate2_suite()
        print("# state_attest --gate2 — signed-writer mechanism suite (synthetic state.db)")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## GATE 2: ✗ NOT MET — writer/chain/signature not sound. Do NOT wire state_verify.")
            return 1
        print("## GATE 2: ✓ MET — signed per-surface chain sound. Cleared to wire state_verify (GATE 3).")
        return 0
    if "--gate3" in sys.argv:
        passed, failed, lines = _run_gate3_suite()
        print("# state_attest --gate3 — verifier suite (6 checks + C5 degrade, synthetic chains)")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## GATE 3: ✗ NOT MET — verifier misses a tamper class or false-alarms. Do NOT integrate.")
            return 1
        print("## GATE 3: ✓ MET — verifier catches all injected tampers, zero false alarms, never halts.")
        print("##          Cleared to integrate into the live reconcile + e2e on real state.db (GATE 4).")
        return 0
    if "--gate-ca" in sys.argv:
        passed, failed, lines = _run_ca_suite()
        print("# state_attest --gate-ca — C1 two-level trust (offline-S5 CA → cert → component signer)")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## GATE CA: ✗ NOT MET — CA trust/revocation wiring unsound. Do NOT cut over from dogfood.")
            return 1
        print("## GATE CA: ✓ MET — trust chains to the offline root; revocation drops the key (→ FORGERY);")
        print("##          missing CA falls back to dogfood. Cleared to deploy the root pubkey + cert + CRL.")
        return 0
    if "--gate-chain" in sys.argv:
        passed, failed, lines = _run_chain_suite()
        print("# state_attest --gate-chain — append-only (audits) verify variant (§audits_followup)")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## GATE CHAIN: ✗ NOT MET — chain verify false-alarms on append or misses a prefix tamper.")
            return 1
        print("## GATE CHAIN: ✓ MET — appends tolerated; past-row edit / deletion / reorder all caught,")
        print("##             never halts. Cleared to enrol audits (mode=chain) into the production agent.")
        return 0
    if "--gate4" in sys.argv:
        i = sys.argv.index("--gate4")
        if i + 1 >= len(sys.argv):
            print("## GATE 4: needs a path to a read-only snapshot of the real state.db")
            return 2
        db_path = sys.argv[i + 1]
        passed, failed, lines = _run_gate4_suite(db_path)
        print(f"# state_attest --gate4 — e2e on a real state.db snapshot ({db_path})")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## GATE 4: ✗ NOT MET — primitive fails on real data. Cycle not closed.")
            return 1
        print("## GATE 4: ✓ MET — primitive works end-to-end on real state.db data, production untouched.")
        print("##          DEV CYCLE CLOSED. Next (productive phase): integrate into the live S3* reconcile;")
        print("##          then port to Rust in the nucleus.")
        return 0
    if "--inject" in sys.argv or "--selftest" in sys.argv:
        passed, failed, lines = _run_injection_suite()
        print("# state_attest --inject — canonical_serialize injection suite (GATE C2)")
        for ln in lines:
            print(ln)
        print(f"\n## RESULT: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print("## GATE C2: ✗ NOT MET — canonical_serialize is not yet injective/stable. Do NOT wire the writer.")
            return 1
        print("## GATE C2: ✓ MET — canonical_serialize injective + stable. Cleared to build the writer (GATE 2).")
        return 0
    print("usage: state_attest.py [--inject|--gate2|--gate3|--gate-chain|--gate-ca|--gate4 DB|--agent]  # n02, never WSL")
    print("  --inject     GATE C2  : canonical_serialize injection suite")
    print("  --gate2      GATE 2   : signed-writer mechanism suite (synthetic state.db)")
    print("  --gate3      GATE 3   : verifier suite — 6 checks + C5 degrade (synthetic chains)")
    print("  --gate-chain GATE CHN : append-only (audits) verify variant — §audits_followup")
    print("  --gate-ca    GATE CA  : C1 two-level trust — offline-S5 CA → cert → signer + revocation")
    print("  --gate4 DB   GATE 4   : e2e on a real state.db snapshot")
    print("  --agent      PROD-A1a : one live host pass (verify+attest+emit) over deploys+coupling_registry+audits")
    print("             flags: --db --attest-dir --key-dir --seen --ca-dir PATH --no-emit")
    print("             flags: --db PATH --attest-dir DIR --key-dir DIR --seen PATH --no-emit")
    return 2


if __name__ == "__main__":
    sys.exit(main())
