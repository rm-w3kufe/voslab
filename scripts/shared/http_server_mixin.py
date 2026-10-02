#!/usr/bin/env python3
"""http_server_mixin.py — Shared mixin for HTTP servers with log suppression.

Provides a common base class for HTTP request handlers that need to suppress
access logs (they go to journald instead).

Usage:
    from http_server_mixin import SilentHTTPHandler
    
    class MyHandler(SilentHTTPHandler):
        def do_GET(self):
            self._respond(200, b'{"status": "ok"}')

MIGRATION NOTE (2026-08-28): Extracted from duplicate implementations in:
- scripts/algedonic/vsf_algedonic_subscriber.py
- scripts/audit/compliance/vsf-audit-logger.py
"""
import http.server
import json
from typing import Optional


class SilentHTTPHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler with suppressed access logs.
    
    Subclass this and override do_GET, do_POST, etc. as needed.
    Use _respond() helper to send JSON responses.
    """
    
    def log_message(self, format, *args):
        """Suppress access logs to stderr (they go to journald)."""
        pass
    
    def _respond(self, code: int, body: bytes, content_type: str = "application/json") -> None:
        """Send an HTTP response with the given status code and body."""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def _respond_json(self, code: int, data: dict) -> None:
        """Send a JSON response with the given status code and data."""
        body = json.dumps(data).encode()
        self._respond(code, body)
    
    def _read_body(self) -> bytes:
        """Read the request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(content_length) if content_length > 0 else b""
    
    def _read_json(self) -> Optional[dict]:
        """Read and parse the request body as JSON."""
        body = self._read_body()
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None


class SilentHTTPServer(http.server.HTTPServer):
    """HTTP server with suppressed access logs."""
    
    def log_message(self, format, *args):
        """Suppress server-level logs."""
        pass


def create_silent_server(addr: tuple, handler_class: type) -> SilentHTTPServer:
    """Create a silent HTTP server with the given address and handler.
    
    Args:
        addr: Tuple of (host, port)
        handler_class: Request handler class (should inherit from SilentHTTPHandler)
    
    Returns:
        SilentHTTPServer instance
    """
    return SilentHTTPServer(addr, handler_class)
