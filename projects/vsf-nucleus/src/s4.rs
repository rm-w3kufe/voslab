// src/s4.rs — S4 cognitive layer: Ollama/Qwen + covenant embedding
// PSI/1.0: Perimeter of Stability Intervention
// @ref docs/spec/s4_integration/spec.vsm

use sha2::{Sha256, Digest};

// ─── COVENANT (compile-time embedding) ───────────────────────────────────────
// Embedded at build time via include_str!() — not read from disk at runtime.
// Cannot be bypassed without recompiling (requires S5 approval — D_deploy-3).

const COVENANT: &str = include_str!("../../../docs/governance/covenant.vsm");
const COVENANT_HASH: &str = env!("COVENANT_SHA256");

pub fn verify_covenant() -> bool {
    let mut hasher = Sha256::new();
    hasher.update(COVENANT.as_bytes());
    hex::encode(hasher.finalize()) == COVENANT_HASH
}

pub fn covenant_hash_short() -> &'static str {
    &COVENANT_HASH[..16]
}

// ─── PSI SIGNAL ───────────────────────────────────────────────────────────────

#[derive(Debug, serde::Serialize)]
pub struct AngustiaSignal {
    pub tick:          u32,
    pub stasis_cos:    f64,
    pub level:         &'static str,   // "L1" | "L2" | "L3"
    pub dcos_dt:       f64,            // positive = recovering
    pub viable_full:   bool,
    pub entropy_phase: String,
}

impl AngustiaSignal {
    pub fn classify(stasis_cos: f64, viable_full: bool) -> Option<&'static str> {
        if !viable_full || stasis_cos < 0.72 { return Some("L3"); }
        if stasis_cos < crate::calibration::THETA_PSI { return Some("L2"); }  // dedup (EXP-TP-01)
        if stasis_cos < 0.90               { return Some("L1"); }
        None
    }
}

// ─── S4 SUGGESTION ───────────────────────────────────────────────────────────

#[derive(Debug)]
pub struct S4Suggestion {
    pub action_type: String,
    pub target:      String,
    pub rationale:   String,
}

impl S4Suggestion {
    const AUTHORIZED: &'static [&'static str] = &[
        "reduce_cpu_weight",
        "request_cooldown",
        "defer_task",
        "escalate_human",
    ];

    fn parse(text: &str) -> Option<Self> {
        let parts: Vec<&str> = text.trim().splitn(3, '|').collect();
        if parts.len() < 3 { return None; }
        let action_type = parts[0].trim().to_string();
        let target      = parts[1].trim().to_string();
        let rationale   = parts[2].trim().to_string();
        if !Self::AUTHORIZED.contains(&action_type.as_str()) {
            eprintln!("[s4] unauthorized action rejected: {}", action_type);
            return None;
        }
        Some(S4Suggestion { action_type, target, rationale })
    }
}

// ─── S4 CLIENT ───────────────────────────────────────────────────────────────

pub struct S4Client {
    ollama_url: String,
    model:      String,
}

impl S4Client {
    pub fn new() -> Self {
        S4Client {
            ollama_url: "http://localhost:11434".to_string(),
            model:      "qwen2.5-coder:7b".to_string(),
        }
    }

    pub fn is_available(&self) -> bool {
        ureq::get(&format!("{}/api/tags", self.ollama_url))
            .timeout(std::time::Duration::from_secs(3))
            .call()
            .map(|r| r.status() == 200)
            .unwrap_or(false)
    }

    pub fn suggest(
        &self,
        state_json:   &str,
        signal:       &AngustiaSignal,
    ) -> Option<S4Suggestion> {
        assert!(verify_covenant(),
            "[s4] covenant integrity check FAILED — S4 halted. \
             Binary may have been tampered with.");

        let prompt = format!(
            "⟦ COVENANT | hash:{} | vsm-0.3 ⟧\n{}\n⟦ /COVENANT ⟧\n\n\
             Kernel state:\n{}\n\n\
             Angustia signal:\n{}\n\n\
             PSI level: {}\n\n\
             Within the covenant constraints above, suggest ONE support action.\n\
             Format: action_type | target | rationale\n\
             Authorized actions: reduce_cpu_weight, request_cooldown, defer_task, escalate_human\n\
             Do not modify policy. Do not command. Suggest only.",
            COVENANT_HASH,
            COVENANT,
            state_json,
            serde_json::to_string_pretty(signal).unwrap_or_default(),
            signal.level,
        );

        let body = serde_json::json!({
            "model":  self.model,
            "prompt": prompt,
            "stream": false,
        });

        let response = ureq::post(&format!("{}/api/generate", self.ollama_url))
            .timeout(std::time::Duration::from_secs(120))
            .send_json(body)
            .ok()?;

        let json: serde_json::Value = response.into_json().ok()?;
        let text = json["response"].as_str()?;

        eprintln!("[s4] raw response: {}", text.trim());
        S4Suggestion::parse(text)
    }

    // Write φ↓ suggestion to s4_params.json
    pub fn emit_phi_down(
        &self,
        root:       &std::path::Path,
        suggestion: &S4Suggestion,
    ) -> std::io::Result<()> {
        let path = root.join("telemetry/vsf-nucleus/s4_params.json");
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let payload = serde_json::json!({
            "action_type":    suggestion.action_type,
            "target":         suggestion.target,
            "rationale":      suggestion.rationale,
            "covenant_hash":  COVENANT_HASH,
            "timestamp":      chrono::Utc::now().to_rfc3339(),
        });
        std::fs::write(&path, serde_json::to_string_pretty(&payload)?)
    }
}

// ─── VERIFY CLI ───────────────────────────────────────────────────────────────

pub fn run_verify_covenant() {
    println!("\n⟦ vsf-nucleus --verify-covenant ⟧");
    println!("  covenant:   embedded at compile time");
    println!("  hash:       sha256:{}", COVENANT_HASH);
    println!("  size:       {} bytes", COVENANT.len());
    if verify_covenant() {
        println!("  status:     OK ✓");
    } else {
        println!("  status:     FAILED ✗ — binary may be tampered");
        std::process::exit(1);
    }
    println!("⟦ /verify-covenant ⟧\n");
}

// ─── TESTS ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn covenant_hash_valid() {
        assert!(verify_covenant(), "covenant hash mismatch at test time");
    }

    #[test]
    fn covenant_not_empty() {
        assert!(COVENANT.len() > 100, "covenant too short — may be missing");
    }

    #[test]
    fn angustia_classification() {
        assert_eq!(AngustiaSignal::classify(0.95, true),  None);
        assert_eq!(AngustiaSignal::classify(0.88, true),  Some("L1"));
        assert_eq!(AngustiaSignal::classify(0.75, true),  Some("L2"));
        assert_eq!(AngustiaSignal::classify(0.71, true),  Some("L3"));
        assert_eq!(AngustiaSignal::classify(0.80, false), Some("L3"));
    }

    #[test]
    fn suggestion_parse_authorized() {
        let s = S4Suggestion::parse("reduce_cpu_weight | kernel_01 | thermal pressure high");
        assert!(s.is_some());
        let s = s.unwrap();
        assert_eq!(s.action_type, "reduce_cpu_weight");
        assert_eq!(s.target, "kernel_01");
    }

    #[test]
    fn suggestion_parse_unauthorized_rejected() {
        let s = S4Suggestion::parse("shutdown_kernel | kernel_01 | test");
        assert!(s.is_none(), "unauthorized action must be rejected");
    }
}
