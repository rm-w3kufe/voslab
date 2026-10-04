#!/usr/bin/env python3
"""s5-opsroom view-host (§7.3a) — minimal, stdlib-only HTTP+SSE server. NOT the legacy api.py.

Serves the panel scaffold (index.html) + an SSE φ↑ feed of the cybernetic-rag view-module. Each tick is
built by cybernetic_rag_view (synthetic source, AX-STATE-attested + verified, G-V3); the `certified` flag
drives the UI badge. Pure stdlib — no framework, no external runtime dep beyond python3-cryptography
(pulled in by state_attest). NATS φ↑ wiring is the next increment (§7.3b); here the source is synthetic.

Run on the view-host LXC (109):  VIEW_PORT=8088 python3 host.py
"""
import os
import sys
import json
import time
import random
import tempfile
import http.server
import socketserver

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cybernetic_rag_view as crv  # noqa: E402
import system_topology_view as stv  # noqa: E402
import s3_viz_view as s3v  # noqa: E402  (S3 resource bargain live view)
import formaid as fa  # noqa: E402  (the diagram studio)
import state_attest as ax  # noqa: E402
import qwen_mermaid_view as qmv  # noqa: E402  (Qwen→Mermaid generator panel)

PORT = int(os.environ.get("VIEW_PORT", "8088"))
HERE = os.path.dirname(os.path.abspath(__file__))
# Real φ↑ source: the nucleus events.jsonl materialized on the shared channel (RO bind-mount, §7.3b).
# If present → REAL chain-verified ticks; else → synthetic fallback (the feed never crashes).
EVENTS_PATH = os.environ.get("EVENTS_PATH", "/mnt/telemetry/events.jsonl")

# Ephemeral key + attest dir for the SYNTHETIC source (dogfood). The real source is the nucleus φ↑
# checkpoint (§7.3b); the certifier key is then the C1 custody track. Do not ship this key handling.
_KEYDIR = tempfile.mkdtemp(prefix="view-host-key-")
_ATTDIR = tempfile.mkdtemp(prefix="view-host-att-")
_SK, _PUB, _SIGNER = ax.load_or_generate_key(_KEYDIR)
_TRUSTED = {_SIGNER: _PUB}


def make_tick():
    """Prefer the REAL φ↑ (events.jsonl, chain-verified); fall back to synthetic if unavailable so the
    feed never crashes. The tick's `source` field tells which (nucleus-events.jsonl vs synthetic)."""
    if os.path.exists(EVENTS_PATH) and os.path.getsize(EVENTS_PATH) > 0:
        try:
            tick, _src, _ok = crv.build_tick_from_events(EVENTS_PATH)
            return tick
        except Exception:
            pass  # degrade to synthetic on any parse error
    return _synthetic_tick()


def _synthetic_tick():
    """Build one attested + verified view tick from a synthetic source (with liveness variation)."""
    stasis = round(random.uniform(0.88, 0.97), 4)
    in_omega = 1 if random.random() > 0.12 else 0          # occasionally exit Ω → degraded render
    recon = 1 if random.random() > 0.06 else 0
    con = crv.synthetic_source_con(stasis=stasis, in_omega=in_omega, reconciled=recon,
                                   lyap_l=round(random.uniform(0.005, 0.02), 4),
                                   lyap_dl=round(random.uniform(-0.0025, 0.0008), 4))
    crv.attest_source(con, _ATTDIR, _SK, _SIGNER)
    tick, _ = crv.build_tick(con, _ATTDIR, _TRUSTED)
    con.close()
    return tick


# The module registry — the view-host is a HOST for N view-modules (modularity law). Each is a
# {module_id: () -> tick} builder. Integrate = add a row + declare in coupling_registry; decommission =
# remove it. cybernetic-rag = the homeostatic loop (real φ↑); system-topology = the declared self-model.
MODULES = {
    "cybernetic-rag": make_tick,
    "system-topology": stv.build_tick,
    "s3-viz": s3v.build_tick,
    "qwen-mermaid": qmv.build_tick,
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name, ctype):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            with open(p, "rb") as f:
                self._send(200, ctype, f.read())
        else:
            self._send(404, "text/plain", b"not found")

    def do_GET(self):
        if self.path in ("/", "/index.html", "/studio"):       # the formaid studio = the product
            self._file("studio.html", "text/html; charset=utf-8")
        elif self.path == "/live":                              # the live modules dashboard
            self._file("index.html", "text/html; charset=utf-8")
        elif self.path == "/mermaid.min.js":                   # vendored locally (no runtime CDN)
            self._file("mermaid.min.js", "application/javascript")
        elif self.path == "/diagrams":                          # the studio catalog (templates+generators+saved)
            self._send(200, "application/json", json.dumps(fa.registry()).encode())
        elif self.path.startswith("/d/"):                       # /d/{id}  or  /d/{id}/export
            rest = self.path[len("/d/"):]
            if rest.endswith("/export"):
                rid = rest[:-len("/export")]
                html = fa.export_html(fa.get_mermaid(rid), rid)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{rid.replace(":", "_")}.html"')
                body = html.encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send(200, "text/plain; charset=utf-8", fa.get_mermaid(rest).encode())
        elif self.path == "/healthz":
            self._send(200, "text/plain", b"ok")
        elif self.path == "/api/qwen-mermaid-status":
            try:
                result = qmv.check_status()
                self._send(200, "application/json", json.dumps(result).encode())
            except Exception as e:
                self._send(200, "application/json", json.dumps({"ok": False, "error": str(e)}).encode())
        elif self.path == "/qwen-mermaid":
            self._file("qwen-mermaid.html", "text/html; charset=utf-8")
        elif self.path == "/modules":
            self._send(200, "application/json", json.dumps(list(MODULES.keys())).encode())
        elif self.path.startswith("/view/"):
            mid = self.path[len("/view/"):].split("?")[0].rstrip("/")
            fn = MODULES.get(mid)
            if fn is None:
                self._send(404, "text/plain", b"unknown module")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    try:
                        payload = json.dumps(fn())
                    except Exception as e:
                        payload = json.dumps({"module_id": mid, "error": str(e), "certified": False})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(2)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path == "/diagrams":
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                rec = fa.save_diagram(body.get("title", "untitled"), body.get("mermaid", ""))
                self._send(200, "application/json", json.dumps(rec).encode())
            except Exception as e:
                self._send(400, "application/json", json.dumps({"error": str(e)}).encode())
        elif self.path == "/api/qwen-mermaid":
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {"description": ""}
                result = qmv.generate(body.get("description", ""))
                self._send(200, "application/json", json.dumps(result).encode())
            except Exception as e:
                self._send(400, "application/json", json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self._send(404, "text/plain", b"not found")


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"s5-opsroom view-host on :{PORT} (synthetic source; §7.3a, no NATS yet)", flush=True)
    Server(("0.0.0.0", PORT), Handler).serve_forever()
