//! Forensic recompute — but compiled INSIDE vsf-nucleus so it uses the same
//! serde_json version as the running prod nucleus binary on LXC 101.
//!
//! Same logic as vsf-agent/examples/recompute.rs. If this binary produces a
//! DIFFERENT recomputed hash than the vsf-agent example, the divergence is
//! a serde_json version-drift artefact (i.e., not a tamper).

use std::env;
use std::fs;
use std::process::ExitCode;
use vsf_agent::CanonicalEvent;

fn main() -> ExitCode {
    let path = env::args().nth(1).expect("usage: recompute <path>");
    let raw = fs::read_to_string(&path).expect("read file");
    let line = raw.lines().next().expect("at least one line");

    let event: CanonicalEvent = serde_json::from_str(line).expect("valid CanonicalEvent");
    let stored = event.hash.clone().unwrap_or_default();
    let recomputed = event.compute_hash();

    println!("# nucleus-side recompute — {}", path);
    println!("  stored:     {}", stored);
    println!("  recomputed: {}", recomputed);
    if stored == recomputed { ExitCode::SUCCESS } else { ExitCode::from(1) }
}
