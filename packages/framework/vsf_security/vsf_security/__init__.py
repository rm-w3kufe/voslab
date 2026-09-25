"""vsf-security — Security primitives for vOSlab.

Minimal security package for NATS authentication and access control.

design: child/docs/vos_system_layer/backlogs/pending_tasks_backlog.vsm §SEC-001
"""

from __future__ import annotations

import os
import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional


@dataclass
class SecurityConfig:
    """Security configuration."""
    nats_token: str | None = None
    nats_user: str | None = None
    nats_password: str | None = None
    enable_tls: bool = False
    ca_cert_path: str | None = None


class NATSAuth:
    """NATS authentication handler.

    Usage:
        auth = NATSAuth.from_env()
        token = auth.get_token()
        if auth.validate_connection(connection_info):
            print("Authenticated")
    """

    def __init__(self, config: SecurityConfig | None = None):
        self.config = config or SecurityConfig()

    @classmethod
    def from_env(cls) -> "NATSAuth":
        """Create auth from environment variables."""
        config = SecurityConfig(
            nats_token=os.environ.get("NATS_TOKEN"),
            nats_user=os.environ.get("NATS_USER"),
            nats_password=os.environ.get("NATS_PASSWORD"),
            enable_tls=os.environ.get("NATS_TLS", "").lower() == "true",
            ca_cert_path=os.environ.get("NATS_CA_CERT"),
        )
        return cls(config)

    def get_token(self) -> str | None:
        """Get authentication token."""
        return self.config.nats_token

    def get_credentials(self) -> dict:
        """Get credentials dict for NATS connection."""
        creds = {}
        if self.config.nats_token:
            creds["token"] = self.config.nats_token
        if self.config.nats_user:
            creds["user"] = self.config.nats_user
        if self.config.nats_password:
            creds["password"] = self.config.nats_password
        if self.config.enable_tls:
            creds["tls"] = True
            if self.config.ca_cert_path:
                creds["ca_cert"] = self.config.ca_cert_path
        return creds

    def validate_connection(self, connection_info: dict) -> bool:
        """Validate a connection has proper authentication."""
        # Check if token or user/password is provided
        has_token = bool(connection_info.get("token"))
        has_user = bool(connection_info.get("user"))
        has_password = bool(connection_info.get("password"))

        return has_token or (has_user and has_password)


def generate_token(length: int = 32) -> str:
    """Generate a secure random token."""
    return secrets.token_hex(length)


def hash_token(token: str) -> str:
    """Hash a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()
