# D.1 — Motor 2: read-only SQLite reader of `bbs.db`
> **STATUS: historical_record** — consumido por fuse S3-ALLOCATION → s3_allocation.vsm · archivo 2026-08-15 (SPEC-REVISION-ORDER-PLAN censo; contenido en el target canonical, este doc es fuente histórica).

**Status:** spec v0.1 (2026-05-30) — proposed, awaiting confirmation.
**Closes:** task #68 (spec only; implementation is a follow-up).

---

## 1. Background

The nucleus (LXC 101) embeds an SQLite database `/root/bbs.db` via the
`rusqlite` crate (feature `bundled`), used by S4 to read/write its
bulletin-board state (S4 decisions, BBH ideas, phi-down acknowledgements).
This is the **Motor 1**: read-write, single-writer, single-process,
in-binary.

Several other subsystems would benefit from observing the same data
without going through NATS or the S4 process: the operational dashboard,
S3\* auditors that want to cross-check the chain against S4 reasoning,
analytical scripts (e.g., `k_phi_down_meter.py`) that today must parse
`events.jsonl`. A second access path is needed — **Motor 2** — that
provides read-only access to `bbs.db` from outside the nucleus process
without disturbing Motor 1’s write throughput.

## 2. Scope and non-goals

| In scope | Out of scope |
|----------|--------------|
| Read-only SQL queries against `bbs.db` from any host that can reach LXC 101 | Modifying schemas |
| Snapshot consistency (no torn reads) | Replacing Motor 1 |
| Lock-free coexistence with Motor 1 writes | Cluster replication |
| Auth/scoping by caller identity | Public exposure (LAN only) |

Motor 2 is **not** a general-purpose database server. It exists to let
*auditors and read-only consumers* observe what S4 is doing without
introducing write contention or polling overhead on the nucleus process.

## 3. Design choices and rationale

### 3.1 Access mode — WAL + immutable handles

Open the database with:

```rust
let conn = Connection::open_with_flags(
    "/root/bbs.db",
    OpenFlags::SQLITE_OPEN_READ_ONLY
        | OpenFlags::SQLITE_OPEN_URI
        | OpenFlags::SQLITE_OPEN_NO_MUTEX,
)?;
conn.pragma_update(None, "journal_mode", "WAL")?;          // already by Motor 1
conn.pragma_update(None, "query_only", "true")?;
```

SQLite WAL allows arbitrary concurrent readers while a single writer
proceeds. Motor 1 already runs in WAL (verified). Motor 2 readers open
READ_ONLY + QUERY_ONLY, defending against accidental write attempts.

### 3.2 Transport — local UNIX socket via a thin Rust service

Motor 2 runs as a **separate process** on LXC 101, exposing an HTTP+JSON
read API over a UNIX socket `/run/vsf/motor2.sock`. Choice rationale:

| Alternative | Why not |
|-------------|---------|
| Direct sqlite3 over file mount | requires sqlite client on every consumer; couples consumer to schema |
| NATS request/reply | already used for events; conflating data-plane and control-plane creates dependency mess |
| gRPC | heavy for the scope |
| Postgres-like wire protocol | overkill |

UNIX socket + JSON gives: local-only access (no firewall surface),
trivial client (curl), zero new dep on consumers.

### 3.3 Schema — exposed views, not raw tables

Motor 2 publishes a fixed set of **named queries**, not raw SQL. This
decouples consumers from schema changes and removes injection risk.

Initial queries (versioned `/v1/...`):

| Endpoint | Returns |
|----------|---------|
| `GET /v1/health` | `{"motor2": "ok", "rows_in_decisions": N, "wal_size_kb": K}` |
| `GET /v1/s4_decisions/recent?limit=N` | latest N rows from the S4 decisions table |
| `GET /v1/bbh_ideas/recent?limit=N` | latest N rows from the BBH ideas table |
| `GET /v1/phi_down/recent?limit=N` | latest N param_change rows |
| `GET /v1/by_id/{table}/{id}` | exact row lookup |

Each response: `{"v":1, "ts":"<ISO>", "rows":[...]}`.

### 3.4 Process model

Motor 2 is **not** part of the nucleus binary. Reasons:

1. Failure isolation: a panic in Motor 2 must not crash the nucleus.
2. Independent restartability for schema-change rollouts.
3. Anti-capture: the read path is structurally separated from the
   write path (parallel to the `vsf-s3-star` rationale).

It is a small (~200 LOC) Rust binary `vsf-motor2`, packaged like
`vsf-s3-star`. Same systemd-unit conventions, same release profile.

### 3.5 Concurrency and durability guarantees

| Property | Guarantee |
|----------|-----------|
| Read-write isolation | WAL — readers see snapshots; writers proceed |
| Torn reads | None: SQLite snapshot isolation per `BEGIN` |
| Motor 1 write throughput impact | < 5 % at expected query rates (TBD measure) |
| Read-after-write visibility | ≤ checkpoint interval, typically ≤ 1 s |

## 4. Threat model and access control

Motor 2 binds to a UNIX socket at `/run/vsf/motor2.sock` with `0660`
permissions, owner `root`, group `vsf-readers`. Any process in
`vsf-readers` (or root) can connect; others cannot. This is sufficient
for Tier α: every legitimate consumer runs on the same host as Motor 1.
For cross-host access (Tier β), the operator runs an SSH-or-VPN tunnel
to the socket.

There is **no per-query auth** in Tier α. If you can open the socket,
you can read everything in the exposed views.

## 5. Acceptance criteria

The implementation is considered complete when:

1. `vsf-motor2` binary exists in `projects/vsf-motor2/`, ≤ 500 LOC.
2. `cargo test` covers each `/v1/...` endpoint with a synthetic
   `bbs.db` populated by a fixture.
3. A load test demonstrates ≥ 50 read-QPS from Motor 2 with Motor 1
   continuously writing ≥ 10 writes/s, with measured write-latency
   impact on Motor 1 ≤ 5 %.
4. `k_phi_down_meter.py` (#75 tooling) gains an `--motor2 <socket>`
   flag and produces the same K_φ↓ and τ values as the `events.jsonl`
   path.
5. The annex (B §7) gains an entry crediting D.1 with closing the
   "read-only observer" gap.

## 6. Out of scope, deferred

- Schema migrations and versioning policy (Tier β).
- A web UI (an opsroom panel) is a separate task.
- Replication or backup (handled at the SQLite-file level).
- Writes via Motor 2 — explicitly refused.

## 7. Effort estimate

| Phase | Effort |
|-------|--------|
| Project skeleton + Cargo.toml | < 1 h |
| Endpoint scaffold + 1 query (`/v1/health`) | 1 h |
| Remaining queries + tests | 2 h |
| systemd unit + deploy script | 1 h |
| Load test + tuning | 1 h |
| **Total** | **~6 h** |

## 8. Decision needed before implementation

Two open questions for the operator to confirm before code is written:

- **Q1**. Is the UNIX-socket-only access model acceptable, or should
  Motor 2 also listen on a TCP loopback port (e.g., `127.0.0.1:9101`)
  for use from non-Unix consumers (Python scripts that don't easily
  speak UDS)?
- **Q2**. Should `vsf-motor2` ship with the nucleus deploy bundle
  (paired releases) or with its own release cadence?
