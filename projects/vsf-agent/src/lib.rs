//! vsf-agent: Shared VSF primitives for agent communication
//!
//! This crate provides:
//! - CanonicalEvent: shared event structure for φ↑ telemetry
//! - nats::connect: NATS connection helper with authentication
//! - witness: Ed25519 witness statement minting/verification

pub mod nats;
pub mod witness;

use serde::{Deserialize, Serialize};

/// Canonical event structure matching connection_schema.json v0.2.1 §upward_channel.
/// Single source of truth shared with s3-star auditor.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CanonicalEvent {
    pub ts: String,
    pub system_id: String,
    pub event_type: String,
    pub status: String,
    pub signal_status: String,
    pub duration_s: f64,
    pub metrics: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prev_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub variety_delta: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub trust_score: Option<f64>,
    pub algedonic_seq: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub origin: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chain_format_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hash: Option<String>,
}

impl CanonicalEvent {
    /// Compute SHA256 hash of the event (excluding prev_hash for chain computation)
    /// Used for v1 legacy chain entries
    pub fn compute_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        
        let mut hasher = Sha256::new();
        hasher.update(self.ts.as_bytes());
        hasher.update(self.system_id.as_bytes());
        hasher.update(self.event_type.as_bytes());
        hasher.update(self.status.as_bytes());
        hasher.update(self.signal_status.as_bytes());
        hasher.update(self.duration_s.to_string().as_bytes());
        hasher.update(serde_json::to_string(&self.metrics).unwrap().as_bytes());
        
        if let Some(ref vd) = self.variety_delta {
            hasher.update(vd.to_string().as_bytes());
        }
        if let Some(ref ts) = self.trust_score {
            hasher.update(ts.to_string().as_bytes());
        }
        hasher.update(self.algedonic_seq.to_string().as_bytes());
        if let Some(ref origin) = self.origin {
            hasher.update(origin.as_bytes());
        }
        
        hex::encode(hasher.finalize())
    }

    /// Compute byte-stable canonical hash for v2 chain entries
    /// Includes prev_hash and chain_format_version for deterministic serialization
    pub fn canonical_hash(&self) -> String {
        use sha2::{Sha256, Digest};
        
        let mut hasher = Sha256::new();
        
        // Deterministic field order for byte-stable hashing
        hasher.update(self.ts.as_bytes());
        hasher.update(b"|");
        hasher.update(self.system_id.as_bytes());
        hasher.update(b"|");
        hasher.update(self.event_type.as_bytes());
        hasher.update(b"|");
        hasher.update(self.status.as_bytes());
        hasher.update(b"|");
        hasher.update(self.signal_status.as_bytes());
        hasher.update(b"|");
        hasher.update(self.duration_s.to_string().as_bytes());
        hasher.update(b"|");
        hasher.update(serde_json::to_string(&self.metrics).unwrap().as_bytes());
        hasher.update(b"|");
        
        if let Some(ref vd) = self.variety_delta {
            hasher.update(vd.to_string().as_bytes());
        }
        hasher.update(b"|");
        
        if let Some(ref ts) = self.trust_score {
            hasher.update(ts.to_string().as_bytes());
        }
        hasher.update(b"|");
        
        hasher.update(self.algedonic_seq.to_string().as_bytes());
        hasher.update(b"|");
        
        if let Some(ref origin) = self.origin {
            hasher.update(origin.as_bytes());
        }
        hasher.update(b"|");
        
        if let Some(ref cfv) = self.chain_format_version {
            hasher.update(cfv.as_bytes());
        }
        hasher.update(b"|");
        
        if let Some(ref prev) = self.prev_hash {
            hasher.update(prev.as_bytes());
        }
        
        hex::encode(hasher.finalize())
    }
}
