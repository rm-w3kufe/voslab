//! Ed25519 witness statement minting and verification
//!
//! Provides cryptographic witness statements for canonical events using Ed25519 signatures.
//! Supports key generation, loading, statement minting, and verification.

use ed25519_dalek::{SigningKey, VerifyingKey, Signature, Signer, Verifier};
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;
use rand::RngCore;

#[derive(Error, Debug)]
pub enum WitnessError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("Key format error: {0}")]
    KeyFormat(String),
    #[error("Signature verification failed")]
    VerificationFailed,
}

/// Witness statement with Ed25519 signature
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WitnessStatement {
    pub issuer: String,
    pub event_hash: String,
    pub timestamp: String,
    pub signature: String,  // hex-encoded Ed25519 signature
}

/// Load or generate Ed25519 signing key from file
///
/// If the file exists, loads the key. Otherwise, generates a new key and saves it.
///
/// # Arguments
/// * `key_path` - Path to the key file (binary format)
///
/// # Returns
/// * `Ok(SigningKey)` - Loaded or generated signing key
/// * `Err(WitnessError)` - IO or format error
pub fn load_or_generate_signing_key(key_path: &Path) -> Result<SigningKey, WitnessError> {
    if key_path.exists() {
        // Load existing key
        let bytes = std::fs::read(key_path)?;
        
        if bytes.len() != 32 {
            return Err(WitnessError::KeyFormat(format!(
                "Invalid key length: expected 32 bytes, got {}",
                bytes.len()
            )));
        }
        
        let mut key_bytes = [0u8; 32];
        key_bytes.copy_from_slice(&bytes);
        Ok(SigningKey::from_bytes(&key_bytes))
    } else {
        // Generate new key
        let mut rng = rand::thread_rng();
        let mut key_bytes = [0u8; 32];
        rng.fill_bytes(&mut key_bytes);
        let signing_key = SigningKey::from_bytes(&key_bytes);
        
        // Save to file
        if let Some(parent) = key_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(key_path, signing_key.to_bytes())?;
        
        Ok(signing_key)
    }
}

/// Mint a witness statement for an event
///
/// Creates a signed witness statement binding an event hash to a timestamp.
///
/// # Arguments
/// * `sk` - Signing key
/// * `issuer` - Identifier of the witness (e.g., "vsf-nucleus")
/// * `event_hash` - SHA256 hash of the canonical event
/// * `timestamp` - ISO 8601 timestamp (e.g., "2026-06-08T00:00:00Z")
///
/// # Returns
/// * `Ok(WitnessStatement)` - Signed witness statement
pub fn mint_statement(
    sk: &SigningKey,
    issuer: &str,
    event_hash: &str,
    timestamp: &str,
) -> Result<WitnessStatement, WitnessError> {
    // Create message to sign: issuer || event_hash || timestamp
    let message = format!("{}|{}|{}", issuer, event_hash, timestamp);
    let signature = sk.sign(message.as_bytes());
    
    Ok(WitnessStatement {
        issuer: issuer.to_string(),
        event_hash: event_hash.to_string(),
        timestamp: timestamp.to_string(),
        signature: hex::encode(signature.to_bytes()),
    })
}

/// Verify a witness statement
///
/// Checks that the signature is valid for the statement's issuer, event_hash, and timestamp.
///
/// # Arguments
/// * `stmt` - Witness statement to verify
/// * `vk` - Verifying key (public key)
///
/// # Returns
/// * `Ok(())` - Verification succeeded
/// * `Err(WitnessError)` - Verification failed
pub fn verify_statement(stmt: &WitnessStatement, vk: &VerifyingKey) -> Result<(), WitnessError> {
    // Reconstruct message
    let message = format!("{}|{}|{}", stmt.issuer, stmt.event_hash, stmt.timestamp);
    
    // Decode signature
    let sig_bytes = hex::decode(&stmt.signature)
        .map_err(|e| WitnessError::KeyFormat(format!("Invalid hex: {}", e)))?;
    
    if sig_bytes.len() != 64 {
        return Err(WitnessError::KeyFormat(format!(
            "Invalid signature length: expected 64 bytes, got {}",
            sig_bytes.len()
        )));
    }
    
    let mut sig_array = [0u8; 64];
    sig_array.copy_from_slice(&sig_bytes);
    let signature = Signature::from_bytes(&sig_array);
    
    // Verify signature
    vk.verify(message.as_bytes(), &signature)
        .map_err(|_| WitnessError::VerificationFailed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_key_generation_and_loading() {
        let temp_dir = TempDir::new().unwrap();
        let key_path = temp_dir.path().join("test.key");
        
        // Generate key
        let sk1 = load_or_generate_signing_key(&key_path).unwrap();
        
        // Load key
        let sk2 = load_or_generate_signing_key(&key_path).unwrap();
        
        // Keys should be identical
        assert_eq!(sk1.to_bytes(), sk2.to_bytes());
    }

    #[test]
    fn test_mint_and_verify() {
        let mut rng = rand::thread_rng();
        let mut key_bytes = [0u8; 32];
        rng.fill_bytes(&mut key_bytes);
        let sk = SigningKey::from_bytes(&key_bytes);
        let vk = sk.verifying_key();
        
        let stmt = mint_statement(&sk, "test-issuer", "abc123", "2026-06-08T00:00:00Z").unwrap();
        
        // Valid signature should verify
        assert!(verify_statement(&stmt, &vk).is_ok());
        
        // Tampered signature should fail
        let mut bad_stmt = stmt.clone();
        bad_stmt.event_hash = "tampered".to_string();
        assert!(verify_statement(&bad_stmt, &vk).is_err());
    }
}
