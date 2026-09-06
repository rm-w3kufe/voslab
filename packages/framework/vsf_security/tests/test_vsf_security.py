"""tests/test_vsf_security.py — Tests for vsf-security."""

import os
import pytest
from vsf_security import (
    SecurityConfig,
    NATSAuth,
    generate_token,
    hash_token,
)


def test_security_config_defaults():
    """SecurityConfig has correct defaults."""
    config = SecurityConfig()
    assert config.nats_token is None
    assert config.nats_user is None
    assert config.nats_password is None
    assert config.enable_tls is False
    assert config.ca_cert_path is None


def test_security_config_custom():
    """SecurityConfig accepts custom values."""
    config = SecurityConfig(
        nats_token="test-token",
        nats_user="user",
        nats_password="pass",
        enable_tls=True,
        ca_cert_path="/path/to/ca.pem",
    )
    assert config.nats_token == "test-token"
    assert config.nats_user == "user"
    assert config.nats_password == "pass"
    assert config.enable_tls is True
    assert config.ca_cert_path == "/path/to/ca.pem"


def test_nats_auth_from_env():
    """NATSAuth creates from environment variables."""
    os.environ["NATS_TOKEN"] = "env-token"
    try:
        auth = NATSAuth.from_env()
        assert auth.config.nats_token == "env-token"
    finally:
        del os.environ["NATS_TOKEN"]


def test_nats_auth_get_token():
    """NATSAuth returns token."""
    auth = NATSAuth(SecurityConfig(nats_token="my-token"))
    assert auth.get_token() == "my-token"


def test_nats_auth_get_credentials_token():
    """NATSAuth returns credentials with token."""
    auth = NATSAuth(SecurityConfig(nats_token="my-token"))
    creds = auth.get_credentials()
    assert creds["token"] == "my-token"
    assert "user" not in creds


def test_nats_auth_get_credentials_user_pass():
    """NATSAuth returns credentials with user/password."""
    auth = NATSAuth(SecurityConfig(nats_user="user", nats_password="pass"))
    creds = auth.get_credentials()
    assert creds["user"] == "user"
    assert creds["password"] == "pass"
    assert "token" not in creds


def test_nats_auth_get_credentials_tls():
    """NATSAuth returns credentials with TLS."""
    auth = NATSAuth(SecurityConfig(
        nats_token="token",
        enable_tls=True,
        ca_cert_path="/path/to/ca.pem",
    ))
    creds = auth.get_credentials()
    assert creds["tls"] is True
    assert creds["ca_cert"] == "/path/to/ca.pem"


def test_nats_auth_validate_connection_token():
    """NATSAuth validates connection with token."""
    auth = NATSAuth()
    assert auth.validate_connection({"token": "my-token"}) is True


def test_nats_auth_validate_connection_user_pass():
    """NATSAuth validates connection with user/password."""
    auth = NATSAuth()
    assert auth.validate_connection({"user": "user", "password": "pass"}) is True


def test_nats_auth_validate_connection_no_auth():
    """NATSAuth rejects connection without auth."""
    auth = NATSAuth()
    assert auth.validate_connection({}) is False


def test_nats_auth_validate_connection_partial_user():
    """NATSAuth rejects connection with user but no password."""
    auth = NATSAuth()
    assert auth.validate_connection({"user": "user"}) is False


def test_generate_token():
    """generate_token returns secure token."""
    token = generate_token()
    assert len(token) == 64  # 32 bytes = 64 hex chars


def test_generate_token_custom_length():
    """generate_token accepts custom length."""
    token = generate_token(16)
    assert len(token) == 32  # 16 bytes = 32 hex chars


def test_hash_token():
    """hash_token returns SHA256 hash."""
    token = "test-token"
    hashed = hash_token(token)
    assert len(hashed) == 64  # SHA256 = 64 hex chars
    assert hashed != token


def test_hash_token_deterministic():
    """hash_token is deterministic."""
    token = "test-token"
    assert hash_token(token) == hash_token(token)
