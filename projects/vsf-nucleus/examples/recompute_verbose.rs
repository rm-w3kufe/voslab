//! Same as recompute, but ALSO prints the exact serialized bytes that go
//! into compute_hash. This lets us byte-diff what the recomputer hashes vs
//! the line as persisted on disk (with hash field excised) — the difference
//! reveals what the WRITER must have hashed to produce the stored hash.

use std::env;
use std::fs;
use vsf_agent::CanonicalEvent;

fn main() {
    let path = env::args().nth(1).expect("usage: recompute_verbose <path>");
    let raw = fs::read_to_string(&path).expect("read file");
    let line = raw.lines().next().expect("at least one line").trim().to_string();

    let event: CanonicalEvent = serde_json::from_str(&line).expect("valid CanonicalEvent");
    let stored = event.hash.clone().unwrap_or_default();
    let recomputed = event.compute_hash();

    // What the recomputer hashes:
    let mut without_hash = event.clone();
    without_hash.hash = None;
    let recomp_serialized = serde_json::to_string(&without_hash).expect("ser");

    // Print
    println!("stored:       {}", stored);
    println!("recomputed:   {}", recomputed);
    println!("match:        {}", stored == recomputed);
    println!();
    println!("RECOMPUTER bytes (what compute_hash hashed):");
    println!("{}", recomp_serialized);
    println!();
    println!("PERSISTED LINE (with hash=stored):");
    println!("{}", line);
}
