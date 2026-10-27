/// telemetry_canonical.rs — γ.1 — Canonical φ↑ writer (per Qwen consensus rounds 1-4)
///
/// @vsm 0.3 — V("vsf-nucleus", L=1)
/// canonical: matches connection_schema.json v0.2.1 §upward_channel
///
/// Responsibilities:
///   1. Append events to /run/vsf/{system_id}/events.jsonl (tmpfs — fast fsync)
///   2. Background flush task: every 100ms, rotate tmpfs → /var/lib/vsf/{system_id}/events.jsonl
///   3. Maintain SHA256 Merkle chain (prev_hash field on each event)
///   4. Emit invariant fields: variety_delta, trust_score, algedonic_seq
///   5. Audit-safe: events.jsonl is the single source of truth
///
/// Design principle: "núcleo primero" — no NATS dependency here.
/// NATS publish is a SEPARATE concern (see nats_publisher.rs).
/// This module is the canonical ledger writer; NATS replicates it.
///
/// Defense in depth: telemetry.rs (original) is NOT touched.

use chrono::Utc;
use hex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::time;

/// Tmpfs root for hot staging. Created by systemd unit or manually.
/// Fallback: directly to disk if tmpfs unavailable.
pub const TMPFS_ROOT: &str = "/run/vsf";
pub const DISK_ROOT: &str = "/var/lib/vsf";
pub const EVENTS_FILENAME: &str = "events.jsonl";
pub const FLUSH_INTERVAL_MS: u64 = 100;
/// PROD-A1b — how often to mint a signed witness checkpoint over the chain head.
pub const WITNESS_CHECKPOINT_SECS: u64 = 60;
/// Sidecar file holding the Ed25519 witness statements (NOT events.jsonl — CanonicalEvent unchanged).
pub const WITNESS_FILENAME: &str = "events.witness.jsonl";

/// Canonical event matching connection_schema.json v0.2.1 §upward_channel.
/// Re-exported from `vsf-agent` (single source of truth shared with s3-star),
/// so the bit-exact Merkle hash parity is guaranteed by the compiler.
pub use vsf_agent::CanonicalEvent;

/// State shared between writer and flush task.
pub struct ChainState {
    pub last_hash: Option<String>,
    pub algedonic_counter: u64,
    pub tmpfs_path: PathBuf,
    pub disk_path: PathBuf,
    /// True if this is the first emit() after a restart where the chain tail was
    /// unreadable (i.e., a chain seam). The first event emitted will be preceded
    /// by a chain_seam marker event.
    pub needs_seam_event: bool,
}

/// Canonical writer with tmpfs staging + async flush + Merkle chain.
#[derive(Clone)]
pub struct CanonicalTelemetry {
    inner: Arc<Mutex<ChainState>>,
}

impl CanonicalTelemetry {
    /// Initialize. Creates directories if needed. Reads existing chain tail (if any)
    /// to continue prev_hash chain.
    pub fn new(system_id: &str) -> std::io::Result<Self> {
        Self::with_roots(system_id, TMPFS_ROOT, DISK_ROOT)
    }

    /// Initialize with custom roots. Used by tests and for non-standard deployments.
    pub fn with_roots(system_id: &str, tmpfs_root: &str, disk_root: &str) -> std::io::Result<Self> {
        let tmpfs_dir = Path::new(tmpfs_root).join(system_id);
        let disk_dir = Path::new(disk_root).join(system_id);

        // Best-effort create; if tmpfs_root is not writable, fall back to disk path for both.
        let tmpfs_ok = fs::create_dir_all(&tmpfs_dir).is_ok();
        fs::create_dir_all(&disk_dir)?;

        let tmpfs_path = if tmpfs_ok {
            tmpfs_dir.join(EVENTS_FILENAME)
        } else {
            disk_dir.join(EVENTS_FILENAME)
        };
        let disk_path = disk_dir.join(EVENTS_FILENAME);

        // Read tail hash from disk_path if exists (resume chain on restart).
        // NUCLEUS-CHAIN-RESTART-SEAM: detect if file has content but hash is unreadable
        // → chain seam. A chain_seam event will be emitted on the first emit() call.
        let file_has_content = fs::metadata(&disk_path).map(|m| m.len() > 0).unwrap_or(false);
        let last_hash = Self::read_tail_hash(&disk_path);
        let needs_seam = last_hash.is_none() && file_has_content;

        // G-K.2 fix: truncate tmpfs staging file on init. The disk is the
        // source of truth — anything still in tmpfs from a prior process
        // instance would otherwise be re-flushed on each restart, since
        // flush_delta starts with bytes_flushed=0. That bug produced 11×
        // duplication of the 3 surviving param_change events in the audit
        // window (33 = 3 × 11 restarts).
        if tmpfs_ok && tmpfs_path != disk_path {
            let _ = fs::OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .open(&tmpfs_path);
        }

        // ── WAL crash recovery: replay .pending files ─────────────────
        // If flush_delta crashed after step 1 (wrote .pending, fsync'd) but
        // before step 3 (removed .pending), the data is durable but not yet
        // in events.jsonl. Re-append and clean up.
        let pending_pattern = disk_dir.join("*.jsonl.pending");
        if let Ok(entries) = fs::read_dir(&disk_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().and_then(|e| e.to_str()) == Some("pending")
                    && path.file_stem()
                        .and_then(|s| s.to_str())
                        .map(|s| s.ends_with(".jsonl"))
                        .unwrap_or(false)
                {
                    let pending_content = match fs::read(&path) {
                        Ok(c) if !c.is_empty() => c,
                        _ => { let _ = fs::remove_file(&path); continue; }
                    };
                    match fs::OpenOptions::new()
                        .create(true)
                        .append(true)
                        .open(&disk_path)
                    {
                        Ok(mut f) => {
                            if f.write_all(&pending_content).is_ok()
                                && f.sync_data().is_ok()
                            {
                                eprintln!("[telemetry_canonical] WAL replay: appended {} bytes from {}",
                                    pending_content.len(), path.display());
                            }
                        }
                        Err(e) => eprintln!("[telemetry_canonical] WAL replay FAILED to open {}: {}", disk_path.display(), e),
                    }
                    let _ = fs::remove_file(&path);
                }
            }
        }
        // ── end WAL recovery ──────────────────────────────────────────

        Ok(Self {
            inner: Arc::new(Mutex::new(ChainState {
                last_hash,
                algedonic_counter: 0,
                tmpfs_path,
                disk_path,
                needs_seam_event: needs_seam,
            })),
        })
    }

    /// Best-effort tail-read of the last event's hash from disk events.jsonl.
    /// Uses file seek (O(64 KB)) instead of loading the whole file — O(file) was
    /// loading ~370k lines → O(300 MB) read on each restart. Also uses
    /// from_utf8_lossy so a single invalid UTF-8 byte mid-file does not poison
    /// the tail. NUCLEUS-CHAIN-RESTART-SEAM f1 (2026-07-03).
    fn read_tail_hash(path: &Path) -> Option<String> {
        use std::io::{Read, Seek, SeekFrom};
        const TAIL_BUF_SIZE: u64 = 65536; // 64 KB — large enough for any event line

        let mut f = fs::File::open(path).ok()?;
        let file_len = f.metadata().ok()?.len();
        if file_len == 0 {
            return None;
        }
        // Seek to TAIL_BUF_SIZE bytes from end (or start if file is smaller)
        let seek_pos = file_len.saturating_sub(TAIL_BUF_SIZE);
        f.seek(SeekFrom::Start(seek_pos)).ok()?;
        let mut buf = vec![0u8; (file_len - seek_pos) as usize];
        f.read_exact(&mut buf).ok()?;
        // Read lossy: a bad byte mid-file (e.g. from an earlier crash) no longer
        // prevents tail parsing.
        let tail = String::from_utf8_lossy(&buf);
        // Walk from last non-empty line backward to find the last JSON line
        for line in tail.lines().rev() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(parsed) = serde_json::from_str::<CanonicalEvent>(trimmed) {
                return parsed.hash;
            }
        }
        None
    }

    /// Append an event. Sets prev_hash + hash + algedonic_seq automatically.
    /// Returns the computed hash so callers can verify.
    /// NUCLEUS-CHAIN-RESTART-SEAM (f2): if the chain has a restart seam (file had content
    /// but tail hash was unreadable at init), the FIRST emit() emits a chain_seam marker
    /// event BEFORE the requested event, so the restart boundary is self-documenting
    /// machine-readable evidence for the triage (TRIAGE-EVIDENCE-RULE closes merkle seam
    /// findings against chain_seam + services.active_since).
    pub fn emit(&self, mut event: CanonicalEvent) -> std::io::Result<String> {
        let mut st = self.inner.lock().expect("ChainState lock poisoned");

        // ⚠ NO recursive self.emit() calls — Mutex is non-reentrant (std::sync::Mutex).
        // Inline the chain_seam write directly instead.

        // ── Chain seam emission (first emit after restart with unreadable tail) ──
        if st.needs_seam_event {
            st.needs_seam_event = false;
            let file_len = fs::metadata(&st.disk_path).map(|m| m.len()).unwrap_or(0);
            eprintln!(
                "[chain_seam] restart seam detected — file has {} bytes with no readable tail hash. \
                 Emitting chain_seam marker event before first {} event.",
                file_len, event.event_type
            );
            // Build the seam event as a raw Value to avoid CanonicalEvent construction.
            let seam_line = serde_json::json!({
                "ts": Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true),
                "system_id": event.system_id,
                "event_type": "chain_seam",
                "status": "ok",
                "signal_status": "resolved",
                "duration_s": 0.0,
                "metrics": {
                    "reason": "tail_hash_unreadable",
                    "prior_file_len": file_len,
                },
                "chain_format_version": 2,
                "prev_hash": st.last_hash,
            });
            let mut seam_line_str = serde_json::to_string(&seam_line)
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
            // Compute hash and append it (hash is computed over the line WITHOUT the hash field)
            use sha2::Digest;
            let seam_hash = hex::encode(Sha256::digest(seam_line_str.as_bytes()));
            // Re-serialize with hash field appended
            let seam_obj = serde_json::from_str::<serde_json::Value>(&seam_line_str)
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
            let mut with_hash = seam_obj;
            if let Some(obj) = with_hash.as_object_mut() {
                obj.insert("hash".into(), serde_json::Value::String(seam_hash.clone()));
            }
            let full_line = serde_json::to_string(&with_hash)
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
            // Write to tmpfs
            {
                let mut f = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&st.tmpfs_path)?;
                writeln!(f, "{}", full_line)?;
                f.sync_data()?;
            }
            st.last_hash = Some(seam_hash);
            eprintln!("[chain_seam] seam event emitted (hash={})", st.last_hash.as_deref().unwrap_or("?"));
        }

        // Algedonic counter: bump on CONSEQUENTIAL events. Semantic
        // extension (Annex B G-K.2): the counter no longer means strictly
        // "algedonic emissions" but rather "events the loop registered as
        // an actual signal/action", which currently is:
        //   - any `algedonic_emit` (the original meaning), AND
        //   - any `param_change` with status="ok" AND non-empty
        //     metrics.changed_keys (i.e. a real apply, not a noop).
        // Other event types (kernel_tick, invariant_check, s4-analysis,
        // noop param_change) carry algedonic_seq=0. This gives the chain
        // a single monotonic ordering over the events that *changed
        // something*, which is what audit tools (k_phi_down_meter, dashboards)
        // can use to count loop closings without re-parsing the metrics blob.
        let is_consequential_param_change = event.event_type == "param_change"
            && event.status == "ok"
            && event.metrics.get("changed_keys")
                .and_then(|v| v.as_array())
                .map(|a| !a.is_empty())
                .unwrap_or(false);
        if event.event_type == "algedonic_emit" || is_consequential_param_change {
            st.algedonic_counter = st.algedonic_counter.wrapping_add(1);
            event.algedonic_seq = st.algedonic_counter;
        } else {
            event.algedonic_seq = 0;
        }

        // Set timestamp if not provided.
        if event.ts.is_empty() {
            event.ts = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, true);
        }

        // Wire previous hash + compute own hash.
        // Task #112: writer is now v2 — set chain_format_version and use
        // the byte-stable canonical_hash. Verifiers must dispatch via
        // expected_hash() / hash_is_intact_v_aware(), which falls back to
        // compute_hash for v1 / absent-version events (legacy chain entries).
        event.prev_hash = st.last_hash.clone();
        event.chain_format_version = Some(2.to_string());
        let h = event.canonical_hash();
        event.hash = Some(h.clone());

        // Serialize + append to tmpfs (single line).
        let line = serde_json::to_string(&event)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        let mut f = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&st.tmpfs_path)?;
        writeln!(f, "{}", line)?;
        f.sync_data()?; // fsync on tmpfs = ~3µs

        st.last_hash = Some(h.clone());
        Ok(h)
    }

    /// Convenience: emit a minimal kernel_tick event.
    pub fn emit_kernel_tick(
        &self,
        system_id: &str,
        metrics: serde_json::Value,
    ) -> std::io::Result<String> {
        let ev = CanonicalEvent {
            ts: String::new(),
            system_id: system_id.to_string(),
            event_type: "kernel_tick".to_string(),
            status: "ok".to_string(),
            signal_status: "resolved".to_string(),
            duration_s: 0.0,
            metrics,
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        self.emit(ev)
    }

    /// Background flush: copy any new bytes from tmpfs to disk every FLUSH_INTERVAL_MS.
    /// Called once from an async runtime.
    pub fn start_flush_task(&self) -> tokio::task::JoinHandle<()> {
        let state = self.inner.clone();
        tokio::spawn(async move {
            let mut interval = time::interval(Duration::from_millis(FLUSH_INTERVAL_MS));
            // Track bytes flushed so we only copy the delta.
            let mut bytes_flushed: u64 = 0;

            loop {
                interval.tick().await;
                let (src, dst) = {
                    let st = state.lock().expect("ChainState lock poisoned (flush)");
                    (st.tmpfs_path.clone(), st.disk_path.clone())
                };
                // If src and dst are the same (fallback), nothing to do.
                if src == dst {
                    continue;
                }
                if let Err(e) = Self::flush_delta(&src, &dst, &mut bytes_flushed).await {
                    eprintln!("[telemetry_canonical] flush error: {}", e);
                }
            }
        })
    }

    /// Atomic flush: write delta to .pending (fsync), then O_APPEND to dst (fsync),
    /// then remove .pending. The .pending file acts as a WAL: if the process crashes
    /// between steps 2-3, the .pending survives and is replayed on next startup.
    async fn flush_delta(
        src: &Path,
        dst: &Path,
        bytes_flushed: &mut u64,
    ) -> std::io::Result<()> {
        use tokio::fs as afs;
        use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt, SeekFrom};

        let meta = afs::metadata(src).await;
        let src_size = match meta {
            Ok(m) => m.len(),
            Err(_) => return Ok(()), // tmpfs file not created yet
        };

        if src_size <= *bytes_flushed {
            return Ok(()); // nothing new
        }

        let mut src_f = afs::OpenOptions::new().read(true).open(src).await?;
        src_f.seek(SeekFrom::Start(*bytes_flushed)).await?;
        let mut buf = Vec::with_capacity((src_size - *bytes_flushed) as usize);
        src_f.read_to_end(&mut buf).await?;
        if buf.is_empty() {
            return Ok(());
        }

        // ── WAL-atomic write ──────────────────────────────────────────
        // Step 1: write delta to .pending on the same filesystem as dst
        let pending = dst.with_extension("jsonl.pending");
        {
            let mut p_f = afs::OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(&pending)
                .await?;
            p_f.write_all(&buf).await?;
            p_f.sync_data().await?; // delta is durable on disk
        } // p_f dropped, fd closed

        // Step 2: O_APPEND .pending content to dst, then fsync
        let mut dst_f = afs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(dst)
            .await?;
        dst_f.write_all(&buf).await?;
        dst_f.sync_data().await?; // dst is durable on disk

        // Step 3: remove .pending (WAL committed)
        let _ = afs::remove_file(&pending).await;
        // ── end atomic ─────────────────────────────────────────────────

        // Advance by what we ACTUALLY read, never by the size we sampled before
        // reading. `src_size` comes from a metadata() call taken BEFORE the
        // seek+read_to_end below; the kernel keeps appending to tmpfs while we
        // read, so read_to_end() consumes up to the CURRENT end — strictly more
        // than `src_size - bytes_flushed` whenever an event lands in that window.
        // Advancing the cursor to the stale `src_size` left that surplus unmarked,
        // so the NEXT flush re-read it and appended it to dst a second time.
        //
        // That is the origin of the 681 malformed lines in the canonical chain
        // (measured 2026-07-24): 679 of them are an exact SUFFIX of the line
        // before, duplicated at a uniformly random fraction (0.002–0.998 of the
        // preceding line) — precisely the size of whatever was written during the
        // race. Not torn writes, not embedded newlines: a re-appended overlap.
        *bytes_flushed += buf.len() as u64;
        Ok(())
    }

    /// Read total bytes written to tmpfs (for tests/monitoring).
    pub fn tmpfs_size(&self) -> u64 {
        let st = self.inner.lock().expect("lock");
        fs::metadata(&st.tmpfs_path).map(|m| m.len()).unwrap_or(0)
    }

    /// Current Merkle chain head (None before the first event). PROD-A1b checkpoints sign THIS.
    pub fn head_hash(&self) -> Option<String> {
        self.inner.lock().expect("ChainState lock poisoned (head)").last_hash.clone()
    }

    /// PROD-A1b — periodic Ed25519 witness checkpoint over the chain head, appended to a sidecar
    /// JSONL (`events.witness.jsonl`). Sidecar by design (witness.rs §Design): `CanonicalEvent` is
    /// NOT mutated. Each `interval`, if the head advanced since the last checkpoint, mint a
    /// `WitnessStatement` over the head's canonical_hash (signature is over the 32 hash BYTES, so it
    /// is toolchain-version-independent) and append it. Any holder of the pubkey can then prove the
    /// chain at that moment had not been retroactively tampered with — upgrading the φ↑ cert from
    /// chain-linkage to full attestation. Failures are logged, NEVER fatal (the witness is an
    /// auditor; its own failure must not halt the productive nucleus — same C5 spirit as the host
    /// attester [PROD-A1a]).
    pub fn start_witness_checkpoint_task(
        &self,
        sk: ed25519_dalek::SigningKey,
        issuer: String,
        interval: Duration,
        sidecar_path: PathBuf,
    ) -> tokio::task::JoinHandle<()> {
        let state = self.inner.clone();
        tokio::spawn(async move {
            let mut ticker = time::interval(interval);
            let mut last_checkpointed: Option<String> = None;
            loop {
                ticker.tick().await;
                let head = {
                    let st = state.lock().expect("ChainState lock poisoned (witness)");
                    st.last_hash.clone()
                };
                let head = match head {
                    Some(h) => h,
                    None => continue, // no events yet — nothing to attest
                };
                if last_checkpointed.as_ref() == Some(&head) {
                    continue; // chain has not advanced — don't mint a redundant statement
                }
                let ts = Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
                match vsf_agent::witness::mint_statement(&sk, &issuer, &head, &ts) {
                    Ok(stmt) => match serde_json::to_string(&stmt) {
                        Ok(line) => match Self::append_line(&sidecar_path, &line) {
                            Ok(()) => last_checkpointed = Some(head),
                            Err(e) => eprintln!("[witness] sidecar append failed: {}", e),
                        },
                        Err(e) => eprintln!("[witness] serialize failed: {}", e),
                    },
                    Err(e) => eprintln!("[witness] mint failed: {}", e),
                }
            }
        })
    }

    fn append_line(path: &Path, line: &str) -> std::io::Result<()> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let mut f = OpenOptions::new().create(true).append(true).open(path)?;
        writeln!(f, "{}", line)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dirs() -> (String, String) {
        let base = std::env::temp_dir().join(format!("vsf-test-{}", std::process::id()));
        let tmpfs = base.join("tmpfs");
        let disk = base.join("disk");
        let _ = fs::create_dir_all(&tmpfs);
        let _ = fs::create_dir_all(&disk);
        (tmpfs.to_string_lossy().to_string(), disk.to_string_lossy().to_string())
    }

    #[test]
    fn hash_chain_is_consistent() {
        let (tmpfs, disk) = temp_dirs();
        let tel = CanonicalTelemetry::with_roots("test-chain", &tmpfs, &disk).unwrap();
        let h1 = tel.emit_kernel_tick("test-chain", serde_json::json!({"n": 1})).unwrap();
        let h2 = tel.emit_kernel_tick("test-chain", serde_json::json!({"n": 2})).unwrap();
        assert_ne!(h1, h2);
        // last_hash should now be h2
        let st = tel.inner.lock().unwrap();
        assert_eq!(st.last_hash.as_deref(), Some(h2.as_str()));
    }

    #[test]
    fn algedonic_counter_bumps_only_on_algedonic_events() {
        let (tmpfs, disk) = temp_dirs();
        let tel = CanonicalTelemetry::with_roots("test-alg", &tmpfs, &disk).unwrap();
        let mut e = CanonicalEvent {
            ts: String::new(),
            system_id: "test-alg".to_string(),
            event_type: "kernel_tick".to_string(),
            status: "ok".to_string(),
            signal_status: "resolved".to_string(),
            duration_s: 0.0,
            metrics: serde_json::json!({}),
            variety_delta: None,
            trust_score: None,
            algedonic_seq: 0,
            origin: None,
            chain_format_version: None,
            prev_hash: None,
            hash: None,
        };
        tel.emit(e.clone()).unwrap();
        e.event_type = "algedonic_emit".to_string();
        tel.emit(e.clone()).unwrap();
        tel.emit(e).unwrap();
        let st = tel.inner.lock().unwrap();
        assert_eq!(st.algedonic_counter, 2);
    }

    #[test]
    fn tail_read_equivalence_vs_full_read() {
        // f3: tail-read returns the same last hash as full-read. Write events directly
        // to disk path (the function reads from canonical events.jsonl on disk).
        let dir = std::env::temp_dir().join(format!("vsf-tail-eq-{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("equivalence.jsonl");
        // Write a real CanonicalEvent-serializable line
        let line1 = "{\"ts\":\"2026-01-01T00:00:00Z\",\"system_id\":\"test\",\"event_type\":\"kernel_tick\",\"status\":\"ok\",\"signal_status\":\"resolved\",\"duration_s\":0.0,\"metrics\":{},\"chain_format_version\":2,\"prev_hash\":null,\"hash\":\"aaa\"}\n";
        let line2 = "{\"ts\":\"2026-01-02T00:00:00Z\",\"system_id\":\"test\",\"event_type\":\"kernel_tick\",\"status\":\"ok\",\"signal_status\":\"resolved\",\"duration_s\":0.0,\"metrics\":{},\"chain_format_version\":2,\"prev_hash\":\"aaa\",\"hash\":\"bbb\"}\n";
        fs::write(&path, [line1, line2].concat()).unwrap();

        // Full read: parse last line and get hash
        let content = fs::read_to_string(&path).unwrap();
        let last_line = content.lines().rev().next().unwrap();
        let full_parsed: CanonicalEvent = serde_json::from_str(last_line).unwrap();
        let full_hash = full_parsed.hash.unwrap();

        // Tail read (bounded, seek-based)
        let tail_hash = CanonicalTelemetry::read_tail_hash(&path).unwrap();
        assert_eq!(tail_hash, full_hash, "tail-read must match full-read");
        assert_eq!(tail_hash, "bbb", "must be the second event's hash");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn tail_read_large_file_uses_bounded_read() {
        // f3: reading a large file must complete in bounded time (reads only tail 64KB)
        let dir = std::env::temp_dir().join(format!("vsf-tail-big-{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("big_events.jsonl");
        let mut f = fs::File::create(&path).unwrap();
        use std::io::Write;
        // Event 1 (near start)
        writeln!(f, "{}", "{\"ts\":\"2026-01-01T00:00:00Z\",\"system_id\":\"test\",\"event_type\":\"kernel_tick\",\"status\":\"ok\",\"signal_status\":\"resolved\",\"duration_s\":0.0,\"metrics\":{},\"chain_format_version\":2,\"prev_hash\":null,\"hash\":\"aaa\"}").unwrap();
        // 128KB of noise lines (well beyond TAIL_BUF_SIZE=65536)
        for _ in 0..2000 {
            writeln!(f, "{}", "{\"ts\":\"2026-01-01T00:01:00Z\",\"system_id\":\"test\",\"event_type\":\"kernel_tick\",\"status\":\"ok\",\"signal_status\":\"resolved\",\"duration_s\":0.0,\"metrics\":{},\"chain_format_version\":2,\"prev_hash\":\"aaa\",\"hash\":\"mid\"}").unwrap();
        }
        // Event 2 (the tail)
        writeln!(f, "{}", "{\"ts\":\"2026-01-02T00:00:00Z\",\"system_id\":\"test\",\"event_type\":\"kernel_tick\",\"status\":\"ok\",\"signal_status\":\"resolved\",\"duration_s\":0.0,\"metrics\":{},\"chain_format_version\":2,\"prev_hash\":\"aaa\",\"hash\":\"bbb\"}").unwrap();
        drop(f);
        let tail_hash = CanonicalTelemetry::read_tail_hash(&path).unwrap();
        assert_eq!(tail_hash, "bbb", "tail-read must find the last event's hash in a large file");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn tail_read_invalid_utf8_mid_file_does_not_poison() {
        // f3: invalid UTF-8 bytes mid-file must not prevent reading a valid tail.
        // Uses events emitted through CanonicalTelemetry (guaranteed valid CanonicalEvent format).
        let (tmpfs, disk) = temp_dirs();
        let tel = CanonicalTelemetry::with_roots("test-utf8-poison", &tmpfs, &disk).unwrap();
        let _ = tel.emit_kernel_tick("test-utf8-poison", serde_json::json!({"n": 1})).unwrap();
        // Inject invalid UTF-8 into the tmpfs file (between event 1 and event 2)
        let tmpfs_path = tel.inner.lock().unwrap().tmpfs_path.clone();
        {
            let mut f = OpenOptions::new().append(true).open(&tmpfs_path).unwrap();
            use std::io::Write;
            f.write_all(&[0xFF, 0xFE, 0x00]).unwrap(); // 3 bytes of invalid UTF-8
            writeln!(f).unwrap();
        }
        let h2 = tel.emit_kernel_tick("test-utf8-poison", serde_json::json!({"n": 2})).unwrap();
        // Now read the disk path (the function reads from disk_path). But disk is flushed
        // asynchronously — copy tmpfs to disk manually for this test
        let disk_path = tel.inner.lock().unwrap().disk_path.clone();
        fs::copy(&tmpfs_path, &disk_path).unwrap();
        drop(tel);
        let tail_hash = CanonicalTelemetry::read_tail_hash(&disk_path).unwrap();
        assert_eq!(tail_hash, h2, "invalid UTF-8 mid-file must not poison tail parsing");
    }

    #[test]
    fn tail_read_empty_file_returns_none() {
        // f3: empty file → None (no seam, just fresh chain)
        let dir = std::env::temp_dir().join(format!("vsf-tail-empty-{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        let path = dir.join("empty.jsonl");
        fs::write(&path, "").unwrap();
        assert!(CanonicalTelemetry::read_tail_hash(&path).is_none());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn chain_seam_emitted_when_tail_unreadable() {
        // NUCLEUS-CHAIN-RESTART-SEAM f2: verify seam event is emitted when init finds
        // file with content but no readable tail hash.
        let (tmpfs, disk) = temp_dirs();
        // Pre-populate disk with a single line that is NOT a valid CanonicalEvent
        // (e.g., a raw JSON with no hash field — simulates a corrupted tail).
        let disk_path = std::path::Path::new(&disk).join("vsf_nucleus").join("events.jsonl");
        let _ = fs::create_dir_all(disk_path.parent().unwrap());
        fs::write(&disk_path, "{\"corrupt\": true}\n").unwrap();
        // Now init — should detect seam and emit chain_seam on first emit
        let tel = CanonicalTelemetry::with_roots("vsf_nucleus", &tmpfs, &disk).unwrap();
        {
            let st = tel.inner.lock().unwrap();
            assert!(st.needs_seam_event, "chain seam must be detected");
        }
        // First emit should produce a chain_seam event followed by the real event
        let h1 = tel.emit_kernel_tick("vsf_nucleus", serde_json::json!({"n": 1})).unwrap();
        {
            let st = tel.inner.lock().unwrap();
            assert!(!st.needs_seam_event, "seam flag cleared after emit");
            assert_eq!(st.last_hash.as_deref(), Some(h1.as_str()));
        }
        // Events go to tmpfs first (flushed async to disk). Check tmpfs for seam.
        let tmpfs_path = tel.inner.lock().unwrap().tmpfs_path.clone();
        let content = fs::read_to_string(&tmpfs_path).unwrap();
        let lines: Vec<&str> = content.lines().collect();
        assert!(lines.len() >= 2, "should have seam + first event, got {} lines", lines.len());
        // The first line should be a chain_seam
        let seam: serde_json::Value = serde_json::from_str(lines[0]).unwrap();
        assert_eq!(seam["event_type"], "chain_seam");
        assert!(seam.get("hash").and_then(|v| v.as_str()).is_some(), "seam must have a hash");
    }

    #[test]
    fn witness_checkpoint_signs_and_verifies_head() {
        // PROD-A1b: head_hash() exposes the chain tail; a minted statement over it verifies.
        let (tmpfs, disk) = temp_dirs();
        let tel = CanonicalTelemetry::with_roots("test-witness", &tmpfs, &disk).unwrap();
        let h = tel.emit_kernel_tick("test-witness", serde_json::json!({"n": 1})).unwrap();
        assert_eq!(tel.head_hash().as_deref(), Some(h.as_str()));

        // Use the real A1b key path (also exercises load_or_generate_signing_key).
        let key_path = std::path::Path::new(&disk).join("witness_key.ed25519");
        let sk = vsf_agent::witness::load_or_generate_signing_key(&key_path).unwrap();
        let stmt = vsf_agent::witness::mint_statement(&sk, "test-witness", &h, "2026-06-08T00:00:00Z").unwrap();
        vsf_agent::witness::verify_statement(&stmt, &sk.verifying_key()).unwrap();
        assert_eq!(stmt.event_canonical_hash, h);

        // A tampered head must NOT verify against the same statement.
        let mut bad = stmt.clone();
        bad.event_canonical_hash.replace_range(0..1, if h.starts_with('0') { "1" } else { "0" });
        assert!(vsf_agent::witness::verify_statement(&bad, &sk.verifying_key()).is_err());
    }
}
