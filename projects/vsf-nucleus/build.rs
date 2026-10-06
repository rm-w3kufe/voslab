// build.rs — computes COVENANT_SHA256 at compile time and injects as env var
// This runs before compilation. The covenant hash becomes an immutable constant
// in the binary — cannot be changed without recompiling (requires S5 approval).

use sha2::{Sha256, Digest};

fn main() {
    let covenant_path = "../../docs/governance/covenant.vsm";

    let covenant = std::fs::read_to_string(covenant_path)
        .unwrap_or_else(|_| panic!(
            "covenant.vsm not found at {} — build aborted. \
             A binary without its constitution must not compile.",
            covenant_path
        ));

    let mut hasher = Sha256::new();
    hasher.update(covenant.as_bytes());
    let hash = hex::encode(hasher.finalize());

    println!("cargo:rustc-env=COVENANT_SHA256={}", hash);
    println!("cargo:rerun-if-changed={}", covenant_path);

    eprintln!("[build] covenant.vsm hash: sha256:{}", &hash[..16]);
}
