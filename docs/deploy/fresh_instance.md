# Fresh VSF instance — modular deploy + dependency ledger

> **Status:** `feat/cybernetic-rag`, v0.1. The reproducible bootstrap for an out-of-the-box LXC joining
> the VSF as a clean viable module (per `legacy_module_migration.md`).
> **Directive (rmw3, 2026-06-05):** we are still CALIBRATING — expect rewiring. So **modularity** (each
> capability is an independent, idempotent layer you can add/remove) and **traceability** (what is
> installed where lives in the canon, queryable, never guessed) are the design priorities.

## 0. Principles

- **Layered + opt-in.** A fresh LXC gets the **base layer**, then only the **capability layers** its
  `Sn-function` role needs (§2, §3). Each layer is idempotent (re-runnable) and independent (add/remove
  without touching the others). Rewiring = swap a layer, not rebuild the box.
- **Traceability = canon, not memory.** Every install is recorded where the reconcile can see it:
  - `state.db.lxcs` — the box exists, with its `Sn-function` role.
  - `state.db.coupling_registry` — every φ↑/φ↓/shared-resource coupling it offers or consumes.
  - the module manifest (`opsroom/modules/<id>.module.json`) — pinned `schema_ref` + `version`.
  - the **dependency ledger** (§6) — pinned package versions.
  An `active` declaration with no live feed = ORPHAN (S3* `topology_reconcile`). So the canon and the
  box cannot silently drift.
- **No legacy base.** A new module is built clean (R9); it consumes the canonical φ↑ channel
  (`core/connection_schema.json`), never a legacy interface.

## 1. Base layer (EVERY fresh LXC)

Provision on the Proxmox host (n02), never WSL; never write to the host `/root` (R3):

```bash
# 1.1 create (unprivileged, no productive mounts; pick the next FREE id — validate vs LIVE state.db, R9)
pct create <id> local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname <sN-function> --cores 2 --memory 1024 --swap 512 --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,tag=20,ip=10.10.20.<id>/24,gw=10.10.20.1 \
  --nameserver 1.1.1.1 --unprivileged 1 --features nesting=1 --ostype debian --onboot 1
pct start <id>

# 1.2 base packages (debian-12 ships python3 3.11; keep the box minimal)
pct exec <id> -- apt-get update -qq
pct exec <id> -- DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates

# 1.3 DECLARE in the canon (traceability) — validate the id is free in LIVE state.db FIRST (R9)
sqlite3 /var/lib/vsf-state/state.db \
 "INSERT OR REPLACE INTO lxcs (id,role,ip,notes) VALUES (<id>,'<sN-function>','10.10.20.<id>','...');"
# and add the row to scripts/state/seed.sql (durable; lxcs is hand-edited canon).
```

## 2. Capability layers (modular, opt-in)

| layer | install | needed by |
|---|---|---|
| **crypto / attestation** | `apt-get install -y python3-cryptography` (Ed25519) | any φ↑ producer/consumer (AX-STATE `state_attest`/`state_verify`) |
| **NATS φ↑ client** | `pip install nats-py` *(pin on first install, §6)* | any module that pubs/subs the φ↑ bus |
| **NATS broker** | `apt-get install -y nats-server` (+ unit) | the `s2-broker` role only |
| **view-host** | push `opsroom/view_host/*` + `scripts/state/state_attest.py`; a static server | `s5-opsroom` (the visualizer host) |
| **nucleus** | the Rust binary (built on the target LXC, R2) | `s3s4-nucleus` |

**Deploy of VSF code** (push, never host `/root`): build/test on the target LXC or the sandbox (108);
`scp` to host `/tmp` → `pct push <id> /tmp/x /root/x --perms <mode>` → `rm` the `/tmp` copy.

## 3. Role → layer matrix

| `Sn-function` (LXC) | base | crypto | NATS client | NATS broker | view-host | nucleus |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `s3s4-nucleus` (101) | ✓ | ✓ | ✓ | | | ✓ |
| `s5-policy` (104) | ✓ | ✓ | ✓ | | | |
| `s2-broker` (106) | ✓ | | ✓ | ✓ | | |
| `s3star-audit` (107) | ✓ | ✓ | ✓ | | | |
| `s5-opsroom` (109) | ✓ | ✓ | ✓ | | ✓ | |
| `dev-sandbox` (108) | ✓ | ✓ | | | | | *(test harness; no productive coupling)* |

## 4. Worked example — `s5-opsroom` (LXC 109, the view-host)

```bash
# layers: base (done) + crypto + NATS client + view-host
pct exec 109 -- DEBIAN_FRONTEND=noninteractive apt-get install -y python3-cryptography
pct exec 109 -- pip install --break-system-packages nats-py   # pin version in §6 on first run
# push the clean module (NO legacy api.py):
#   opsroom/view_host/cybernetic_rag_view.py  +  scripts/state/state_attest.py  +  the static host + index.html scaffold
# declare the coupling (already done §7.1): coupling_registry 'view-cybernetic-rag' kind=phi_channel status=planned
# run the gates before flipping status→active: G-V1 (version) G-V2/G-V3 (builder, see --gate72) G-V4 (declared)
# cut over: stop SCADA on 101 ONLY once 109 serves the verified view (migration protocol step 4).
```

## 5. Decommission (modularity — clean removal is a first-class step)

```bash
# retire a module: stop its service; set its coupling_registry row status='deprecated' (or delete);
#   set lifecycle=decommissioned in the manifest; the host reflows. Then optionally:
pct stop <id> && pct destroy <id>
# remove its state.db.lxcs row + seed.sql row. The S3* reconcile confirms model≡reality (no orphan).
```

## 6. Dependency ledger (traceability — pin every version)

Verified on the sandbox (108), 2026-06-05:

| component | version (pinned) | source |
|---|---|---|
| LXC template | `debian-12-standard_12.12-1_amd64` | proxmox `local:vztmpl` |
| python3 | 3.11.2 | debian-12 base |
| python3-cryptography | 38.0.4 | debian apt |
| mermaid (view-host) | `10.9.1` (3.3MB, vendored to `opsroom/view_host/mermaid.min.js`, served locally — no runtime CDN) | jsdelivr, fetched on deploy |
| nats-py | *(NOT used for φ↑ — the canonical φ↑ is the events.jsonl file/bind-mount, v0.2.2; NATS = algedonic only)* | pip |
| nats-server | *(broker role — pin on install)* | debian apt |

**The canon IS the install record.** To answer "what is on box X / who consumes what", query `state.db`
(`lxcs`, `coupling_registry`) + the module manifests — not a person's memory. Keep this ledger in sync
with what is actually pinned (it is itself an AX-STATE candidate surface).
